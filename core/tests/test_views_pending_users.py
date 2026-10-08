"""
View tests for pending-user management: listing users without a profile,
assigning them as School Staff or System User, and deleting them.
"""

import pytest
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.contrib.messages import get_messages
from django.urls import reverse

from conftest import UserFactory
from core.models import SchoolStaff, SystemUser

User = get_user_model()
pytestmark = pytest.mark.django_db


def messages_of(response):
    return [str(m) for m in get_messages(response.wsgi_request)]


def gid(name):
    return Group.objects.get(name=name).pk


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

    @pytest.mark.parametrize("role", ["superuser", "admin_user", "system_admin_user"])
    def test_managers_see_pending_users_only(self, request, client_for, pendings, teacher_user, superuser, role):
        response = client_for(request.getfixturevalue(role)).get(self.url)
        assert response.status_code == 200
        pks = self._pks(response)
        assert {pendings["p1"].pk, pendings["p2"].pk} <= pks
        assert teacher_user.pk not in pks  # has a profile
        assert superuser.pk not in pks  # superusers are excluded

    @pytest.mark.parametrize("role", ["system_staff_user", "school_admin_user", "teacher_user", "school_staff_user"])
    def test_others_forbidden(self, request, client_for, pendings, role):
        assert client_for(request.getfixturevalue(role)).get(self.url).status_code == 403

    def test_search(self, client_for, superuser, pendings):
        client = client_for(superuser)
        assert self._pks(client.get(self.url, {"q": "paul@"})) == {pendings["p2"].pk}
        assert self._pks(client.get(self.url, {"q": "pending-one"})) == {pendings["p1"].pk}
        assert self._pks(client.get(self.url, {"q": "One"})) == {pendings["p1"].pk}


class TestAssignSchoolStaff:
    def url(self, user):
        return reverse("core:assign_school_staff", kwargs={"user_id": user.pk})

    def test_forbidden_for_system_staff(self, client_for, system_staff_user, pendings):
        assert client_for(system_staff_user).get(self.url(pendings["p1"])).status_code == 403

    def test_admin_assigns_profile_and_groups(self, client_for, admin_user, pendings):
        target = pendings["p1"]
        response = client_for(admin_user).post(
            self.url(target), {"staff_type": "teaching", "groups": [gid("Teachers"), gid("School Staff")]}
        )
        assert response.status_code == 302
        staff = SchoolStaff.objects.get(user=target)
        assert response["Location"] == reverse("core:staff_detail", kwargs={"pk": staff.pk})
        assert staff.staff_type == "teaching"
        assert staff.created_by == admin_user and staff.last_updated_by == admin_user
        assert set(target.groups.values_list("name", flat=True)) == {"Teachers", "School Staff"}

    def test_system_admin_cannot_assign_admins(self, client_for, system_admin_user, pendings):
        target = pendings["p1"]
        response = client_for(system_admin_user).post(self.url(target), {"staff_type": "teaching", "groups": [gid("Admins")]})
        assert response.status_code == 200
        assert "groups" in response.context["form"].errors
        assert not SchoolStaff.objects.filter(user=target).exists()

    def test_admin_can_assign_admins(self, client_for, admin_user, pendings):
        target = pendings["p1"]
        client_for(admin_user).post(self.url(target), {"staff_type": "non_teaching", "groups": [gid("Admins")]})
        assert target.groups.filter(name="Admins").exists()

    def test_already_has_profile_redirects_with_warning(self, client_for, admin_user, teacher_user):
        response = client_for(admin_user).get(self.url(teacher_user))
        assert response.status_code == 302
        assert response["Location"] == reverse("core:pending_users_list")
        assert any("already has a School Staff profile" in m for m in messages_of(response))

    def test_unknown_user_404(self, client_for, admin_user):
        assert client_for(admin_user).get(reverse("core:assign_school_staff", kwargs={"user_id": 999999})).status_code == 404

    def test_groups_required(self, client_for, admin_user, pendings):
        response = client_for(admin_user).post(self.url(pendings["p1"]), {"staff_type": "teaching", "groups": []})
        assert response.status_code == 200
        assert not SchoolStaff.objects.filter(user=pendings["p1"]).exists()


class TestAssignSystemUser:
    def url(self, user):
        return reverse("core:assign_system_user", kwargs={"user_id": user.pk})

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
