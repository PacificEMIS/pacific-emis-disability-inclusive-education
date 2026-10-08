from django import template

register = template.Library()

@register.filter
def get_item(d, key):
    try:
        return d.get(key)
    except Exception:
        return None


@register.filter
def getfield(obj, name):
    """Return an attribute of an object by name (for dynamic table columns)."""
    return getattr(obj, name, "")
