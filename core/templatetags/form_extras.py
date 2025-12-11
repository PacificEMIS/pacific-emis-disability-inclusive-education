from django import template

register = template.Library()

@register.filter
def form_field(form, name):
    """
    Return a BoundField from a form by field name, e.g. {{ form|form_field:"first_name" }}.
    Safe to use with dynamic field names in templates.
    """
    try:
        return form[name]
    except Exception:
        return None
