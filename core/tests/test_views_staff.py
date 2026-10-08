"""
View tests for the School Staff pages: list filtering per role, detail with
assignment creation, assignment edit/delete, and staff profile/group edit.
"""

import datetime as dt

import pytest
from django.contrib.auth.models import Group
from django.contrib.messages import get_messages
from django.urls import reverse

from conftest import SchoolStaffAssignmentFactory, SchoolStaffFactory, UserFactory
from core.models import SchoolStaffAssignment

pytestmark = pytest.mark.django_db


def messages_of(response):
    return [str(m) for m in get_messages(response.wsgi_request)]


@pytest.fixture
def staff_set(db, school_a, school_b, job_title):
    """Three staff: at A, at B, unassigned, with distinctive names."""
    a = SchoolStaffAssignmentFactory(
        school_staff=SchoolStaffFactory(user=UserFactory(first_name="Alice", last_name="Anders", email="alice@a.org")),
        school=school_a, job_title=job_title,
    ).school_staff
    b = SchoolStaffAssignmentFactory(
        school_staff=SchoolStaffFactory(user=UserFactory(first_name="Bob", last_name="Barnes", email="bob@b.org")),
        school=school_b, job_title=job_title,
    ).school_staff
    none = SchoolStaffFactory(user=UserFactory(first_name="Zed", last_name="Zero", email="zed@z.org"))
    return {"a": a, "b": b, "none": none}


# ============================================================================
# staff_list
# ============================================================================


class TestStaffList:
    url = reverse("core:staff_list")

    def _pks(self, response):
        return {s.pk for s in response.context["page_obj"].object_list}

    @pytest.mark.parametrize("role", ["superuser", "admin_user", "system_admin_user", "system_staff_user"])
    def test_system_roles_see_all(self, request, client_for, staff_set, role):
        response = client_for(request.getfixturevalue(role)).get(self.url)
        assert response.status_code == 200
        assert self._pks(response) >= {staff_set["a"].pk, staff_set["b"].pk, staff_set["none"].pk}

    @pytest.mark.parametrize("role", ["school_admin_user", "teacher_user", "school_staff_user"])
    def test_school_roles_see_only_own_school(self, request, client_for, staff_set, role):
        user = request.getfixturevalue(role)
        response = client_for(user).get(self.url)
        pks = self._pks(response)
        assert staff_set["a"].pk in pks
        assert user.school_staff.pk in pks  # they see themselves
        assert staff_set["b"].pk not in pks
        assert staff_set["none"].pk not in pks

    def test_search_by_name(self, client_for, superuser, staff_set):
        response = client_for(superuser).get(self.url, {"q": "barn"})
        assert self._pks(response) == {staff_set["b"].pk}

    def test_filter_by_email(self, client_for, superuser, staff_set):
        response = client_for(superuser).get(self.url, {"email": "zed@"})
        assert self._pks(response) == {staff_set["none"].pk}

    def test_filter_by_school(self, client_for, superuser, staff_set, school_a):
        response = client_for(superuser).get(self.url, {"school": school_a.emis_school_no})
        assert self._pks(response) == {staff_set["a"].pk}

    def test_sort_by_name_desc(self, client_for, superuser, staff_set):
        response = client_for(superuser).get(self.url, {"sort": "name", "dir": "desc"})
        names = [s.user.last_name for s in response.context["page_obj"].object_list]
        assert names == sorted(names, reverse=True)
        assert response.context["dir"] == "desc"

    def test_direction_is_sanitised(self, client_for, superuser, staff_set):
        response = client_for(superuser).get(self.url, {"sort": "name", "dir": "sideways"})
        assert response.context["dir"] == "asc"

    @pytest.mark.parametrize("raw,expected", [("10", 10), ("7", 25), ("abc", 25), ("100", 100)])
    def test_per_page_is_sanitised(self, client_for, superuser, staff_set, raw, expected):
        response = client_for(superuser).get(self.url, {"per_page": raw})
        assert response.context["per_page"] == expected

    def test_pagination(self, client_for, superuser, school_a, job_title):
        for _ in range(12):
            SchoolStaffAssignmentFactory(school=school_a, job_title=job_title)
        response = client_for(superuser).get(self.url, {"per_page": 10, "page": 2})
        page = response.context["page_obj"]
        assert page.number == 2
        assert page.paginator.count == 12
        assert len(page.object_list) == 2

    def test_out_of_range_page_falls_back_to_last(self, client_for, superuser, staff_set):
        response = client_for(superuser).get(self.url, {"page": 999})
        assert response.context["page_obj"].number == 1


# ============================================================================
# staff_detail (view + add assignment)
# ============================================================================


class TestStaffDetail:
    def url(self, staff):
        return reverse("core:staff_detail", kwargs={"pk": staff.pk})

    def test_school_role_cannot_view_other_school(self, client_for, teacher_user, staff_set):
        response = client_for(teacher_user).get(self.url(staff_set["b"]))
        assert response.status_code == 302
        assert response["Location"] == reverse("core:staff_list")
        assert any("permission" in m for m in messages_of(response))

    def test_school_role_can_view_same_school(self, client_for, teacher_user, staff_set):
        response = client_for(teacher_user).get(self.url(staff_set["a"]))
        assert response.status_code == 200
        assert response.context["can_add_assignment"] is False
        assert response.context["assignment_form"] is None
        assert response.context["can_edit"] is False

    def test_admin_sees_form_and_permissions(self, client_for, admin_user, staff_set):
        response = client_for(admin_user).get(self.url(staff_set["a"]))
        ctx = response.context
        assert ctx["can_add_assignment"] is True
        assert ctx["assignment_form"] is not None
        assert ctx["can_edit"] is True
        assignment = staff_set["a"].assignments.first()
        assert ctx["assignment_permissions"][assignment.pk] == {"can_edit": True, "can_delete": True}

    def test_group_permissions_are_summarised(self, client_for, superuser, teacher_user):
        response = client_for(superuser).get(self.url(teacher_user.school_staff))
        groups = [g["group"].name for g in response.context["group_permissions"]]
        assert groups == ["Teachers"]
        keys = [s["key"] for s in response.context["group_permissions"][0]["sections"]]
        assert "access" in keys

    def test_unknown_staff_404(self, client_for, superuser):
        assert client_for(superuser).get(reverse("core:staff_detail", kwargs={"pk": 999999})).status_code == 404

    def test_admin_adds_assignment(self, client_for, admin_user, staff_set, school_b, job_title):
        staff = staff_set["none"]
        response = client_for(admin_user).post(
            self.url(staff),
            {"school": school_b.pk, "job_title": job_title.pk, "start_date": "2026-01-01", "end_date": ""},
        )
        assert response.status_code == 302
        a = staff.assignments.get()
        assert a.school == school_b and a.start_date == dt.date(2026, 1, 1)
        assert a.created_by == admin_user and a.last_updated_by == admin_user

    def test_duplicate_assignment_is_rejected_with_form_error(self, client_for, admin_user, staff_set, school_a, job_title):
        staff = staff_set["a"]
        response = client_for(admin_user).post(
            self.url(staff), {"school": school_a.pk, "job_title": job_title.pk, "start_date": "", "end_date": ""}
        )
        assert response.status_code == 200
        assert "school" in response.context["assignment_form"].errors
        assert staff.assignments.count() == 1

    def test_school_admin_cannot_add_assignment_for_other_school(
        self, client_for, school_admin_user, staff_set, school_b, job_title
    ):
        staff = staff_set["a"]
        response = client_for(school_admin_user).post(
            self.url(staff), {"school": school_b.pk, "job_title": job_title.pk, "start_date": "", "end_date": ""}
        )
        assert response.status_code == 200
        assert staff.assignments.filter(school=school_b).count() == 0

    def test_school_admin_adds_assignment_at_own_school(
        self, client_for, school_admin_user, staff_set, school_a, job_title
    ):
        staff = staff_set["a"]
        response = client_for(school_admin_user).post(
            self.url(staff),
            {"school": school_a.pk, "job_title": job_title.pk, "start_date": "2026-02-01", "end_date": ""},
        )
        assert response.status_code == 302
        assert staff.assignments.count() == 2

    def test_teacher_post_is_refused(self, client_for, teacher_user, staff_set, school_a, job_title):
        staff = staff_set["a"]
        response = client_for(teacher_user).post(
            self.url(staff), {"school": school_a.pk, "job_title": job_title.pk, "start_date": "2026-02-01", "end_date": ""}
        )
        assert response.status_code == 200
        assert staff.assignments.count() == 1
        assert any("permission" in m for m in messages_of(response))


# ============================================================================
# staff_assignment_edit / delete
# ============================================================================


class TestStaffAssignmentEditDelete:
    def edit_url(self, assignment):
        return reverse("core:staff_assignment_edit", kwargs={"staff_id": assignment.school_staff_id, "pk": assignment.pk})

    def delete_url(self, assignment):
        return reverse("core:staff_assignment_delete", kwargs={"staff_id": assignment.school_staff_id, "pk": assignment.pk})

    def test_mismatched_staff_and_assignment_404(self, client_for, superuser, staff_set):
        a = staff_set["a"].assignments.first()
        url = reverse("core:staff_assignment_edit", kwargs={"staff_id": staff_set["b"].pk, "pk": a.pk})
        assert client_for(superuser).get(url).status_code == 404

    def test_admin_edits_dates(self, client_for, admin_user, staff_set, school_a, job_title):
        a = staff_set["a"].assignments.first()
        response = client_for(admin_user).post(
            self.edit_url(a),
            {"school": school_a.pk, "job_title": job_title.pk, "start_date": "2025-01-01", "end_date": "2025-12-31"},
        )
        assert response.status_code == 302
        a.refresh_from_db()
        assert a.start_date == dt.date(2025, 1, 1) and a.end_date == dt.date(2025, 12, 31)
        assert a.last_updated_by == admin_user

    def test_school_admin_cannot_edit_other_school(self, client_for, school_admin_user, staff_set):
        a = staff_set["b"].assignments.first()
        response = client_for(school_admin_user).get(self.edit_url(a))
        assert response.status_code == 302
        assert response["Location"] == reverse("core:staff_detail", kwargs={"pk": staff_set["b"].pk})

    def test_school_admin_cannot_move_assignment_to_other_school(
        self, client_for, school_admin_user, staff_set, school_b, job_title
    ):
        a = staff_set["a"].assignments.first()
        response = client_for(school_admin_user).post(
            self.edit_url(a), {"school": school_b.pk, "job_title": job_title.pk, "start_date": "", "end_date": ""}
        )
        assert response.status_code == 200
        a.refresh_from_db()
        assert a.school_id != school_b.pk

    def test_teacher_cannot_delete(self, client_for, teacher_user, staff_set):
        a = staff_set["a"].assignments.first()
        response = client_for(teacher_user).post(self.delete_url(a))
        assert response.status_code == 302
        assert SchoolStaffAssignment.objects.filter(pk=a.pk).exists()

    def test_admin_delete_confirm_then_delete(self, client_for, admin_user, staff_set):
        a = staff_set["a"].assignments.first()
        client = client_for(admin_user)
        assert client.get(self.delete_url(a)).status_code == 200
        response = client.post(self.delete_url(a))
        assert response.status_code == 302
        assert not SchoolStaffAssignment.objects.filter(pk=a.pk).exists()

    def test_school_admin_deletes_at_own_school(self, client_for, school_admin_user, staff_set):
        a = staff_set["a"].assignments.first()
        client_for(school_admin_user).post(self.delete_url(a))
        assert not SchoolStaffAssignment.objects.filter(pk=a.pk).exists()


# ============================================================================
# staff_edit
# ============================================================================


class TestStaffEdit:
    def url(self, staff):
        return reverse("core:staff_edit", kwargs={"pk": staff.pk})

    def _post(self, client, staff, groups, staff_type="teaching"):
        ids = [Group.objects.get(name=g).pk for g in groups]
        return client.post(self.url(staff), {"staff_type": staff_type, "groups": ids})

    def test_teacher_cannot_edit(self, client_for, teacher_user, staff_set):
        response = client_for(teacher_user).get(self.url(staff_set["a"]))
        assert response.status_code == 302
        assert response["Location"] == reverse("core:staff_detail", kwargs={"pk": staff_set["a"].pk})

    def test_admin_changes_type_and_groups(self, client_for, admin_user, teacher_user):
        staff = teacher_user.school_staff
        response = self._post(client_for(admin_user), staff, ["School Admins", "School Staff"], "non_teaching")
        assert response.status_code == 302
        staff.refresh_from_db()
        assert staff.staff_type == "non_teaching"
        assert staff.last_updated_by == admin_user
        assert set(teacher_user.groups.values_list("name", flat=True)) == {"School Admins", "School Staff"}

    def test_admin_can_grant_admins(self, client_for, admin_user, teacher_user):
        self._post(client_for(admin_user), teacher_user.school_staff, ["Admins"])
        assert teacher_user.groups.filter(name="Admins").exists()

    def test_system_admin_cannot_grant_admins(self, client_for, system_admin_user, teacher_user):
        response = self._post(client_for(system_admin_user), teacher_user.school_staff, ["Admins"])
        assert response.status_code == 200
        assert "groups" in response.context["form"].errors
        assert not teacher_user.groups.filter(name="Admins").exists()

    def test_school_admin_edits_staff_at_own_school(self, client_for, school_admin_user, staff_set):
        staff = staff_set["a"]
        response = self._post(client_for(school_admin_user), staff, ["Teachers"])
        assert response.status_code == 302
        assert set(staff.user.groups.values_list("name", flat=True)) == {"Teachers"}

    def test_school_admin_cannot_edit_staff_at_other_school(self, client_for, school_admin_user, staff_set):
        response = self._post(client_for(school_admin_user), staff_set["b"], ["Teachers"])
        assert response.status_code == 302
        assert staff_set["b"].user.groups.count() == 0

    def test_non_school_groups_are_preserved(self, client_for, admin_user, teacher_user):
        """Editing school-level groups must not strip unrelated groups."""
        other = Group.objects.create(name="Reporting")
        teacher_user.groups.add(other)
        self._post(client_for(admin_user), teacher_user.school_staff, ["School Staff"])
        assert set(teacher_user.groups.values_list("name", flat=True)) == {"School Staff", "Reporting"}

    @pytest.mark.xfail(
        strict=True,
        reason="Known gap: an editor who cannot assign Admins still strips an existing Admins "
        "membership, because the view removes all school-level groups before re-adding the "
        "submitted ones. Track as its own issue; the test documents the intended behaviour.",
    )
    def test_limited_editor_does_not_strip_existing_admins_membership(
        self, client_for, school_admin_user, school_a, job_title, make_school_user
    ):
        target = make_school_user("Admins", schools=[school_a], username="target-admin")
        target.groups.add(Group.objects.get(name="Teachers"))
        self._post(client_for(school_admin_user), target.school_staff, ["Teachers"])
        assert target.groups.filter(name="Admins").exists()
