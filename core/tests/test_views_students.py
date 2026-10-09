"""
View tests for Students: list filtering per role, detail, profile edit,
the combined intake form (student_new) including its transaction and
email hook, the fuzzy match endpoint, and enrolment add/edit/delete.
"""

import datetime as dt

import pytest
from django.contrib.messages import get_messages
from django.core import mail
from django.db import IntegrityError
from django.urls import reverse

from conftest import (
    EmisClassLevelFactory,
    EmisWarehouseYearFactory,
    StudentFactory,
    StudentSchoolEnrolmentFactory,
)
from core.models import Student, StudentSchoolEnrolment

pytestmark = pytest.mark.django_db


def messages_of(response):
    return [str(m) for m in get_messages(response.wsgi_request)]


@pytest.fixture
def students(db, school_a, school_b, school_year, class_level):
    a = StudentSchoolEnrolmentFactory(
        student=StudentFactory(first_name="Ana", last_name="Teata", date_of_birth=dt.date(2015, 1, 1)),
        school=school_a, school_year=school_year, class_level=class_level,
    ).student
    b = StudentSchoolEnrolmentFactory(
        student=StudentFactory(first_name="Bati", last_name="Mwemwe", date_of_birth=dt.date(2014, 1, 1)),
        school=school_b, school_year=school_year, class_level=class_level,
    ).student
    none = StudentFactory(first_name="Zoe", last_name="Zero", date_of_birth=dt.date(2013, 1, 1))
    return {"a": a, "b": b, "none": none}


# ============================================================================
# student_list
# ============================================================================


class TestStudentList:
    url = reverse("core:student_list")

    def _pks(self, response):
        return {s.pk for s in response.context["page_obj"].object_list}

    @pytest.mark.parametrize("role", ["superuser", "admin_user", "system_admin_user", "system_staff_user"])
    def test_system_roles_see_all(self, request, client_for, students, role):
        response = client_for(request.getfixturevalue(role)).get(self.url)
        assert response.status_code == 200
        assert self._pks(response) == {students["a"].pk, students["b"].pk, students["none"].pk}

    @pytest.mark.parametrize("role", ["school_admin_user", "teacher_user", "school_staff_user"])
    def test_school_roles_see_only_own_school(self, request, client_for, students, role):
        response = client_for(request.getfixturevalue(role)).get(self.url)
        assert self._pks(response) == {students["a"].pk}

    def test_search_by_name(self, client_for, superuser, students):
        client = client_for(superuser)
        assert self._pks(client.get(self.url, {"q": "teat"})) == {students["a"].pk}
        assert self._pks(client.get(self.url, {"q": "bat"})) == {students["b"].pk}

    def test_filters_use_latest_enrolment(self, client_for, superuser, students, school_a, school_b, class_level):
        """A student who moved to B is filtered under B, not A."""
        newer = EmisWarehouseYearFactory(code="2026")
        StudentSchoolEnrolmentFactory(student=students["a"], school=school_b, school_year=newer, class_level=class_level)
        client = client_for(superuser)
        assert self._pks(client.get(self.url, {"school": school_a.emis_school_no})) == set()
        assert self._pks(client.get(self.url, {"school": school_b.emis_school_no})) == {students["a"].pk, students["b"].pk}
        assert self._pks(client.get(self.url, {"year": "2026"})) == {students["a"].pk}
        assert self._pks(client.get(self.url, {"level": class_level.code})) == {students["a"].pk, students["b"].pk}

    def test_school_role_loses_transferred_student(self, client_for, teacher_user, students, school_b, class_level):
        newer = EmisWarehouseYearFactory(code="2026")
        StudentSchoolEnrolmentFactory(student=students["a"], school=school_b, school_year=newer, class_level=class_level)
        assert self._pks(client_for(teacher_user).get(self.url)) == set()

    @pytest.mark.parametrize("sort", ["name", "dob", "school", "school_year", "class_level"])
    def test_sorting_does_not_error(self, client_for, superuser, students, sort):
        for direction in ("asc", "desc"):
            response = client_for(superuser).get(self.url, {"sort": sort, "dir": direction})
            assert response.status_code == 200

    def test_sort_by_dob_desc(self, client_for, superuser, students):
        response = client_for(superuser).get(self.url, {"sort": "dob", "dir": "desc"})
        dobs = [s.date_of_birth for s in response.context["page_obj"].object_list]
        assert dobs == sorted(dobs, reverse=True)

    def test_enrol_map_carries_latest_enrolment(self, client_for, superuser, students, school_a, school_year, class_level):
        response = client_for(superuser).get(self.url)
        entry = response.context["enrol_map"][students["a"].pk]
        assert entry["school_no"] == school_a.emis_school_no
        assert entry["school_year"] == school_year.code
        assert entry["class_level_code"] == class_level.code
        assert response.context["enrol_map"][students["none"].pk]["school_no"] is None

    def test_pagination_and_per_page(self, client_for, superuser):
        for i in range(30):
            StudentFactory(last_name=f"Pupil{i:02d}")
        response = client_for(superuser).get(self.url, {"per_page": 10, "page": 3})
        assert response.context["page_obj"].number == 3
        assert response.context["per_page"] == 10
        assert client_for(superuser).get(self.url, {"per_page": "x"}).context["per_page"] == 25


# ============================================================================
# student_detail / student_edit
# ============================================================================


class TestStudentDetail:
    def url(self, s):
        return reverse("core:student_detail", kwargs={"pk": s.pk})

    def test_teacher_sees_own_school_student(self, client_for, teacher_user, students):
        response = client_for(teacher_user).get(self.url(students["a"]))
        assert response.status_code == 200
        assert response.context["latest_enrolment"] == students["a"].enrolments.first()

    def test_teacher_forbidden_for_other_school(self, client_for, teacher_user, students):
        assert client_for(teacher_user).get(self.url(students["b"])).status_code == 403

    def test_unenrolled_student_has_no_latest_enrolment(self, client_for, superuser, students):
        response = client_for(superuser).get(self.url(students["none"]))
        assert response.status_code == 200
        assert response.context["latest_enrolment"] is None

    def test_enrolments_ordered_newest_year_first(self, client_for, superuser, students, school_a, class_level):
        older = EmisWarehouseYearFactory(code="2020")
        StudentSchoolEnrolmentFactory(student=students["a"], school=school_a, school_year=older, class_level=class_level)
        response = client_for(superuser).get(self.url(students["a"]))
        codes = [e.school_year.code for e in response.context["enrolments"]]
        assert codes == ["2025", "2020"]

    def test_404(self, client_for, superuser):
        assert client_for(superuser).get(reverse("core:student_detail", kwargs={"pk": 99999})).status_code == 404


class TestStudentEdit:
    def url(self, s):
        return reverse("core:student_edit", kwargs={"pk": s.pk})

    def test_school_staff_forbidden(self, client_for, school_staff_user, students):
        assert client_for(school_staff_user).get(self.url(students["a"])).status_code == 403

    def test_teacher_edits_own_school_student(self, client_for, teacher_user, students):
        s = students["a"]
        response = client_for(teacher_user).post(
            self.url(s), {"first_name": "Anna", "last_name": "Teata", "date_of_birth": "2015-02-02", "gender": "2"}
        )
        assert response.status_code == 302
        s.refresh_from_db()
        assert s.first_name == "Anna" and s.date_of_birth == dt.date(2015, 2, 2) and s.gender == 2
        assert s.last_updated_by == teacher_user

    def test_teacher_forbidden_other_school(self, client_for, teacher_user, students):
        assert client_for(teacher_user).post(self.url(students["b"]), {}).status_code == 403

    def test_invalid_post_rerenders(self, client_for, superuser, students):
        response = client_for(superuser).post(self.url(students["a"]), {"first_name": "", "last_name": "x", "date_of_birth": ""})
        assert response.status_code == 200
        assert response.context["form"].errors


# ============================================================================
# student_new
# ============================================================================


class TestStudentNew:
    url = reverse("core:student_new")

    def _data(self, school, year, level, **extra):
        data = {
            "first_name": " Tebwe ",
            "last_name": " Kaitara ",
            "date_of_birth": "2016-05-06",
            "gender": "1",
            "school": school.pk,
            "school_year": year.pk,
            "class_level": level.pk,
            "cft1_wears_glasses": "1",
            "cft3_difficulty_seeing": "3",
            "cft20_depressed_frequency": "5",
        }
        data.update(extra)
        return data

    @pytest.mark.parametrize("role", ["school_staff_user", "system_staff_user"])
    def test_read_only_roles_forbidden(self, request, client_for, role):
        client = client_for(request.getfixturevalue(role))
        assert client.get(self.url).status_code == 403
        assert client.post(self.url, {}).status_code == 403

    def test_get_limits_schools_to_allowed(self, client_for, teacher_user, school_a, school_b):
        response = client_for(teacher_user).get(self.url)
        assert list(response.context["form"].fields["school"].queryset) == [school_a]
        assert response.context["cft_meta"][0][2]  # question text present

    def test_creates_student_enrolment_and_emails_on_commit(
        self, client_for, teacher_user, admin_user, school_a, school_year, class_level,
        django_capture_on_commit_callbacks, sync_email_threads,
    ):
        with django_capture_on_commit_callbacks(execute=True):
            response = client_for(teacher_user).post(self.url, self._data(school_a, school_year, class_level))
        assert response.status_code == 302
        student = Student.objects.get(last_name="Kaitara")
        assert response["Location"] == reverse("core:student_detail", kwargs={"pk": student.pk})
        assert student.first_name == "Tebwe"  # stripped
        assert student.gender == 1
        assert student.created_by == teacher_user and student.last_updated_by == teacher_user

        enrolment = student.enrolments.get()
        assert enrolment.school == school_a and enrolment.school_year == school_year
        assert enrolment.cft1_wears_glasses == 1
        assert enrolment.cft3_difficulty_seeing == 3
        assert enrolment.cft20_depressed_frequency == 5
        assert enrolment.cft2_difficulty_seeing_with_glasses is None
        assert enrolment.created_by == teacher_user

        assert len(mail.outbox) == 1
        msg = mail.outbox[0]
        assert set(msg.to) == {teacher_user.email, admin_user.email}
        assert "Tebwe Kaitara" in msg.subject
        assert "Tebwe Kaitara" in msg.body
        html_body, mimetype = msg.alternatives[0]
        assert mimetype == "text/html"
        assert reverse("core:student_detail", kwargs={"pk": student.pk}) in html_body

    def test_teacher_cannot_enrol_at_other_school(self, client_for, teacher_user, school_b, school_year, class_level):
        response = client_for(teacher_user).post(self.url, self._data(school_b, school_year, class_level))
        assert response.status_code == 200
        assert "school" in response.context["form"].errors
        assert Student.objects.count() == 0

    def test_invalid_cft_value_rejected(self, client_for, superuser, school_a, school_year, class_level):
        response = client_for(superuser).post(
            self.url, self._data(school_a, school_year, class_level, cft1_wears_glasses="9")
        )
        assert response.status_code == 200
        assert Student.objects.count() == 0

    def test_invalid_post_keeps_typed_name_in_questions(self, client_for, superuser, school_a, school_year, class_level):
        response = client_for(superuser).post(
            self.url, self._data(school_a, school_year, class_level, date_of_birth="")
        )
        assert response.status_code == 200
        assert "Tebwe Kaitara" in str(response.context["cft_meta"][0][2])

    def test_enrolment_failure_rolls_back_student(
        self, client_for, superuser, school_a, school_year, class_level, monkeypatch
    ):
        """If the enrolment insert fails, no orphan Student row may remain."""

        def boom(*args, **kwargs):
            raise IntegrityError("simulated")

        monkeypatch.setattr(StudentSchoolEnrolment.objects, "create", boom)
        response = client_for(superuser).post(self.url, self._data(school_a, school_year, class_level))
        assert response.status_code == 400
        assert Student.objects.count() == 0
        assert any("already exists" in m for m in messages_of(response))

    def test_no_email_when_transaction_not_committed(
        self, client_for, superuser, school_a, school_year, class_level, django_capture_on_commit_callbacks, sync_email_threads
    ):
        with django_capture_on_commit_callbacks(execute=False) as callbacks:
            client_for(superuser).post(self.url, self._data(school_a, school_year, class_level))
        assert len(callbacks) == 1
        assert mail.outbox == []


# ============================================================================
# student_matches
# ============================================================================


class TestStudentMatches:
    url = reverse("core:student_matches")

    def _ids(self, response):
        return [r["id"] for r in response.json()["results"]]

    def test_exact_match(self, client_for, superuser, students):
        response = client_for(superuser).get(self.url, {"first_name": "Ana", "last_name": "Teata"})
        assert response.status_code == 200
        assert self._ids(response) == [students["a"].pk]
        result = response.json()["results"][0]
        assert result["date_of_birth"] == "2015-01-01"
        assert result["similarity"] == 1.0
        assert result["current_schools"] == students["a"].enrolments.first().school.emis_school_name

    def test_partial_first_name_matches(self, client_for, superuser, students):
        response = client_for(superuser).get(self.url, {"first_name": "An", "last_name": "Teat"})
        assert self._ids(response) == [students["a"].pk]

    def test_dob_is_a_hard_filter(self, client_for, superuser, students):
        response = client_for(superuser).get(
            self.url, {"first_name": "Ana", "last_name": "Teata", "date_of_birth": "1999-01-01"}
        )
        assert self._ids(response) == []

    def test_no_query_returns_nothing(self, client_for, superuser, students):
        assert self._ids(client_for(superuser).get(self.url)) == []

    def test_weak_matches_are_dropped(self, client_for, superuser, students):
        response = client_for(superuser).get(self.url, {"first_name": "Zzz", "last_name": "Qqq"})
        assert self._ids(response) == []

    def test_results_capped_at_ten(self, client_for, superuser):
        for i in range(15):
            StudentFactory(first_name="Ana", last_name="Teata")
        response = client_for(superuser).get(self.url, {"first_name": "Ana", "last_name": "Teata"})
        assert len(self._ids(response)) == 10

    def test_school_role_cannot_match_students_at_other_schools(self, client_for, teacher_user, students):
        response = client_for(teacher_user).get(self.url, {"first_name": "Bati", "last_name": "Mwemwe"})
        assert self._ids(response) == []

    def test_school_role_matches_students_at_own_school(self, client_for, teacher_user, students):
        response = client_for(teacher_user).get(self.url, {"first_name": "Ana", "last_name": "Teata"})
        assert self._ids(response) == [students["a"].pk]

    def test_pending_user_gets_no_matches(self, client_for, pending_user, students):
        response = client_for(pending_user).get(self.url, {"first_name": "Ana", "last_name": "Teata"})
        assert response.status_code in (302, 403)


# ============================================================================
# Enrolment add / edit / delete
# ============================================================================


class TestEnrolmentAdd:
    def url(self, s):
        return reverse("core:student_enrolment_add", kwargs={"student_pk": s.pk})

    def _data(self, school, year, level, **extra):
        data = {"school": school.pk, "school_year": year.pk, "class_level": level.pk, "start_date": "", "end_date": ""}
        data.update(extra)
        return data

    def test_school_staff_forbidden(self, client_for, school_staff_user, students):
        assert client_for(school_staff_user).get(self.url(students["a"])).status_code == 403

    def test_get_shows_create_form_with_student_name(self, client_for, teacher_user, students, school_a):
        response = client_for(teacher_user).get(self.url(students["a"]))
        assert response.status_code == 200
        assert response.context["is_create"] is True
        assert "Ana Teata" in str(response.context["cft_meta"][0][2])
        assert list(response.context["form"].fields["school"].queryset) == [school_a]

    def test_adds_enrolment_for_new_year(self, client_for, teacher_user, students, school_a, class_level):
        year = EmisWarehouseYearFactory(code="2026")
        response = client_for(teacher_user).post(
            self.url(students["a"]), self._data(school_a, year, class_level, cft6_difficulty_hearing="2")
        )
        assert response.status_code == 302
        e = students["a"].enrolments.get(school_year=year)
        assert e.cft6_difficulty_hearing == 2
        assert e.created_by == teacher_user and e.last_updated_by == teacher_user

    def test_duplicate_year_rejected(self, client_for, teacher_user, students, school_a, school_year, class_level):
        response = client_for(teacher_user).post(self.url(students["a"]), self._data(school_a, school_year, class_level))
        assert response.status_code == 200
        assert "school" in response.context["form"].errors
        assert students["a"].enrolments.count() == 1

    def test_teacher_cannot_add_at_other_school(self, client_for, teacher_user, students, school_b, class_level):
        year = EmisWarehouseYearFactory(code="2026")
        response = client_for(teacher_user).post(self.url(students["a"]), self._data(school_b, year, class_level))
        assert response.status_code == 200
        assert students["a"].enrolments.count() == 1


class TestEnrolmentEdit:
    def url(self, e):
        return reverse("core:student_enrolment_edit", kwargs={"student_pk": e.student_id, "enrolment_pk": e.pk})

    def test_mismatch_404(self, client_for, superuser, students):
        e = students["a"].enrolments.first()
        url = reverse("core:student_enrolment_edit", kwargs={"student_pk": students["b"].pk, "enrolment_pk": e.pk})
        assert client_for(superuser).get(url).status_code == 404

    def test_teacher_edits_cft_values(self, client_for, teacher_user, students, school_a, school_year, class_level):
        e = students["a"].enrolments.first()
        response = client_for(teacher_user).post(
            self.url(e),
            {
                "school": school_a.pk, "school_year": school_year.pk, "class_level": class_level.pk,
                "start_date": "2025-02-01", "end_date": "", "cft13_difficulty_learning": "4",
            },
        )
        assert response.status_code == 302
        e.refresh_from_db()
        assert e.cft13_difficulty_learning == 4
        assert e.start_date == dt.date(2025, 2, 1)
        assert e.last_updated_by == teacher_user

    def test_school_staff_forbidden(self, client_for, school_staff_user, students):
        assert client_for(school_staff_user).get(self.url(students["a"].enrolments.first())).status_code == 403

    def test_get_is_edit_mode(self, client_for, superuser, students):
        response = client_for(superuser).get(self.url(students["a"].enrolments.first()))
        assert response.context["is_create"] is False
        assert response.context["enrolment"] is not None


class TestEnrolmentDelete:
    def url(self, e):
        return reverse("core:student_enrolment_delete", kwargs={"student_pk": e.student_id, "enrolment_pk": e.pk})

    @pytest.mark.parametrize("role", ["school_admin_user", "teacher_user", "school_staff_user", "system_staff_user"])
    def test_non_admins_forbidden(self, request, client_for, students, role):
        e = students["a"].enrolments.first()
        assert client_for(request.getfixturevalue(role)).post(self.url(e)).status_code == 403
        assert StudentSchoolEnrolment.objects.filter(pk=e.pk).exists()

    @pytest.mark.parametrize("role", ["superuser", "admin_user", "system_admin_user"])
    def test_admins_confirm_and_delete(self, request, client_for, students, role):
        e = students["a"].enrolments.first()
        client = client_for(request.getfixturevalue(role))
        assert client.get(self.url(e)).status_code == 200
        response = client.post(self.url(e))
        assert response.status_code == 302
        assert not StudentSchoolEnrolment.objects.filter(pk=e.pk).exists()
        assert Student.objects.filter(pk=students["a"].pk).exists()  # student kept
