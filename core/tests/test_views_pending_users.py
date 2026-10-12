"""
View tests for pending-user management: listing users without a profile,
assigning them as School Staff (single step, with the first school
assignment) or System User, and deleting them.

School Admins with an active school can see the list and on-board School
Staff at their own schools only (issue #74); everything else stays with
Admins / System Admins.
"""

import pytest
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.contrib.messages import get_messages
from django.urls import reverse

from conftest import SchoolStaffAssignmentFactory, UserFactory
from core.models import SchoolStaff, SchoolStaffAssignment, SystemUser

User = get_user_model()
pytestmark = pytest.mark.django_db


def messages_of(response):
    return [str(m) for m in get_messages(response.wsgi_request)]


def gid(name):
    return Group.objects.get(name=name).pk


def staff_data(school, job_title, *groups, start="2026-01-05"):
    """POST body for the single-step assign-as-School-Staff form."""
    return {
        "school": school.pk,
        "job_title": job_title.pk,
        "start_date": start,
        "groups": [gid(g) for g in groups],
    }


@pytest.fixture
def pendings(db):
    return {
        "p1": UserFactory(username="pending-one", first_name="Pia", last_name="One", email="pia@example.org"),
        "p2": UserFactory(username="pending-two", first_name="Paul", last_name="Two", email="paul@example.org"),
    }


class TestPendingUsersList:
    url = reverse("core:pending_users_list")

    def _pks(self, response):
        return {u.pk for u in response.context["page_obj"].object_list}

    @pytest.mark.parametrize("role", ["superuser", "admin_user", "system_admin_user", "school_admin_user"])
    def test_managers_see_pending_users_only(self, request, client_for, pendings, teacher_user, superuser, role):
        response = client_for(request.getfixturevalue(role)).get(self.url)
        assert response.status_code == 200
        pks = self._pks(response)
        assert {pendings["p1"].pk, pendings["p2"].pk} <= pks
        assert teacher_user.pk not in pks  # has a profile
        assert superuser.pk not in pks  # superusers are excluded

    @pytest.mark.parametrize("role", ["system_staff_user", "teacher_user", "school_staff_user"])
    def test_others_forbidden(self, request, client_for, pendings, role):
        assert client_for(request.getfixturevalue(role)).get(self.url).status_code == 403

    def test_school_admin_without_active_school_forbidden(self, client_for, school_admin_user, pendings):
        SchoolStaffAssignment.objects.filter(school_staff__user=school_admin_user).update(end_date="2000-01-01")
        assert client_for(school_admin_user).get(self.url).status_code == 403

    def test_school_admin_only_gets_the_school_staff_action(self, client_for, school_admin_user, pendings):
        html = client_for(school_admin_user).get(self.url).content.decode()
        p1 = pendings["p1"]
        assert reverse("core:assign_school_staff", kwargs={"user_id": p1.pk}) in html
        assert reverse("core:assign_system_user", kwargs={"user_id": p1.pk}) not in html
        assert reverse("core:delete_pending_user", kwargs={"user_id": p1.pk}) not in html

    def test_admin_gets_all_actions(self, client_for, admin_user, pendings):
        html = client_for(admin_user).get(self.url).content.decode()
        p1 = pendings["p1"]
        assert reverse("core:assign_system_user", kwargs={"user_id": p1.pk}) in html
        assert reverse("core:delete_pending_user", kwargs={"user_id": p1.pk}) in html

    def test_search(self, client_for, superuser, pendings):
        client = client_for(superuser)
        assert self._pks(client.get(self.url, {"q": "paul@"})) == {pendings["p2"].pk}
        assert self._pks(client.get(self.url, {"q": "pending-one"})) == {pendings["p1"].pk}
        assert self._pks(client.get(self.url, {"q": "One"})) == {pendings["p1"].pk}


class TestAssignSchoolStaff:
    def url(self, user):
        return reverse("core:assign_school_staff", kwargs={"user_id": user.pk})

    @pytest.mark.parametrize("role", ["system_staff_user", "teacher_user", "school_staff_user"])
    def test_forbidden_for_non_onboarders(self, request, client_for, pendings, role):
        assert client_for(request.getfixturevalue(role)).get(self.url(pendings["p1"])).status_code == 403

    def test_admin_assigns_profile_groups_and_first_school(self, client_for, admin_user, pendings, school_b, job_title):
        target = pendings["p1"]
        response = client_for(admin_user).post(
            self.url(target), staff_data(school_b, job_title, "Teachers", "School Admins")
        )
        assert response.status_code == 302
        staff = SchoolStaff.objects.get(user=target)
        assert response["Location"] == reverse("core:staff_detail", kwargs={"pk": staff.pk})
        assert staff.staff_type == "teaching"  # derived from the Teachers group
        assert staff.created_by == admin_user and staff.last_updated_by == admin_user
        assert set(target.groups.values_list("name", flat=True)) == {"Teachers", "School Admins"}
        assignment = staff.assignments.get()
        assert assignment.school == school_b and assignment.job_title == job_title
        assert str(assignment.start_date) == "2026-01-05" and assignment.end_date is None
        assert assignment.created_by == admin_user and assignment.last_updated_by == admin_user

    def test_non_teaching_group_gives_non_teaching_staff(self, client_for, admin_user, pendings, school_a, job_title):
        target = pendings["p1"]
        client_for(admin_user).post(self.url(target), staff_data(school_a, job_title, "School Staff"))
        assert SchoolStaff.objects.get(user=target).staff_type == "non_teaching"

    def test_system_admin_cannot_assign_admins(self, client_for, system_admin_user, pendings, school_a, job_title):
        target = pendings["p1"]
        response = client_for(system_admin_user).post(self.url(target), staff_data(school_a, job_title, "Admins"))
        assert response.status_code == 200
        assert "groups" in response.context["form"].errors
        assert not SchoolStaff.objects.filter(user=target).exists()

    def test_admin_can_assign_admins(self, client_for, admin_user, pendings, school_a, job_title):
        target = pendings["p1"]
        client_for(admin_user).post(self.url(target), staff_data(school_a, job_title, "Admins"))
        assert target.groups.filter(name="Admins").exists()
        assert SchoolStaff.objects.get(user=target).staff_type == "non_teaching"

    def test_teachers_and_school_staff_together_rejected(self, client_for, admin_user, pendings, school_a, job_title):
        target = pendings["p1"]
        response = client_for(admin_user).post(
            self.url(target), staff_data(school_a, job_title, "Teachers", "School Staff")
        )
        assert response.status_code == 200
        assert "groups" in response.context["form"].errors
        assert not SchoolStaff.objects.filter(user=target).exists()

    def test_school_assignment_fields_required(self, client_for, admin_user, pendings, school_a, job_title):
        target = pendings["p1"]
        response = client_for(admin_user).post(self.url(target), {"groups": [gid("Teachers")]})
        assert response.status_code == 200
        assert {"school", "job_title", "start_date"} <= set(response.context["form"].errors)
        assert not SchoolStaff.objects.filter(user=target).exists()

    # --- School Admins on-boarding their own teachers (issue #74) ---

    def test_school_admin_form_is_scoped_to_own_school(self, client_for, school_admin_user, pendings, school_a, school_b):
        response = client_for(school_admin_user).get(self.url(pendings["p1"]))
        assert response.status_code == 200
        form = response.context["form"]
        assert list(form.fields["school"].queryset) == [school_a]
        assert form.fields["school"].initial == school_a.pk
        assert list(form.fields["groups"].queryset.values_list("name", flat=True)) == ["School Staff", "Teachers"]

    def test_school_admin_onboards_teacher_at_own_school(self, client_for, school_admin_user, pendings, school_a, job_title):
        target = pendings["p1"]
        response = client_for(school_admin_user).post(self.url(target), staff_data(school_a, job_title, "Teachers"))
        assert response.status_code == 302
        staff = SchoolStaff.objects.get(user=target)
        assert staff.staff_type == "teaching"
        assert list(target.groups.values_list("name", flat=True)) == ["Teachers"]
        assert staff.assignments.get().school == school_a

    def test_school_admin_cannot_onboard_to_other_school(self, client_for, school_admin_user, pendings, school_b, job_title):
        target = pendings["p1"]
        response = client_for(school_admin_user).post(self.url(target), staff_data(school_b, job_title, "Teachers"))
        assert response.status_code == 200
        assert "school" in response.context["form"].errors
        assert not SchoolStaff.objects.filter(user=target).exists()

    def test_school_admin_cannot_grant_admin_groups(self, client_for, school_admin_user, pendings, school_a, job_title):
        target = pendings["p1"]
        for name in ("Admins", "School Admins"):
            response = client_for(school_admin_user).post(self.url(target), staff_data(school_a, job_title, name))
            assert response.status_code == 200
            assert "groups" in response.context["form"].errors
        assert not SchoolStaff.objects.filter(user=target).exists()

    def test_school_admin_with_two_schools_picks_one(
        self, client_for, school_admin_user, pendings, school_a, school_b, job_title
    ):
        SchoolStaffAssignmentFactory(
            school_staff=school_admin_user.school_staff, school=school_b, job_title=job_title
        )
        target = pendings["p1"]
        response = client_for(school_admin_user).get(self.url(target))
        assert set(response.context["form"].fields["school"].queryset) == {school_a, school_b}
        client_for(school_admin_user).post(self.url(target), staff_data(school_b, job_title, "Teachers"))
        assert SchoolStaff.objects.get(user=target).assignments.get().school == school_b

    def test_school_admin_without_active_school_forbidden(self, client_for, school_admin_user, pendings):
        SchoolStaffAssignment.objects.filter(school_staff__user=school_admin_user).update(end_date="2000-01-01")
        assert client_for(school_admin_user).get(self.url(pendings["p1"])).status_code == 403

    def test_onboarded_teacher_can_now_enter_the_app(
        self, client_for, school_admin_user, pendings, school_a, job_title, client
    ):
        target = pendings["p1"]
        client_for(school_admin_user).post(self.url(target), staff_data(school_a, job_title, "Teachers"))
        client.logout()
        client.force_login(target)
        assert client.get(reverse("core:dashboard")).status_code == 200

    def test_already_has_profile_redirects_with_warning(self, client_for, admin_user, teacher_user):
        response = client_for(admin_user).get(self.url(teacher_user))
        assert response.status_code == 302
        assert response["Location"] == reverse("core:pending_users_list")
        assert any("already has a School Staff profile" in m for m in messages_of(response))

    def test_unknown_user_404(self, client_for, admin_user):
        assert client_for(admin_user).get(reverse("core:assign_school_staff", kwargs={"user_id": 999999})).status_code == 404

    def test_groups_required(self, client_for, admin_user, pendings, school_a, job_title):
        response = client_for(admin_user).post(self.url(pendings["p1"]), staff_data(school_a, job_title))
        assert response.status_code == 200
        assert "groups" in response.context["form"].errors
        assert not SchoolStaff.objects.filter(user=pendings["p1"]).exists()


class TestAssignSystemUser:
    def url(self, user):
        return reverse("core:assign_system_user", kwargs={"user_id": user.pk})

    def test_forbidden_for_school_admin(self, client_for, school_admin_user, pendings):
        """School Admins can on-board School Staff but never System Users."""
        assert client_for(school_admin_user).get(self.url(pendings["p2"])).status_code == 403

    def test_admin_assigns(self, client_for, admin_user, pendings):
        target = pendings["p2"]
        response = client_for(admin_user).post(
            self.url(target),
            {"organization": "MOE", "position_title": "Analyst", "groups": [gid("System Staff")]},
        )
        assert response.status_code == 302
        su = SystemUser.objects.get(user=target)
        assert response["Location"] == reverse("core:system_user_detail", kwargs={"pk": su.pk})
        assert su.organization == "MOE" and su.position_title == "Analyst"
        assert su.created_by == admin_user
        assert list(target.groups.values_list("name", flat=True)) == ["System Staff"]

    def test_system_admin_cannot_assign_admins(self, client_for, system_admin_user, pendings):
        target = pendings["p2"]
        response = client_for(system_admin_user).post(self.url(target), {"groups": [gid("Admins")]})
        assert response.status_code == 200
        assert not SystemUser.objects.filter(user=target).exists()

    def test_system_admin_can_assign_system_admins(self, client_for, system_admin_user, pendings):
        target = pendings["p2"]
        client_for(system_admin_user).post(self.url(target), {"groups": [gid("System Admins")]})
        assert target.groups.filter(name="System Admins").exists()

    def test_already_has_profile_redirects(self, client_for, admin_user, system_staff_user):
        response = client_for(admin_user).get(self.url(system_staff_user))
        assert response.status_code == 302
        assert any("already has a System User profile" in m for m in messages_of(response))

    def test_newly_assigned_user_can_now_enter_the_app(self, client_for, admin_user, pendings, client):
        target = pendings["p2"]
        client_for(admin_user).post(self.url(target), {"groups": [gid("System Staff")]})
        client.logout()
        client.force_login(target)
        assert client.get(reverse("core:dashboard")).status_code == 200


class TestDeletePendingUser:
    def url(self, user):
        return reverse("core:delete_pending_user", kwargs={"user_id": user.pk})

    def test_forbidden_for_non_managers(self, client_for, school_admin_user, pendings):
        assert client_for(school_admin_user).post(self.url(pendings["p1"])).status_code == 403

    def test_confirm_then_delete(self, client_for, admin_user, pendings):
        target = pendings["p1"]
        client = client_for(admin_user)
        assert client.get(self.url(target)).status_code == 200
        response = client.post(self.url(target))
        assert response.status_code == 302
        assert not User.objects.filter(pk=target.pk).exists()
        assert any("has been deleted" in m for m in messages_of(response))

    def test_cannot_delete_user_with_profile(self, client_for, admin_user, teacher_user):
        response = client_for(admin_user).post(self.url(teacher_user))
        assert response.status_code == 302
        assert User.objects.filter(pk=teacher_user.pk).exists()
        assert any("already has a role" in m for m in messages_of(response))

    def test_cannot_delete_self(self, client_for, superuser):
        response = client_for(superuser).post(self.url(superuser))
        assert response.status_code == 302
        assert User.objects.filter(pk=superuser.pk).exists()
        assert any("your own account" in m for m in messages_of(response))

    def test_cannot_delete_superuser(self, client_for, admin_user, superuser):
        response = client_for(admin_user).post(self.url(superuser))
        assert response.status_code == 302
        assert User.objects.filter(pk=superuser.pk).exists()
        assert any("Superusers cannot be deleted" in m for m in messages_of(response))
