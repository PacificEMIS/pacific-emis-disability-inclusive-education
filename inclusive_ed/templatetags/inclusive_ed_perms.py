from django import template
from inclusive_ed.permissions import can_manage_inclusive_ed as _check_perm

register = template.Library()

@register.filter(name="can_manage_inclusive_ed")
def can_manage_inclusive_ed_tag(user):
    return _check_perm(user)
