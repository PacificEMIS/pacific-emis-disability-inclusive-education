"""
View tests for the dashboard: system-level versus school-level content,
KPI counts scoped to the user's schools, recent activity, and the
enrolment figures read from the warehouse cache.
"""

import datetime as dt

import pytest
from django.urls import reverse

from conftest import (
    EmisWarehouseYearFactory,
    SchoolStaffAssignmentFactory,
    StudentFactory,
    StudentSchoolEnrolmentFactory,
    UserFactory,
)

pytestmark = pytest.mark.django_db
URL = reverse("core:dashboard")


@pytest.fixture
def world(db, school_a, school_b, school_year, class_level, job_title, teacher_user, pending_user):
    """A small world: staff and students at A and B, one pending user."""
    staff_b = SchoolStaffAssignmentFactory(school=school_b, job_title=job_title).school_staff
    s_a = StudentSchoolEnrolmentFactory(
        school=school_a, school_year=school_year, class_level=class_level, cft1_wears_glasses=1
    ).student
    s_b = StudentSchoolEnrolmentFactory(school=school_b, school_year=school_year, class_level=class_level).student
    s_none = StudentFactory()
    return {"staff_b": staff_b, "s_a": s_a, "s_b": s_b, "s_none": s_none}


class TestSystemLevelDashboard:
    @pytest.mark.parametrize("role", ["superuser", "admin_user", "system_admin_user", "system_staff_user"])
    def test_flag_and_global_counts(self, request, client_for, world, role):
        user = request.getfixturevalue(role)
        ctx = client_for(user).get(URL).context
        assert ctx["is_system_level_dashboard"] is True
        assert ctx["total_students"] == 3
        assert ctx["students_added_recent"] == 3
        assert ctx["active_schools"] == 2
        assert ctx["schools_with_disability_data"] == 1
        assert ctx["pending_users_count"] >= 1
        assert ctx["total_staff"] >= 2  # teacher_user + staff_b (+ admin_user if SchoolStaff)
        assert ctx["school_staff_in_teachers"] == 1

    def test_system_user_counts(self, client_for, superuser, system_admin_user, system_staff_user):
        ctx = client_for(superuser).get(URL).context
        assert ctx["total_system_users"] == 2
        assert ctx["system_user_in_system_admins"] == 1
        assert ctx["system_user_in_system_staff"] == 1

    def test_unassigned_staff_counted(self, client_for, superuser, make_school_user):
        make_school_user("Teachers")  # no assignment
        assert client_for(superuser).get(URL).context["staff_unassigned"] == 1

    def test_recent_events_and_student_files(self, client_for, superuser, world):
        ctx = client_for(superuser).get(URL).context
        events = ctx["recent_events"]
        assert 0 < len(events) <= 10
        assert {e["entity"] for e in events} >= {"Student", "Staff", "Student enrolment", "Staff assignment"}
        assert all(e["action"] in ("Created", "Updated") for e in events)
        whens = [e["when"] for e in events]
        assert whens == sorted(whens, reverse=True)

        files = ctx["student_events"]
        assert files and len(files) <= 10
        student_event = next(f for f in files if f["action"] == "Created")
        assert student_event["url"].startswith("/students/")

    def test_event_by_display_prefers_full_name_then_email(self, client_for, superuser, school_a, school_year, class_level):
        named = UserFactory(first_name="Full", last_name="Name")
        email_only = UserFactory(first_name="", last_name="", email="only@example.org")
        StudentSchoolEnrolmentFactory(
            student=StudentFactory(created_by=named, last_updated_by=named),
            school=school_a, school_year=school_year, class_level=class_level, created_by=email_only, last_updated_by=email_only,
        )
        bys = {e["by"] for e in client_for(superuser).get(URL).context["recent_events"]}
        assert {"Full Name", "only@example.org"} <= bys


class TestSchoolLevelDashboard:
    @pytest.mark.parametrize("role", ["school_admin_user", "teacher_user", "school_staff_user"])
    def test_counts_are_scoped_to_own_school(self, request, client_for, world, school_a, role):
        user = request.getfixturevalue(role)
        ctx = client_for(user).get(URL).context
        assert ctx["is_system_level_dashboard"] is False
        assert ctx["total_students"] == 1
        assert ctx["active_schools"] == 1
        assert ctx["schools_with_disability_data"] == 1
        assert ctx["pending_users_count"] == 0
        assert ctx["total_system_users"] == 0
        assert ctx["user_school_info"] == [
            {"emis_school_no": school_a.emis_school_no, "emis_school_name": school_a.emis_school_name}
        ]
        # staff at school A: teacher_user plus the role user themself (unless they are teacher_user)
        expected_staff = 1 if role == "teacher_user" else 2
        assert ctx["total_staff"] == expected_staff

    def test_is_teacher_flag(self, client_for, teacher_user, school_admin_user):
        assert client_for(teacher_user).get(URL).context["is_teacher"] is True
        assert client_for(school_admin_user).get(URL).context["is_teacher"] is False

    def test_recent_activity_excludes_other_schools(self, client_for, teacher_user, world):
        ctx = client_for(teacher_user).get(URL).context
        urls = {e["url"] for e in ctx["recent_events"] if e["url"]}
        assert reverse("core:student_detail", args=[world["s_b"].pk]) not in urls
        assert reverse("core:staff_detail", args=[world["staff_b"].pk]) not in urls
        assert reverse("core:student_detail", args=[world["s_a"].pk]) in urls

    def test_no_enrolment_cache_gives_none(self, client_for, teacher_user, monkeypatch):
        import integrations.odata_client as oc

        monkeypatch.setattr(oc, "load_enrollment_cache", lambda: None)
        ctx = client_for(teacher_user).get(URL).context
        assert ctx["total_enrolment"] is None
        assert ctx["enrolment_by_school"] == []

    def test_enrolment_cache_is_summed_per_school_for_latest_year_with_data(
        self, client_for, teacher_user, school_a, school_b, school_year, monkeypatch
    ):
        import integrations.odata_client as oc

        EmisWarehouseYearFactory(code="2026")  # newest year, but no data for it
        records = [
            {"SurveyYear": 2025, "SchoolNo": school_a.emis_school_no, "GenderCode": "M", "Enrol": 40},
            {"SurveyYear": 2025, "SchoolNo": school_a.emis_school_no, "GenderCode": "F", "Enrol": 35},
            {"SurveyYear": 2025, "SchoolNo": school_b.emis_school_no, "GenderCode": "M", "Enrol": 99},
            {"SurveyYear": 2024, "SchoolNo": school_a.emis_school_no, "GenderCode": "M", "Enrol": 10},
        ]
        monkeypatch.setattr(oc, "load_enrollment_cache", lambda: records)
        ctx = client_for(teacher_user).get(URL).context
        assert ctx["total_enrolment"] == 75
        assert ctx["enrolment_survey_year"] == school_year
        assert ctx["enrolment_by_school"] == [
            {
                "school_code": school_a.emis_school_no,
                "school_name": school_a.emis_school_name,
                "total": 75,
                "survey_year": "2025",
                "survey_year_label": school_year.label,
            }
        ]

    def test_cache_errors_do_not_break_dashboard(self, client_for, teacher_user, monkeypatch):
        import integrations.odata_client as oc

        def boom():
            raise RuntimeError("corrupt cache")

        monkeypatch.setattr(oc, "load_enrollment_cache", boom)
        response = client_for(teacher_user).get(URL)
        assert response.status_code == 200
        assert response.context["total_enrolment"] is None

    def test_system_level_users_never_read_enrolment_cache(self, client_for, superuser, monkeypatch):
        import integrations.odata_client as oc

        def boom():
            raise AssertionError("should not be called")

        monkeypatch.setattr(oc, "load_enrollment_cache", boom)
        assert client_for(superuser).get(URL).status_code == 200

    def test_school_user_without_assignment_sees_zeroes(self, client_for, make_school_user, world):
        user = make_school_user("Teachers")
        ctx = client_for(user).get(URL).context
        assert ctx["total_students"] == 0
        assert ctx["active_schools"] == 0
        assert ctx["total_enrolment"] == 0
