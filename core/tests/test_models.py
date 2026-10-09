"""
Unit tests for core.models: date-based activity rules, derived properties,
string representations and database constraints.
"""

import datetime as dt

import pytest
import time_machine
from django.db import IntegrityError, transaction

from conftest import (
    EmisWarehouseYearFactory,
    SchoolStaffAssignmentFactory,
    SchoolStaffFactory,
    StudentFactory,
    StudentSchoolEnrolmentFactory,
    SystemUserFactory,
    UserFactory,
)
from core.models import SchoolStaff, SchoolStaffAssignment, StudentSchoolEnrolment, active_assignment_q

pytestmark = pytest.mark.django_db

TODAY = dt.date(2026, 6, 15)
FROZEN = dt.datetime(2026, 6, 15, 12, 0, tzinfo=dt.timezone.utc)

DATE_CASES = [
    (None, None, True),
    (TODAY, None, True),
    (TODAY + dt.timedelta(days=1), None, False),
    (None, TODAY, True),
    (None, TODAY - dt.timedelta(days=1), False),
    (None, TODAY + dt.timedelta(days=200), True),
    (TODAY - dt.timedelta(days=10), TODAY + dt.timedelta(days=10), True),
    (TODAY - dt.timedelta(days=400), TODAY - dt.timedelta(days=100), False),
]
DATE_IDS = [
    "open",
    "starts-today",
    "starts-tomorrow",
    "ends-today",
    "ended-yesterday",
    "future-end",
    "covers-today",
    "ended-long-ago",
]


class TestSchoolStaffAssignment:
    @time_machine.travel(FROZEN)
    @pytest.mark.parametrize("start,end,active", DATE_CASES, ids=DATE_IDS)
    def test_is_active_property(self, school_a, job_title, start, end, active):
        a = SchoolStaffAssignmentFactory(
            school=school_a, job_title=job_title, start_date=start, end_date=end
        )
        assert a.is_active is active

    @time_machine.travel(FROZEN)
    @pytest.mark.parametrize("start,end,active", DATE_CASES, ids=DATE_IDS)
    def test_active_assignment_q_matches_property(self, school_a, job_title, start, end, active):
        """The queryset rule and the Python property must never disagree."""
        a = SchoolStaffAssignmentFactory(
            school=school_a, job_title=job_title, start_date=start, end_date=end
        )
        in_qs = SchoolStaffAssignment.objects.filter(active_assignment_q(), pk=a.pk).exists()
        assert in_qs is active
        assert in_qs is a.is_active

    @time_machine.travel(FROZEN)
    def test_active_assignment_q_with_prefix(self, school_a, job_title):
        staff = SchoolStaffFactory()
        SchoolStaffAssignmentFactory(
            school_staff=staff, school=school_a, job_title=job_title,
            end_date=TODAY - dt.timedelta(days=1),
        )
        assert not SchoolStaff.objects.filter(active_assignment_q("assignments__"), pk=staff.pk).exists()
        SchoolStaffAssignmentFactory(school_staff=staff, school=school_a, job_title=job_title)
        assert SchoolStaff.objects.filter(active_assignment_q("assignments__"), pk=staff.pk).exists()

    @time_machine.travel(FROZEN)
    def test_staff_active_assignments_property(self, school_a, school_b, job_title):
        staff = SchoolStaffFactory()
        live = SchoolStaffAssignmentFactory(school_staff=staff, school=school_a, job_title=job_title)
        SchoolStaffAssignmentFactory(
            school_staff=staff, school=school_b, job_title=job_title,
            end_date=TODAY - dt.timedelta(days=1),
        )
        assert list(staff.active_assignments) == [live]

    def test_unique_constraint_on_staff_school_dates(self, school_a, job_title):
        a = SchoolStaffAssignmentFactory(
            school=school_a, job_title=job_title,
            start_date=dt.date(2024, 1, 1), end_date=dt.date(2024, 12, 31),
        )
        with pytest.raises(IntegrityError):
            with transaction.atomic():
                SchoolStaffAssignment.objects.create(
                    school_staff=a.school_staff, school=school_a, job_title=job_title,
                    start_date=dt.date(2024, 1, 1), end_date=dt.date(2024, 12, 31),
                )

    def test_null_dates_do_not_collide_at_database_level(self, school_a, job_title):
        """
        PostgreSQL treats NULLs as distinct in unique constraints, so two
        open-ended assignments at the same school are allowed by the DB.
        The form layer (StudentEnrolmentForm/SchoolStaffAssignmentForm.clean)
        is what prevents this for users. Pin the DB behaviour so a future
        constraint change is deliberate.
        """
        a = SchoolStaffAssignmentFactory(school=school_a, job_title=job_title)
        SchoolStaffAssignment.objects.create(
            school_staff=a.school_staff, school=school_a, job_title=job_title
        )
        assert a.school_staff.assignments.count() == 2

    def test_str(self, school_a, job_title):
        a = SchoolStaffAssignmentFactory(school=school_a, job_title=job_title)
        assert str(a) == f"{a.school_staff.user} @ {school_a}"

    def test_school_is_protected_from_deletion(self, school_a, job_title):
        from django.db.models import ProtectedError

        SchoolStaffAssignmentFactory(school=school_a, job_title=job_title)
        with pytest.raises(ProtectedError):
            school_a.delete()


class TestSchoolStaffAndSystemUser:
    def test_school_staff_str_and_default_type(self):
        staff = SchoolStaffFactory()
        assert str(staff) == f"SchoolStaff<{staff.user}>"
        assert SchoolStaff._meta.get_field("staff_type").default == SchoolStaff.NON_TEACHING_STAFF

    def test_deleting_user_cascades_to_profile(self):
        staff = SchoolStaffFactory()
        staff.user.delete()
        assert not SchoolStaff.objects.filter(pk=staff.pk).exists()

    def test_system_user_str_variants(self):
        user = UserFactory(first_name="Ada", last_name="Lovelace")
        su = SystemUserFactory(user=user, organization="MOE")
        assert str(su) == "Ada Lovelace (MOE)"
        su.organization = ""
        assert str(su) == "Ada Lovelace"
        user.first_name = user.last_name = ""
        assert str(su) == user.username

    def test_one_profile_per_user(self):
        staff = SchoolStaffFactory()
        with pytest.raises(IntegrityError):
            with transaction.atomic():
                SchoolStaff.objects.create(user=staff.user)


class TestStudent:
    def test_str_is_last_comma_first(self):
        s = StudentFactory(first_name="Ana", last_name="Teata")
        assert str(s) == "Teata, Ana"

    @time_machine.travel(FROZEN)
    def test_current_enrolments_and_school_names(self, school_a, school_b, class_level):
        student = StudentFactory()
        y1 = EmisWarehouseYearFactory(code="2024")
        y2 = EmisWarehouseYearFactory(code="2025")
        StudentSchoolEnrolmentFactory(
            student=student, school=school_a, school_year=y1, class_level=class_level,
            end_date=TODAY - dt.timedelta(days=1),
        )
        current = StudentSchoolEnrolmentFactory(
            student=student, school=school_b, school_year=y2, class_level=class_level,
            end_date=TODAY,
        )
        assert list(student.current_enrolments) == [current]
        assert student.current_school_names == school_b.emis_school_name

    def test_current_school_names_empty_without_enrolments(self):
        assert StudentFactory().current_school_names == ""


class TestStudentSchoolEnrolment:
    @time_machine.travel(FROZEN)
    @pytest.mark.parametrize(
        "end,active",
        [(None, True), (TODAY, True), (TODAY - dt.timedelta(days=1), False), (TODAY + dt.timedelta(days=1), True)],
        ids=["open", "ends-today", "ended-yesterday", "ends-tomorrow"],
    )
    def test_is_active(self, school_a, school_year, class_level, end, active):
        e = StudentSchoolEnrolmentFactory(
            school=school_a, school_year=school_year, class_level=class_level, end_date=end
        )
        assert e.is_active is active

    def test_unique_per_student_school_year(self, school_a, school_year, class_level):
        e = StudentSchoolEnrolmentFactory(school=school_a, school_year=school_year, class_level=class_level)
        with pytest.raises(IntegrityError):
            with transaction.atomic():
                StudentSchoolEnrolment.objects.create(
                    student=e.student, school=school_a, school_year=school_year, class_level=class_level
                )

    def test_same_student_can_enrol_in_other_year_or_school(self, school_a, school_b, school_year, class_level):
        e = StudentSchoolEnrolmentFactory(school=school_a, school_year=school_year, class_level=class_level)
        other_year = EmisWarehouseYearFactory(code="2026")
        StudentSchoolEnrolment.objects.create(
            student=e.student, school=school_a, school_year=other_year, class_level=class_level
        )
        StudentSchoolEnrolment.objects.create(
            student=e.student, school=school_b, school_year=school_year, class_level=class_level
        )
        assert e.student.enrolments.count() == 3

    def test_deleting_student_cascades_to_enrolments(self, school_a, school_year, class_level):
        e = StudentSchoolEnrolmentFactory(school=school_a, school_year=school_year, class_level=class_level)
        e.student.delete()
        assert not StudentSchoolEnrolment.objects.filter(pk=e.pk).exists()

    def test_lookups_are_protected(self, school_a, school_year, class_level):
        from django.db.models import ProtectedError

        StudentSchoolEnrolmentFactory(school=school_a, school_year=school_year, class_level=class_level)
        for obj in (school_a, school_year, class_level):
            with pytest.raises(ProtectedError):
                obj.delete()

    def test_all_twenty_cft_fields_exist_with_choices(self):
        names = [f.name for f in StudentSchoolEnrolment._meta.fields if f.name.startswith("cft")]
        assert len(names) == 20
        assert [int(n[3:].split("_")[0]) for n in names] == list(range(1, 21))
        for f in StudentSchoolEnrolment._meta.fields:
            if f.name.startswith("cft"):
                assert f.choices and f.null and f.blank, f.name

    def test_str(self, school_a, school_year, class_level):
        e = StudentSchoolEnrolmentFactory(school=school_a, school_year=school_year, class_level=class_level)
        assert str(e) == f"{e.student} @ {school_a} — {school_year}"
