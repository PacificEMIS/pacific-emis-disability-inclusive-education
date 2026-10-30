import re

from django.conf import settings

# "KEMIS (Dev)" -> the system's name and, in parentheses, the environment it is
# not production in. A context with no parenthetical is production.
_CONTEXT_WITH_ENVIRONMENT = re.compile(r"^(?P<name>.*?)\s*\((?P<environment>[^)]+)\)\s*$")


def emis_context(request):
    """
    Makes settings.EMIS['CONTEXT'] available as {{ emis_context }} in all templates.
    Also provides {{ emis_logo }} — the lowercase first word of CONTEXT for logo filenames
    (e.g. "KEMIS (Dev)" → "kemis") — and splits the context into {{ emis_name }} and
    {{ emis_environment }}: "KEMIS (Dev)" → "KEMIS" and "Dev". The environment is None
    in production, where the context carries no parenthetical, and every template that
    warns a user they are not in production keys off it.
    """
    emis_cfg = getattr(settings, "EMIS", None)
    context_str = emis_cfg.get("CONTEXT", "") if emis_cfg else ""
    logo_name = context_str.split()[0].lower() if context_str else "logo"
    match = _CONTEXT_WITH_ENVIRONMENT.match(context_str) if context_str else None
    name = match.group("name").strip() if match else context_str
    environment = match.group("environment").strip() if match else None
    return {
        "emis_context": context_str or None,
        "emis_logo": logo_name,
        "emis_name": name or None,
        "emis_environment": environment or None,
    }


def app_name(request):
    """
    Makes settings.APP_NAME available as {{ app_name }} in all templates.
    """
    return {"app_name": getattr(settings, "APP_NAME", "Pacific EMIS")}


def terminology(request):
    """
    Makes customizable terminology available in all templates.

    Available in templates as:
    - {{ terminology.system_users_singular }} (e.g., "System User", "MOE Staff")
    - {{ terminology.system_users_plural }} (e.g., "System Users", "MOE Staff")
    """
    terminology_cfg = getattr(settings, "TERMINOLOGY", {})
    return {
        "terminology": {
            "system_users_singular": terminology_cfg.get("SYSTEM_USERS_SINGULAR", "System User"),
            "system_users_plural": terminology_cfg.get("SYSTEM_USERS_PLURAL", "System Users"),
        }
    }
