from django.contrib.auth.models import Group
from django.db.models import Q
from django.db.models import QuerySet


from integrations.models import EmisSchool
from inclusive_ed.models import Student, StudentSchoolEnrolment
from accounts.models import StaffSchoolMembership

# ---- Group names (single source of truth) ----

GROUP_INCLUSIVE_ADMINS = "InclusiveEd - Admins"
GROUP_INCLUSIVE_STAFF = "InclusiveEd - Staff"
GROUP_INCLUSIVE_TEACHERS = "InclusiveEd - Teachers"

# ---- Role helpers -----------------------------------------------------------

def _in_group(user, group_name: str) -> bool:
    if not user or not user.is_authenticated:
        return False
    return user.groups.filter(name=group_name).exists()


def is_inclusive_admin(user) -> bool:
    """Admins (plus superusers) have system-wide full access."""
    if not user or not user.is_authenticated:
        return False
    if user.is_superuser:
        return True
    return _in_group(user, GROUP_INCLUSIVE_ADMINS)


def is_inclusive_staff(user) -> bool:
    """Read-only, per-school restricted."""
    return _in_group(user, GROUP_INCLUSIVE_STAFF)


def is_inclusive_teacher(user) -> bool:
    """Per-school restricted; can add/edit (no delete)."""
    return _in_group(user, GROUP_INCLUSIVE_TEACHERS)

# ---- User ↔ School helpers --------------------------------------------------

def get_user_schools(user):
    """
    Return the EmisSchool queryset for which the user has an *active*
    StaffSchoolMembership.

    Active == membership.end_date is NULL (no end date).
    Teachers and Staff both use this; Admins/superusers don't need it
    for permissions, but we might still use it for defaults later.
    """
    if not user or not user.is_authenticated:
        return EmisSchool.objects.none()

    # Assumes StaffSchoolMembership has:
    #   staff -> Staff
    #   staff.user -> AUTH_USER
    #   school -> EmisSchool (related_name="memberships")
    #   end_date (nullable)
    return (
        EmisSchool.objects.filter(
            memberships__staff__user=user,
            memberships__end_date__isnull=True,
        )
        .distinct()
    )


# ---- Student ↔ School helpers ----------------------------------------------

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
        return EmisSchool.objects.filter(
            pk__in=current.values("school_id")
        ).distinct()

    # 2) No current enrolments → fall back to latest enrolment
    all_enrolments = student.enrolments.select_related("school_year", "school")
    if not all_enrolments.exists():
        return EmisSchool.objects.none()

    latest = (
        all_enrolments
        .order_by(
            "-school_year__code",  # newest school year first
            "-start_date",         # then by start date if present
            "-pk",                 # stable tiebreaker
        )
        .first()
    )
    return EmisSchool.objects.filter(pk=latest.school_id)


# ---- Core access check: user ↔ student via schools -------------------------

def user_has_school_access_to_student(user, student: Student) -> bool:
    """
    Row-level rule: does this user have school-based access to this student?

    - Admins/superusers: always True.
    - Staff/Teachers: only if there is at least one intersection between
      their active schools and the student's effective schools.
    - Others: False.
    """
    if not user or not user.is_authenticated:
        return False

    if user.is_superuser or is_inclusive_admin(user):
        return True

    user_schools = get_user_schools(user)
    if not user_schools.exists():
        return False

    student_schools = get_effective_student_schools(student)
    if not student_schools.exists():
        return False

    return student_schools.filter(pk__in=user_schools.values("pk")).exists()


# ---- Convenience helpers we’ll use in views later --------------------------

def can_create_student(user) -> bool:
    """
    Who can *create* a student (profile/enrolments/disability)?

    - Admins/superusers: always.
    - InclusiveEd – Admins
    - Teachers: if they have school access.
    - Staff: never (read-only).
    """
    if not user or not user.is_authenticated:
        return False
    if user.is_superuser or is_inclusive_admin(user):
        return True
    if is_inclusive_teacher(user):
        return True
    return False

def can_view_student(user, student: Student) -> bool:
    """
    Who can *view* a student?

    - Admins/superusers: always.
    - Staff/Teachers: only if they have school access to that student.
    - Others: never.
    """
    if not user or not user.is_authenticated:
        return False
    if user.is_superuser or is_inclusive_admin(user):
        return True
    if is_inclusive_staff(user) or is_inclusive_teacher(user):
        return user_has_school_access_to_student(user, student)
    return False


def can_edit_student(user, student: Student) -> bool:
    """
    Who can *edit* a student (profile/enrolments/disability)?

    - Admins/superusers: always.
    - Teachers: if they have school access.
    - Staff: never (read-only).
    """
    if not user or not user.is_authenticated:
        return False
    if user.is_superuser or is_inclusive_admin(user):
        return True
    if is_inclusive_teacher(user):
        return user_has_school_access_to_student(user, student)
    return False


def can_delete_student(user, student: Student) -> bool:
    """
    Who can *delete* a student? (very restricted)

    - Admins/superusers only.
    """
    if not user or not user.is_authenticated:
        return False
    return user.is_superuser or is_inclusive_admin(user)

def filter_students_for_user(qs: QuerySet, user) -> QuerySet:
    """
    Apply row-level access rules to a Student queryset *for the list view*,
    where qs is expected to have `latest_school_no` annotated.

    - Superusers / InclusiveEd - Admins: see all students in qs.
    - InclusiveEd - Staff / Teachers: only see students whose latest_school_no
      is one of their active StaffSchoolMembership schools.
    - Everyone else: see nothing.
    """
    if not user or not user.is_authenticated:
        return qs.none()

    # Admins/superusers: no restriction
    if user.is_superuser or is_inclusive_admin(user):
        return qs

    # Only Staff / Teachers get per-school restricted views
    if not (is_inclusive_staff(user) or is_inclusive_teacher(user)):
        return qs.none()

    # Get the user’s active schools
    user_schools = get_user_schools(user)
    if not user_schools.exists():
        return qs.none()

    # We restrict by emis_school_no because the list queryset already
    # annotates latest_school_no from the latest enrolment.
    allowed_school_nos = list(
        user_schools.values_list("emis_school_no", flat=True)
    )

    if not allowed_school_nos:
        return qs.none()

    return qs.filter(latest_school_no__in=allowed_school_nos)

def get_allowed_enrolment_schools(user):
    """
    Schools a user is allowed to *write* enrolments/disability data for.

    - Superusers + InclusiveEd - Admins: all active schools.
    - InclusiveEd - Teachers: their active membership schools (get_user_schools).
    - InclusiveEd - Staff: read-only, so they get no write schools here.
    - Others: none.
    """
    if not user or not user.is_authenticated:
        return EmisSchool.objects.none()

    if user.is_superuser or is_inclusive_admin(user):
        return EmisSchool.objects.filter(active=True).order_by("emis_school_name")

    if is_inclusive_teacher(user):
        return get_user_schools(user).order_by("emis_school_name")

    # Staff and other users are read-only
    return EmisSchool.objects.none()