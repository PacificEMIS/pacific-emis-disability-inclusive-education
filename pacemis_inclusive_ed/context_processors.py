from django.conf import settings


def emis_context(request):
    """
    Makes settings.EMIS['CONTEXT'] available as {{ emis_context }} in all templates.
    """
    emis_cfg = getattr(settings, "EMIS", None)
    return {"emis_context": emis_cfg.get("CONTEXT") if emis_cfg else None}
