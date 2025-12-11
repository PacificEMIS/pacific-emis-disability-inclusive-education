from django import template
from core.permissions import (
    can_create_student,
    can_edit_student,
    can_delete_student
)

register = template.Library()

@register.filter(name="can_create_student")
def can_create_student_filter(user):
    """
    Usage: {{ user|can_create_student }}
    Returns True/False.
    """
    return can_create_student(user)

@register.filter(name="can_edit_student")
def can_edit_student_filter(user, student):
    """
    Usage: {{ user|can_edit_student:student }}
    Returns True/False.
    """
    if user is None or student is None:
        return False
    return can_edit_student(user, student)

@register.filter(name="can_delete_student")
def can_delete_student_filter(user, student):
    """
    Usage: {{ user|can_delete_student:student }}
    Returns True/False.
    """
    if user is None or student is None:
        return False
    return can_delete_student(user, student)
