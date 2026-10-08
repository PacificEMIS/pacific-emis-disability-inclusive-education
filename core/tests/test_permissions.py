"""
Unit tests for core.permissions: the complete role x action matrix.

Every role fixture is crossed with every permission function against
targets at the user's own school (school_a), at another school (school_b)
and with no school at all. The tables below are the executable
specification of the access rules documented at the top of
core/permissions.py; a change in either must be reflected in the other.

Role fixture names used in the tables:
  superuser, admin_user, system_admin_user, system_staff_user,
  school_admin_user, teacher_user, school_staff_user, pending_user
"""

import datetime as dt

import pytest
import time_machine
from django.contrib.auth.models import AnonymousUser
from django.db.models import OuterRef, Subquery

from conftest import (
    SchoolStaffAssignmentFactory,
    SchoolStaffFactory,
    StudentFactory,
    StudentSchoolEnrolmentFactory,
    EmisSchoolFactory,
    EmisWarehouseYearFactory,
    UserFactory,
)
from core import permissions as perms
from core.models import SchoolStaff, SchoolStaffAssignment, Student, StudentSchoolEnrolment

pytestmark = pytest.mark.django_db

ALL_ROLES = [
    "superuser",
    "admin_user",
    "system_admin_user",
    "system_staff_user",
    "school_admin_user",
    "teacher_user",
    "school_staff_user",
    "pending_user",
]

SYSTEM_WIDE = {"superuser", "admin_user", "system_admin_user"}
SYSTEM_WIDE_READERS = SYSTEM_WIDE | {"system_staff_user"}
SCHOOL_SCOPED = {"school_admin_user", "teacher_user", "school_staff_user"}


def expect(true_for):
    """Build a parametrize list: (role, expected) for every role."""
    return [(role, role in true_for) for role in ALL_ROLES]


@pytest.fixture
def targets(db, school_a, school_b, school_year, class_level, job_title):
    """Staff and students at school A, at school B, and with no school."""
    staff_a = SchoolStaffAssignmentFactory(school=school_a, job_title=job_title).school_staff
    staff_b = SchoolStaffAssignmentFactory(school=school_b, job_title=job_title).school_staff
    staff_none = SchoolStaffFactory()
    student_a = StudentSchoolEnrolmentFactory(
        school=school_a, school_year=school_year, class_level=class_level
    ).student
    student_b = StudentSchoolEnrolmentFactory(
        school=school_b, school_year=school_year, class_level=class_level
    ).student
    student_none = StudentFactory()
    return {
        "staff_a": staff_a,
        "staff_b": staff_b,
        "staff_none": staff_none,
        "student_a": student_a,
        "student_b": student_b,
        "student_none": student_none,
    }


# ============================================================================
# Role helpers
# ============================================================================


class TestRoleHelpers:
    @pytest.mark.parametrize("role,expected", expect(SYSTEM_WIDE))
    def test_is_admin(self, request, role, expected):
        assert perms.is_admin(request.getfixturevalue(role)) is expected

    @pytest.mark.parametrize("role,expected", expect({"superuser", "admin_user"}))
    def test_is_admins_group(self, request, role, expected):
        assert perms.is_admins_group(request.getfixturevalue(role)) is expected

    @pytest.mark.parametrize("role,expected", expect(SYSTEM_WIDE_READERS))
    def test_is_system_level_user(self, request, role, expected):
        assert perms.is_system_level_user(request.getfixturevalue(role)) is expected

    @pytest.mark.parametrize("role,expected", expect({"school_admin_user"}))
    def test_is_school_admin(self, request, role, expected):
        assert perms.is_school_admin(request.getfixturevalue(role)) is expected

    @pytest.mark.parametrize("role,expected", expect({"teacher_user"}))
    def test_is_teacher(self, request, role, expected):
        assert perms.is_teacher(request.getfixturevalue(role)) is expected

    @pytest.mark.parametrize("role,expected", expect({"school_staff_user"}))
    def test_is_school_staff(self, request, role, expected):
        assert perms.is_school_staff(request.getfixturevalue(role)) is expected

    @pytest.mark.parametrize("role,expected", expect({"system_staff_user"}))
    def test_is_system_staff(self, request, role, expected):
        assert perms.is_system_staff(request.getfixturevalue(role)) is expected

    @pytest.mark.parametrize(
        "fn",
        [
            perms.is_admin,
            perms.is_admins_group,
            perms.is_system_level_user,
            perms.is_school_admin,
            perms.is_teacher,
            perms.is_school_staff,
            perms.is_system_staff,
            perms.has_app_access,
            perms.can_create_student,
            perms.can_manage_pending_users,
            perms.can_assign_admins_group,
        ],
    )
    def test_anonymous_and_none_are_never_granted(self, fn):
        assert fn(AnonymousUser()) is False
        assert fn(None) is False


class TestHasAppAccess:
    @pytest.mark.parametrize("role,expected", expect(set(ALL_ROLES) - {"pending_user"}))
    def test_matrix(self, request, role, expected):
        assert perms.has_app_access(request.getfixturevalue(role)) is expected

    def test_profile_without_group_is_denied(self, profile_only_user):
        assert perms.has_app_access(profile_only_user) is False

    def test_group_without_profile_is_denied(self, pending_user):
        pending_user.groups.add(perms.Group.objects.get(name=perms.GROUP_TEACHERS))
        assert perms.has_app_access(pending_user) is False

    def test_inactive_user_with_profile_and_group_still_passes_function(self, teacher_user):
        # has_app_access does not check is_active; login does. Pin that.
        teacher_user.is_active = False
        assert perms.has_app_access(teacher_user) is True


# ============================================================================
# User <-> school helpers
# ============================================================================


class TestGetUserSchools:
    def test_school_roles_see_their_school_only(self, teacher_user, school_a, school_b):
        assert list(perms.get_user_schools(teacher_user)) == [school_a]

    @pytest.mark.parametrize("role", ["system_admin_user", "system_staff_user", "pending_user"])
    def test_users_without_school_staff_profile_have_no_schools(self, request, role):
        assert not perms.get_user_schools(request.getfixturevalue(role)).exists()

    def test_anonymous_has_no_schools(self):
        assert not perms.get_user_schools(AnonymousUser()).exists()

    def test_distinct_when_several_assignments_at_same_school(
        self, make_school_user, school_a, job_title
    ):
        user = make_school_user(perms.GROUP_TEACHERS, schools=[school_a])
        SchoolStaffAssignmentFactory(
            school_staff=user.school_staff,
            school=school_a,
            job_title=job_title,
            start_date=dt.date(2020, 1, 1),
        )
        assert list(perms.get_user_schools(user)) == [school_a]

    @time_machine.travel(dt.datetime(2026, 6, 15, 12, 0, tzinfo=dt.timezone.utc))
    @pytest.mark.parametrize(
        "start,end,active",
        [
            (None, None, True),
            (dt.date(2026, 6, 15), None, True),  # starts today
            (dt.date(2026, 6, 16), None, False),  # starts tomorrow
            (None, dt.date(2026, 6, 15), True),  # ends today
            (None, dt.date(2026, 6, 14), False),  # ended yesterday
            (None, dt.date(2027, 1, 1), True),  # future end date (PR #71)
            (dt.date(2026, 1, 1), dt.date(2026, 12, 31), True),
            (dt.date(2025, 1, 1), dt.date(2025, 12, 31), False),
        ],
        ids=[
            "open",
            "starts-today",
            "starts-tomorrow",
            "ends-today",
            "ended-yesterday",
            "future-end",
            "covers-today",
            "last-year",
        ],
    )
    def test_assignment_date_boundaries(self, make_school_user, school_a, job_title, start, end, active):
        user = make_school_user(perms.GROUP_TEACHERS)
        SchoolStaffAssignmentFactory(
            school_staff=user.school_staff,
            school=school_a,
            job_title=job_title,
            start_date=start,
            end_date=end,
        )
        assert perms.get_user_schools(user).exists() is active


# ============================================================================
# SchoolStaff permissions
# ============================================================================


class TestStaffPermissions:
    @pytest.mark.parametrize("role,expected", expect(SYSTEM_WIDE_READERS | SCHOOL_SCOPED))
    def test_can_view_staff_at_own_school(self, request, targets, role, expected):
        user = request.getfixturevalue(role)
        assert perms.can_view_staff(user, targets["staff_a"]) is expected

    @pytest.mark.parametrize("role,expected", expect(SYSTEM_WIDE_READERS))
    def test_can_view_staff_at_other_school(self, request, targets, role, expected):
        user = request.getfixturevalue(role)
        assert perms.can_view_staff(user, targets["staff_b"]) is expected

    @pytest.mark.parametrize("role,expected", expect(SYSTEM_WIDE_READERS))
    def test_can_view_unassigned_staff(self, request, targets, role, expected):
        user = request.getfixturevalue(role)
        assert perms.can_view_staff(user, targets["staff_none"]) is expected

    @pytest.mark.parametrize("role,expected", expect(SYSTEM_WIDE | {"school_admin_user"}))
    def test_can_edit_staff_at_own_school(self, request, targets, role, expected):
        user = request.getfixturevalue(role)
        assert perms.can_edit_staff(user, targets["staff_a"]) is expected
        assert perms.can_edit_staff_groups(user, targets["staff_a"]) is expected

    @pytest.mark.parametrize("role,expected", expect(SYSTEM_WIDE))
    def test_can_edit_staff_at_other_school(self, request, targets, role, expected):
        user = request.getfixturevalue(role)
        assert perms.can_edit_staff(user, targets["staff_b"]) is expected
        assert perms.can_edit_staff_groups(user, targets["staff_b"]) is expected

    def test_can_view_staff_rejects_anonymous(self, targets):
        assert perms.can_view_staff(AnonymousUser(), targets["staff_a"]) is False
        assert perms.can_edit_staff(AnonymousUser(), targets["staff_a"]) is False

    def test_school_access_to_staff_requires_overlap_on_both_sides(
        self, school_admin_user, targets
    ):
        # The target has no active school, so there is nothing to overlap with.
        assert perms.user_has_school_access_to_staff(school_admin_user, targets["staff_none"]) is False

    def test_school_admin_without_active_school_has_no_access(self, make_school_user, targets):
        user = make_school_user(perms.GROUP_SCHOOL_ADMINS)  # no assignments
        assert perms.user_has_school_access_to_staff(user, targets["staff_a"]) is False
        assert perms.can_edit_staff(user, targets["staff_a"]) is False


class TestStaffAssignmentPermissions:
    @pytest.mark.parametrize("role,expected", expect(SYSTEM_WIDE | {"school_admin_user"}))
    def test_create_without_target_school(self, request, role, expected):
        user = request.getfixturevalue(role)
        assert perms.can_create_staff_assignment(user) is expected

    @pytest.mark.parametrize("role,expected", expect(SYSTEM_WIDE | {"school_admin_user"}))
    def test_create_for_own_school(self, request, school_a, role, expected):
        user = request.getfixturevalue(role)
        assert perms.can_create_staff_assignment(user, school_a) is expected

    @pytest.mark.parametrize("role,expected", expect(SYSTEM_WIDE))
    def test_create_for_other_school(self, request, school_b, role, expected):
        user = request.getfixturevalue(role)
        assert perms.can_create_staff_assignment(user, school_b) is expected

    @pytest.mark.parametrize("role,expected", expect(SYSTEM_WIDE | {"school_admin_user"}))
    def test_edit_and_delete_at_own_school(self, request, targets, role, expected):
        user = request.getfixturevalue(role)
        assignment = targets["staff_a"].assignments.first()
        assert perms.can_edit_staff_assignment(user, assignment) is expected
        assert perms.can_delete_staff_assignment(user, assignment) is expected

    @pytest.mark.parametrize("role,expected", expect(SYSTEM_WIDE))
    def test_edit_and_delete_at_other_school(self, request, targets, role, expected):
        user = request.getfixturevalue(role)
        assignment = targets["staff_b"].assignments.first()
        assert perms.can_edit_staff_assignment(user, assignment) is expected
        assert perms.can_delete_staff_assignment(user, assignment) is expected


class TestFilterStaffForUser:
    @staticmethod
    def annotated_qs():
        latest = SchoolStaffAssignment.objects.filter(school_staff=OuterRef("pk")).order_by("-id")
        return SchoolStaff.objects.annotate(
            latest_school_no=Subquery(latest.values("school__emis_school_no")[:1])
        )

    @pytest.mark.parametrize("role", sorted(SYSTEM_WIDE_READERS))
    def test_system_roles_see_everyone(self, request, targets, role):
        user = request.getfixturevalue(role)
        qs = perms.filter_staff_for_user(self.annotated_qs(), user)
        assert set(qs) >= {targets["staff_a"], targets["staff_b"], targets["staff_none"]}

    @pytest.mark.parametrize("role", sorted(SCHOOL_SCOPED))
    def test_school_roles_see_only_their_school(self, request, targets, role):
        user = request.getfixturevalue(role)
        qs = perms.filter_staff_for_user(self.annotated_qs(), user)
        assert targets["staff_a"] in qs
        assert targets["staff_b"] not in qs
        assert targets["staff_none"] not in qs

    def test_pending_user_sees_nothing(self, pending_user, targets):
        assert not perms.filter_staff_for_user(self.annotated_qs(), pending_user).exists()

    def test_anonymous_sees_nothing(self, targets):
        assert not perms.filter_staff_for_user(self.annotated_qs(), AnonymousUser()).exists()

    def test_school_role_with_expired_assignment_sees_nothing(
        self, make_school_user, school_a, job_title, targets
    ):
        user = make_school_user(perms.GROUP_TEACHERS)
        SchoolStaffAssignmentFactory(
            school_staff=user.school_staff,
            school=school_a,
            job_title=job_title,
            end_date=dt.date(2000, 1, 1),
        )
        assert not perms.filter_staff_for_user(self.annotated_qs(), user).exists()


# ============================================================================
# Student <-> school helpers
# ============================================================================


class TestGetEffectiveStudentSchools:
    def test_no_enrolments_means_no_schools(self):
        assert not perms.get_effective_student_schools(StudentFactory()).exists()

    def test_current_enrolments_win(self, school_a, school_b, class_level):
        student = StudentFactory()
        old = EmisWarehouseYearFactory(code="2024")
        new = EmisWarehouseYearFactory(code="2025")
        StudentSchoolEnrolmentFactory(
            student=student, school=school_a, school_year=old, class_level=class_level,
            end_date=dt.date(2000, 1, 1),
        )
        StudentSchoolEnrolmentFactory(
            student=student, school=school_b, school_year=new, class_level=class_level,
        )
        assert list(perms.get_effective_student_schools(student)) == [school_b]

    def test_all_current_enrolments_are_included(self, school_a, school_b, class_level):
        student = StudentFactory()
        y1 = EmisWarehouseYearFactory(code="2024")
        y2 = EmisWarehouseYearFactory(code="2025")
        StudentSchoolEnrolmentFactory(student=student, school=school_a, school_year=y1, class_level=class_level)
        StudentSchoolEnrolmentFactory(student=student, school=school_b, school_year=y2, class_level=class_level)
        assert set(perms.get_effective_student_schools(student)) == {school_a, school_b}

    def test_falls_back_to_latest_year_when_all_ended(self, school_a, school_b, class_level):
        student = StudentFactory()
        older = EmisWarehouseYearFactory(code="2023")
        newer = EmisWarehouseYearFactory(code="2024")
        ended = dt.date(2000, 1, 1)
        StudentSchoolEnrolmentFactory(
            student=student, school=school_b, school_year=newer, class_level=class_level, end_date=ended
        )
        StudentSchoolEnrolmentFactory(
            student=student, school=school_a, school_year=older, class_level=class_level, end_date=ended
        )
        assert list(perms.get_effective_student_schools(student)) == [school_b]

    def test_fallback_tiebreak_by_start_date_then_pk(self, school_a, school_b, class_level):
        student = StudentFactory()
        year = EmisWarehouseYearFactory(code="2024")
        ended = dt.date(2000, 1, 1)
        StudentSchoolEnrolmentFactory(
            student=student, school=school_a, school_year=year, class_level=class_level,
            start_date=dt.date(1999, 1, 1), end_date=ended,
        )
        StudentSchoolEnrolmentFactory(
            student=student, school=school_b, school_year=year, class_level=class_level,
            start_date=dt.date(1999, 6, 1), end_date=ended,
        )
        assert list(perms.get_effective_student_schools(student)) == [school_b]


# ============================================================================
# Student permissions
# ============================================================================


class TestStudentPermissions:
    @pytest.mark.parametrize(
        "role,expected", expect(SYSTEM_WIDE | {"school_admin_user", "teacher_user"})
    )
    def test_can_create_student(self, request, role, expected):
        assert perms.can_create_student(request.getfixturevalue(role)) is expected

    @pytest.mark.parametrize("role,expected", expect(SYSTEM_WIDE_READERS | SCHOOL_SCOPED))
    def test_can_view_student_at_own_school(self, request, targets, role, expected):
        user = request.getfixturevalue(role)
        assert perms.can_view_student(user, targets["student_a"]) is expected

    @pytest.mark.parametrize("role,expected", expect(SYSTEM_WIDE_READERS))
    def test_can_view_student_at_other_school(self, request, targets, role, expected):
        user = request.getfixturevalue(role)
        assert perms.can_view_student(user, targets["student_b"]) is expected

    @pytest.mark.parametrize("role,expected", expect(SYSTEM_WIDE_READERS))
    def test_can_view_unenrolled_student(self, request, targets, role, expected):
        user = request.getfixturevalue(role)
        assert perms.can_view_student(user, targets["student_none"]) is expected

    @pytest.mark.parametrize(
        "role,expected", expect(SYSTEM_WIDE | {"school_admin_user", "teacher_user"})
    )
    def test_can_edit_student_at_own_school(self, request, targets, role, expected):
        user = request.getfixturevalue(role)
        assert perms.can_edit_student(user, targets["student_a"]) is expected

    @pytest.mark.parametrize("role,expected", expect(SYSTEM_WIDE))
    def test_can_edit_student_at_other_school(self, request, targets, role, expected):
        user = request.getfixturevalue(role)
        assert perms.can_edit_student(user, targets["student_b"]) is expected

    @pytest.mark.parametrize("role,expected", expect(SYSTEM_WIDE))
    def test_can_delete_student(self, request, targets, role, expected):
        user = request.getfixturevalue(role)
        assert perms.can_delete_student(user, targets["student_a"]) is expected

    def test_anonymous_never(self, targets):
        s = targets["student_a"]
        assert perms.can_view_student(AnonymousUser(), s) is False
        assert perms.can_edit_student(AnonymousUser(), s) is False
        assert perms.can_delete_student(AnonymousUser(), s) is False

    def test_access_follows_the_student_s_latest_school_after_transfer(
        self, teacher_user, school_a, school_b, class_level
    ):
        """A student who moved from A to B is no longer visible to A's teacher."""
        student = StudentFactory()
        y1 = EmisWarehouseYearFactory(code="2024")
        y2 = EmisWarehouseYearFactory(code="2025")
        StudentSchoolEnrolmentFactory(
            student=student, school=school_a, school_year=y1, class_level=class_level,
            end_date=dt.date(2024, 12, 31),
        )
        StudentSchoolEnrolmentFactory(
            student=student, school=school_b, school_year=y2, class_level=class_level
        )
        assert perms.can_view_student(teacher_user, student) is False


class TestFilterStudentsForUser:
    @staticmethod
    def annotated_qs():
        latest = StudentSchoolEnrolment.objects.filter(student=OuterRef("pk")).order_by(
            "-school_year__code", "-created_at", "-id"
        )
        return Student.objects.annotate(
            latest_school_no=Subquery(latest.values("school__emis_school_no")[:1])
        )

    @pytest.mark.parametrize("role", sorted(SYSTEM_WIDE_READERS))
    def test_system_roles_see_everyone(self, request, targets, role):
        user = request.getfixturevalue(role)
        qs = perms.filter_students_for_user(self.annotated_qs(), user)
        assert set(qs) >= {targets["student_a"], targets["student_b"], targets["student_none"]}

    @pytest.mark.parametrize("role", sorted(SCHOOL_SCOPED))
    def test_school_roles_see_only_their_school(self, request, targets, role):
        user = request.getfixturevalue(role)
        qs = perms.filter_students_for_user(self.annotated_qs(), user)
        assert targets["student_a"] in qs
        assert targets["student_b"] not in qs
        assert targets["student_none"] not in qs

    def test_pending_and_anonymous_see_nothing(self, pending_user, targets):
        assert not perms.filter_students_for_user(self.annotated_qs(), pending_user).exists()
        assert not perms.filter_students_for_user(self.annotated_qs(), AnonymousUser()).exists()


class TestGetAllowedEnrolmentSchools:
    @pytest.mark.parametrize("role", sorted(SYSTEM_WIDE))
    def test_admins_get_all_active_schools_by_name(self, request, school_a, school_b, role):
        user = request.getfixturevalue(role)
        inactive = EmisSchoolFactory(emis_school_no="KPS999", active=False)
        schools = list(perms.get_allowed_enrolment_schools(user))
        assert schools == [school_a, school_b]
        assert inactive not in schools

    @pytest.mark.parametrize("role", ["school_admin_user", "teacher_user"])
    def test_school_writers_get_their_schools(self, request, school_a, school_b, role):
        user = request.getfixturevalue(role)
        assert list(perms.get_allowed_enrolment_schools(user)) == [school_a]

    @pytest.mark.parametrize("role", ["school_staff_user", "system_staff_user", "pending_user"])
    def test_read_only_roles_get_nothing(self, request, school_a, role):
        user = request.getfixturevalue(role)
        assert not perms.get_allowed_enrolment_schools(user).exists()

    def test_anonymous_gets_nothing(self, school_a):
        assert not perms.get_allowed_enrolment_schools(AnonymousUser()).exists()


# ============================================================================
# SystemUser and pending-user permissions
# ============================================================================


class TestSystemUserPermissions:
    @pytest.mark.parametrize("role,expected", expect(SYSTEM_WIDE_READERS))
    def test_can_view_system_user(self, request, system_staff_user, role, expected):
        user = request.getfixturevalue(role)
        target = system_staff_user.system_user
        assert perms.can_view_system_user(user, target) is expected

    @pytest.mark.parametrize("role,expected", expect(SYSTEM_WIDE))
    def test_can_edit_system_user(self, request, system_staff_user, role, expected):
        user = request.getfixturevalue(role)
        target = system_staff_user.system_user
        assert perms.can_edit_system_user(user, target) is expected
        assert perms.can_edit_system_user_groups(user, target) is expected

    @pytest.mark.parametrize("role,expected", expect(SYSTEM_WIDE))
    def test_can_manage_pending_users(self, request, role, expected):
        assert perms.can_manage_pending_users(request.getfixturevalue(role)) is expected

    @pytest.mark.parametrize("role,expected", expect({"superuser", "admin_user"}))
    def test_can_assign_admins_group(self, request, role, expected):
        """System Admins must not be able to elevate anyone to Admins."""
        assert perms.can_assign_admins_group(request.getfixturevalue(role)) is expected
