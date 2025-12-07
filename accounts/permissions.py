"""
Row-level permissions for the accounts app (Staff).

Mirrors the pattern from inclusive_ed.permissions.
"""

from django.db.models import QuerySet

from inclusive_ed.permissions import (
    is_inclusive_admin,
    is_inclusive_school_admin,
    is_inclusive_teacher,
    get_user_schools,
)
from accounts.models import Staff


def can_view_staff(user, staff: Staff) -> bool:
    """
    Who can *view* a staff member?

    - Admins/superusers: always.
    - School Admins: only if they share at least one active school membership.
    - Teachers: only if they share at least one active school membership.
    - Others: never.
    """
    if not user or not user.is_authenticated:
        return False
    if user.is_superuser or is_inclusive_admin(user):
        return True
    if is_inclusive_school_admin(user) or is_inclusive_teacher(user):
        return user_has_school_access_to_staff(user, staff)
    return False


def user_has_school_access_to_staff(user, staff: Staff) -> bool:
    """
    Row-level rule: does this user have school-based access to this staff member?

    - Admins/superusers: always True.
    - Teachers: only if there is at least one intersection between
      their active schools and the staff member's active schools.
    - Others: False.
    """
    if not user or not user.is_authenticated:
        return False

    if user.is_superuser or is_inclusive_admin(user):
        return True

    user_schools = get_user_schools(user)
    if not user_schools.exists():
        return False

    staff_schools = get_user_schools(staff.user)
    if not staff_schools.exists():
        return False

    return staff_schools.filter(pk__in=user_schools.values("pk")).exists()


def filter_staff_for_user(qs: QuerySet, user) -> QuerySet:
    """
    Apply row-level access rules to a Staff queryset *for the list view*.

    - Superusers / InclusiveEd - Admins: see all staff in qs.
    - InclusiveEd - School Admins: only see staff with whom they share at least
      one active school membership.
    - InclusiveEd - Teachers: only see staff with whom they share at least
      one active school membership.
    - Everyone else: see nothing.
    """
    if not user or not user.is_authenticated:
        return qs.none()

    # Admins/superusers: no restriction
    if user.is_superuser or is_inclusive_admin(user):
        return qs

    # Only School Admins and Teachers get per-school restricted views
    if not (is_inclusive_school_admin(user) or is_inclusive_teacher(user)):
        return qs.none()

    # Get the user's active schools
    user_schools = get_user_schools(user)
    if not user_schools.exists():
        return qs.none()

    # Filter staff who have active memberships in any of the user's schools
    allowed_school_nos = list(user_schools.values_list("emis_school_no", flat=True))

    if not allowed_school_nos:
        return qs.none()

    # Filter by staff who have memberships at schools the user has access to
    # Using the annotated latest_school_no field from the view
    return qs.filter(latest_school_no__in=allowed_school_nos)


def can_create_staff_membership(user, target_school=None) -> bool:
    """
    Who can *create* a staff school membership?

    - Admins/superusers: always (any school).
    - School Admins: only for their active schools.
    - Others: never.

    Args:
        user: The user attempting the action
        target_school: Optional EmisSchool instance to validate school-scoped access
    """
    if not user or not user.is_authenticated:
        return False

    # System admins can create memberships for any school
    if user.is_superuser or is_inclusive_admin(user):
        return True

    # School admins can only create memberships for schools they have access to
    if is_inclusive_school_admin(user):
        if target_school is None:
            # Permission check without specific school - allow attempt
            # (school validation happens later in the view/form)
            return True
        # Validate that the target school is one of the user's active schools
        user_schools = get_user_schools(user)
        return user_schools.filter(pk=target_school.pk).exists()

    return False


def can_edit_staff_membership(user, membership) -> bool:
    """
    Who can *edit* a staff school membership?

    - Admins/superusers: always.
    - School Admins: only if the membership is for one of their active schools.
    - Others: never.

    Args:
        user: The user attempting the action
        membership: StaffSchoolMembership instance to edit
    """
    if not user or not user.is_authenticated:
        return False

    # System admins can edit any membership
    if user.is_superuser or is_inclusive_admin(user):
        return True

    # School admins can only edit memberships for their schools
    if is_inclusive_school_admin(user):
        user_schools = get_user_schools(user)
        return user_schools.filter(pk=membership.school.pk).exists()

    return False


def can_delete_staff_membership(user, membership) -> bool:
    """
    Who can *delete* a staff school membership?

    - Admins/superusers: always.
    - School Admins: only if the membership is for one of their active schools.
    - Others: never.

    Args:
        user: The user attempting the action
        membership: StaffSchoolMembership instance to delete
    """
    if not user or not user.is_authenticated:
        return False

    # System admins can delete any membership
    if user.is_superuser or is_inclusive_admin(user):
        return True

    # School admins can only delete memberships for their schools
    if is_inclusive_school_admin(user):
        user_schools = get_user_schools(user)
        return user_schools.filter(pk=membership.school.pk).exists()

    return False
