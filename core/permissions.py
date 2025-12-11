"""
Access control and permissions for the Pacific EMIS system.

This module implements a two-layer access control system:

Layer 1: App-Level Access (Profile + Group)
-------------------------------------------
Users must have:
  1. Authentication (login)
  2. Profile (SchoolStaff OR SystemUser)
  3. Group membership (at least one group)

Without all three, users see the "no permissions" page.

Layer 2: Row-Level Access (School-based filtering)
--------------------------------------------------
Enforced by permission functions in this module.
- Admins/System Admins: See all data
- SchoolStaff groups: See only data from their assigned schools
- SystemUser groups: See all data (system-wide access)

Permission Groups
-----------------
School-Level (for SchoolStaff users):
  - Admins: System-wide full access
  - School Admins: School-scoped admin (can manage their schools)
  - Teachers: School-scoped access for teachers
  - School Staff: Read-only at their schools

System-Level (for SystemUser users):
  - System Admins: System-wide full access
  - System Staff: System-wide read-only access
"""

from django.contrib.auth.models import Group
from django.db.models import Q, QuerySet

from integrations.models import EmisSchool
from core.models import SchoolStaff, SchoolStaffAssignment, Student, StudentSchoolEnrolment

# ============================================================================
# Group names (single source of truth)
# ============================================================================

# School-level groups (for SchoolStaff users)
GROUP_ADMINS = "Admins"
GROUP_SCHOOL_ADMINS = "School Admins"
GROUP_SCHOOL_STAFF = "School Staff"
GROUP_TEACHERS = "Teachers"

# System-level groups (for SystemUser users)
GROUP_SYSTEM_ADMINS = "System Admins"
GROUP_SYSTEM_STAFF = "System Staff"

# ============================================================================
# Role helpers
# ============================================================================


def _in_group(user, group_name: str) -> bool:
    """Check if user is in the specified group."""
    if not user or not user.is_authenticated:
        return False
    return user.groups.filter(name=group_name).exists()


def _in_any_group(user, *group_names: str) -> bool:
    """Check if user is in any of the specified groups."""
    if not user or not user.is_authenticated:
        return False
    return user.groups.filter(name__in=group_names).exists()


def is_admin(user) -> bool:
    """
    System-wide admins (plus superusers) have full access to everything.
    This includes both 'Admins' and 'System Admins' groups.
    """
    if not user or not user.is_authenticated:
        return False
    if user.is_superuser:
        return True
    return _in_any_group(user, GROUP_ADMINS, GROUP_SYSTEM_ADMINS)


def is_admins_group(user) -> bool:
    """
    Check if user is in the 'Admins' group specifically.
    Used for features that should only be accessible to the Admins group,
    like the Pending Users management.
    """
    if not user or not user.is_authenticated:
        return False
    if user.is_superuser:
        return True
    return _in_group(user, GROUP_ADMINS)


def is_school_staff(user) -> bool:
    """School Staff: Read-only access, per-school restricted."""
    return _in_group(user, GROUP_SCHOOL_STAFF)


def is_school_admin(user) -> bool:
    """School Admins: School-scoped admin; can manage staff/data at their schools."""
    return _in_group(user, GROUP_SCHOOL_ADMINS)


def is_teacher(user) -> bool:
    """Teachers: Per-school restricted access."""
    return _in_group(user, GROUP_TEACHERS)


def is_system_staff(user) -> bool:
    """System Staff: Read-only access, system-wide."""
    return _in_group(user, GROUP_SYSTEM_STAFF)


def is_system_level_user(user) -> bool:
    """
    Check if user has system-level access (can see MOE Staff UI).

    System-level users are:
    - Superusers
    - Admins group
    - System Admins group
    - System Staff group

    School-level users (School Admins, School Staff, Teachers) should NOT
    see the MOE Staff management UI.
    """
    if not user or not user.is_authenticated:
        return False
    if user.is_superuser:
        return True
    return _in_any_group(user, GROUP_ADMINS, GROUP_SYSTEM_ADMINS, GROUP_SYSTEM_STAFF)


def has_app_access(user) -> bool:
    """
    Check if user has any role that grants access to the application.
    Requires either SchoolStaff or SystemUser profile + a group membership.
    """
    if not user or not user.is_authenticated:
        return False

    if user.is_superuser:
        return True

    # Check if user has a profile (SchoolStaff or SystemUser)
    has_profile = hasattr(user, 'school_staff') or hasattr(user, 'system_user')
    if not has_profile:
        return False

    # Check if user is in any group
    return user.groups.exists()


# ============================================================================
# User ↔ School helpers
# ============================================================================


def get_user_schools(user):
    """
    Return the EmisSchool queryset for which the user has an *active*
    SchoolStaffAssignment.

    Active == assignment.end_date is NULL (no end date).
    Teachers and SchoolStaff both use this; Admins/superusers don't need it
    for permissions, but we might still use it for defaults later.
    """
    if not user or not user.is_authenticated:
        return EmisSchool.objects.none()

    # Check if user has SchoolStaff profile
    if not hasattr(user, 'school_staff'):
        return EmisSchool.objects.none()

    # SchoolStaffAssignment uses:
    #   school_staff -> SchoolStaff
    #   school_staff.user -> AUTH_USER
    #   school -> EmisSchool (related_name="staff_assignments")
    #   end_date (nullable)
    return EmisSchool.objects.filter(
        staff_assignments__school_staff__user=user,
        staff_assignments__end_date__isnull=True,
    ).distinct()


# ============================================================================
# SchoolStaff Permissions
# ============================================================================


def can_view_staff(user, staff: SchoolStaff) -> bool:
    """
    Who can *view* a staff member?

    - Admins/superusers/System Staff: always (system-wide access).
    - School Admins/School Staff/Teachers: only if they share at least one active school assignment.
    - Others: never.
    """
    if not user or not user.is_authenticated:
        return False
    if user.is_superuser or is_admin(user) or is_system_staff(user):
        return True
    if is_school_admin(user) or is_school_staff(user) or is_teacher(user):
        return user_has_school_access_to_staff(user, staff)
    return False


def user_has_school_access_to_staff(user, staff: SchoolStaff) -> bool:
    """
    Row-level rule: does this user have school-based access to this staff member?

    - Admins/superusers: always True.
    - School Admins/Teachers: only if there is at least one intersection between
      their active schools and the staff member's active schools.
    - Others: False.
    """
    if not user or not user.is_authenticated:
        return False

    if user.is_superuser or is_admin(user):
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
    Apply row-level access rules to a SchoolStaff queryset *for the list view*.

    - Superusers / Admins / System Staff: see all staff in qs (system-wide access).
    - School Admins / School Staff / Teachers: only see staff with whom they share
      at least one active school assignment.
    - Everyone else: see nothing.
    """
    if not user or not user.is_authenticated:
        return qs.none()

    # Admins/superusers/System Staff: no restriction (system-wide access)
    if user.is_superuser or is_admin(user) or is_system_staff(user):
        return qs

    # School-level users get per-school restricted views
    if not (is_school_admin(user) or is_school_staff(user) or is_teacher(user)):
        return qs.none()

    # Get the user's active schools
    user_schools = get_user_schools(user)
    if not user_schools.exists():
        return qs.none()

    # Filter staff who have active assignments in any of the user's schools
    allowed_school_nos = list(user_schools.values_list("emis_school_no", flat=True))

    if not allowed_school_nos:
        return qs.none()

    # Filter by staff who have assignments at schools the user has access to
    # Using the annotated latest_school_no field from the view
    return qs.filter(latest_school_no__in=allowed_school_nos)


def can_create_staff_assignment(user, target_school=None) -> bool:
    """
    Who can *create* a staff school assignment?

    - Admins/superusers: always (any school).
    - School Admins: only for their active schools.
    - Others: never.

    Args:
        user: The user attempting the action
        target_school: Optional EmisSchool instance to validate school-scoped access
    """
    if not user or not user.is_authenticated:
        return False

    # System admins can create assignments for any school
    if user.is_superuser or is_admin(user):
        return True

    # School admins can only create assignments for schools they have access to
    if is_school_admin(user):
        if target_school is None:
            # Permission check without specific school - allow attempt
            # (school validation happens later in the view/form)
            return True
        # Validate that the target school is one of the user's active schools
        user_schools = get_user_schools(user)
        return user_schools.filter(pk=target_school.pk).exists()

    return False


def can_edit_staff_assignment(user, assignment) -> bool:
    """
    Who can *edit* a staff school assignment?

    - Admins/superusers: always.
    - School Admins: only if the assignment is for one of their active schools.
    - Others: never.

    Args:
        user: The user attempting the action
        assignment: SchoolStaffAssignment instance to edit
    """
    if not user or not user.is_authenticated:
        return False

    # System admins can edit any assignment
    if user.is_superuser or is_admin(user):
        return True

    # School admins can only edit assignments for their schools
    if is_school_admin(user):
        user_schools = get_user_schools(user)
        return user_schools.filter(pk=assignment.school.pk).exists()

    return False


def can_delete_staff_assignment(user, assignment) -> bool:
    """
    Who can *delete* a staff school assignment?

    - Admins/superusers: always.
    - School Admins: only if the assignment is for one of their active schools.
    - Others: never.

    Args:
        user: The user attempting the action
        assignment: SchoolStaffAssignment instance to delete
    """
    if not user or not user.is_authenticated:
        return False

    # System admins can delete any assignment
    if user.is_superuser or is_admin(user):
        return True

    # School admins can only delete assignments for their schools
    if is_school_admin(user):
        user_schools = get_user_schools(user)
        return user_schools.filter(pk=assignment.school.pk).exists()

    return False


# ============================================================================
# Student ↔ School helpers
# ============================================================================


def get_effective_student_schools(student: Student):
    """
    Which school(s) 'own' this student for access control?

    Policy (for now):
      1) If there are current_enrolments, use those schools.
      2) Otherwise, use the school from the most recent enrolment.

    'Most recent' here is approximated by SchoolYear code (descending),
    then by start_date (if present), then by PK as a final tiebreaker.

    This function is the main hook if we ever change the policy to include
    more/less history.
    """
    # 1) Try current_enrolments (you already defined this property on Student)
    current = student.current_enrolments
    if current.exists():
        return EmisSchool.objects.filter(pk__in=current.values("school_id")).distinct()

    # 2) No current enrolments → fall back to latest enrolment
    all_enrolments = student.enrolments.select_related("school_year", "school")  # type: ignore[attr-defined]
    if not all_enrolments.exists():
        return EmisSchool.objects.none()

    latest = all_enrolments.order_by(
        "-school_year__code",  # newest school year first
        "-start_date",  # then by start date if present
        "-pk",  # stable tiebreaker
    ).first()
    return EmisSchool.objects.filter(pk=latest.school_id)


# ============================================================================
# Student Permissions
# ============================================================================


def user_has_school_access_to_student(user, student: Student) -> bool:
    """
    Row-level rule: does this user have school-based access to this student?

    - Admins/superusers: always True.
    - School Staff/Teachers: only if there is at least one intersection between
      their active schools and the student's effective schools.
    - Others: False.
    """
    if not user or not user.is_authenticated:
        return False

    if user.is_superuser or is_admin(user):
        return True

    user_schools = get_user_schools(user)
    if not user_schools.exists():
        return False

    student_schools = get_effective_student_schools(student)
    if not student_schools.exists():
        return False

    return student_schools.filter(pk__in=user_schools.values("pk")).exists()


def can_create_student(user) -> bool:
    """
    Who can *create* a student (profile/enrolments/disability)?

    - Admins/superusers: always.
    - School Admins: yes (at their schools).
    - Teachers: yes (at their schools).
    - School Staff: never (read-only).
    """
    if not user or not user.is_authenticated:
        return False
    if user.is_superuser or is_admin(user):
        return True
    if is_school_admin(user) or is_teacher(user):
        return True
    return False


def can_view_student(user, student: Student) -> bool:
    """
    Who can *view* a student?

    - Admins/superusers/System Staff: always (system-wide access).
    - School Admins/School Staff/Teachers: only if they have school access to that student.
    - Others: never.
    """
    if not user or not user.is_authenticated:
        return False
    if user.is_superuser or is_admin(user) or is_system_staff(user):
        return True
    if is_school_admin(user) or is_school_staff(user) or is_teacher(user):
        return user_has_school_access_to_student(user, student)
    return False


def can_edit_student(user, student: Student) -> bool:
    """
    Who can *edit* a student (profile/enrolments/disability)?

    - Admins/superusers: always.
    - School Admins: if they have school access.
    - Teachers: if they have school access.
    - School Staff: never (read-only).
    """
    if not user or not user.is_authenticated:
        return False
    if user.is_superuser or is_admin(user):
        return True
    if is_school_admin(user) or is_teacher(user):
        return user_has_school_access_to_student(user, student)
    return False


def can_delete_student(user, student: Student) -> bool:
    """
    Who can *delete* a student? (very restricted)

    - Admins/superusers only.
    """
    if not user or not user.is_authenticated:
        return False
    return user.is_superuser or is_admin(user)


def filter_students_for_user(qs: QuerySet, user) -> QuerySet:
    """
    Apply row-level access rules to a Student queryset *for the list view*,
    where qs is expected to have `latest_school_no` annotated.

    - Superusers / Admins / System Staff: see all students in qs (system-wide access).
    - School Admins / School Staff / Teachers: only see students whose latest_school_no
      is one of their active SchoolStaffAssignment schools.
    - Everyone else: see nothing.
    """
    if not user or not user.is_authenticated:
        return qs.none()

    # Admins/superusers/System Staff: no restriction (system-wide access)
    if user.is_superuser or is_admin(user) or is_system_staff(user):
        return qs

    # School-level users get per-school restricted views
    if not (is_school_admin(user) or is_school_staff(user) or is_teacher(user)):
        return qs.none()

    # Get the user's active schools
    user_schools = get_user_schools(user)
    if not user_schools.exists():
        return qs.none()

    # We restrict by emis_school_no because the list queryset already
    # annotates latest_school_no from the latest enrolment.
    allowed_school_nos = list(user_schools.values_list("emis_school_no", flat=True))

    if not allowed_school_nos:
        return qs.none()

    return qs.filter(latest_school_no__in=allowed_school_nos)


def get_allowed_enrolment_schools(user):
    """
    Schools a user is allowed to *write* enrolments/disability data for.

    - Superusers + Admins: all active schools.
    - School Admins: their active membership schools (get_user_schools).
    - Teachers: their active membership schools (get_user_schools).
    - School Staff: read-only, so they get no write schools here.
    - Others: none.
    """
    if not user or not user.is_authenticated:
        return EmisSchool.objects.none()

    if user.is_superuser or is_admin(user):
        return EmisSchool.objects.filter(active=True).order_by("emis_school_name")

    if is_school_admin(user) or is_teacher(user):
        return get_user_schools(user).order_by("emis_school_name")

    # Staff and other users are read-only
    return EmisSchool.objects.none()
