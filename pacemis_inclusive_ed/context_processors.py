from django.conf import settings


def emis_context(request):
    """
    Makes settings.EMIS['CONTEXT'] available as {{ emis_context }} in all templates.
    Also provides {{ emis_logo }} — the lowercase first word of CONTEXT for logo filenames
    (e.g. "KEMIS (Dev)" → "kemis").
    """
    emis_cfg = getattr(settings, "EMIS", None)
    context_str = emis_cfg.get("CONTEXT", "") if emis_cfg else ""
    logo_name = context_str.split()[0].lower() if context_str else "logo"
    return {
        "emis_context": context_str or None,
        "emis_logo": logo_name,
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
