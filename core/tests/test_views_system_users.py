"""
View tests for System Users: list (system-level only), detail and edit.
"""

import pytest
from django.contrib.auth.models import Group
from django.urls import reverse

from conftest import SystemUserFactory, UserFactory

pytestmark = pytest.mark.django_db


@pytest.fixture
def system_users(db):
    return {
        "moe": SystemUserFactory(
            user=UserFactory(first_name="Mere", last_name="Moana", email="mere@moe.org"),
            organization="Ministry of Education",
        ),
        "unicef": SystemUserFactory(
            user=UserFactory(first_name="Ulan", last_name="Ubay", email="ulan@unicef.org"),
            organization="UNICEF",
        ),
    }


class TestSystemUserList:
    url = reverse("core:system_user_list")

    def _pks(self, response):
        return {s.pk for s in response.context["page_obj"].object_list}

    @pytest.mark.parametrize("role", ["superuser", "admin_user", "system_admin_user", "system_staff_user"])
    def test_system_roles_can_list(self, request, client_for, system_users, role):
        response = client_for(request.getfixturevalue(role)).get(self.url)
        assert response.status_code == 200
        assert self._pks(response) >= {system_users["moe"].pk, system_users["unicef"].pk}

    @pytest.mark.parametrize("role", ["school_admin_user", "teacher_user", "school_staff_user"])
    def test_school_roles_are_forbidden(self, request, client_for, system_users, role):
        response = client_for(request.getfixturevalue(role)).get(self.url)
        assert response.status_code == 403

    def test_search_and_filters(self, client_for, superuser, system_users):
        client = client_for(superuser)
        assert self._pks(client.get(self.url, {"q": "moan"})) == {system_users["moe"].pk}
        assert self._pks(client.get(self.url, {"email": "unicef"})) == {system_users["unicef"].pk}
        assert self._pks(client.get(self.url, {"organization": "ministry"})) == {system_users["moe"].pk}

    def test_sort_by_organization_desc(self, client_for, superuser, system_users):
        response = client_for(superuser).get(self.url, {"sort": "organization", "dir": "desc"})
        orgs = [s.organization for s in response.context["page_obj"].object_list]
        assert orgs == sorted(orgs, reverse=True)

    def test_user_can_edit_flag(self, client_for, system_staff_user, system_admin_user, system_users):
        assert client_for(system_staff_user).get(self.url).context["user_can_edit"] is False
        assert client_for(system_admin_user).get(self.url).context["user_can_edit"] is True


class TestSystemUserDetail:
    def url(self, su):
        return reverse("core:system_user_detail", kwargs={"pk": su.pk})

    def test_system_staff_can_view_but_not_edit(self, client_for, system_staff_user, system_users):
        response = client_for(system_staff_user).get(self.url(system_users["moe"]))
        assert response.status_code == 200
        assert response.context["can_edit"] is False

    def test_school_role_forbidden(self, client_for, school_admin_user, system_users):
        assert client_for(school_admin_user).get(self.url(system_users["moe"])).status_code == 403

    def test_groups_are_summarised(self, client_for, superuser, system_admin_user):
        response = client_for(superuser).get(self.url(system_admin_user.system_user))
        assert [g["group"].name for g in response.context["group_permissions"]] == ["System Admins"]
        assert response.context["can_edit"] is True

    def test_404(self, client_for, superuser):
        assert client_for(superuser).get(reverse("core:system_user_detail", kwargs={"pk": 999999})).status_code == 404


class TestSystemUserEdit:
    def url(self, su):
        return reverse("core:system_user_edit", kwargs={"pk": su.pk})

    def _post(self, client, su, groups, organization="Org", position="Pos"):
        ids = [Group.objects.get(name=g).pk for g in groups]
        return client.post(self.url(su), {"organization": organization, "position_title": position, "groups": ids})

    def test_system_staff_is_redirected_with_message(self, client_for, system_staff_user, system_users):
        response = client_for(system_staff_user).get(self.url(system_users["moe"]))
        assert response.status_code == 302
        assert response["Location"] == reverse("core:system_user_detail", kwargs={"pk": system_users["moe"].pk})

    def test_school_role_forbidden(self, client_for, teacher_user, system_users):
        assert client_for(teacher_user).get(self.url(system_users["moe"])).status_code == 403

    def test_admin_edits_fields_and_groups(self, client_for, admin_user, system_users):
        su = system_users["moe"]
        response = self._post(client_for(admin_user), su, ["System Staff"], "New Org", "New Pos")
        assert response.status_code == 302
        su.refresh_from_db()
        assert su.organization == "New Org" and su.position_title == "New Pos"
        assert su.last_updated_by == admin_user
        assert set(su.user.groups.values_list("name", flat=True)) == {"System Staff"}

    def test_system_admin_cannot_grant_admins(self, client_for, system_admin_user, system_users):
        su = system_users["moe"]
        response = self._post(client_for(system_admin_user), su, ["Admins"])
        assert response.status_code == 200
        assert "groups" in response.context["form"].errors
        assert not su.user.groups.filter(name="Admins").exists()

    def test_system_admin_can_grant_system_admins(self, client_for, system_admin_user, system_users):
        su = system_users["moe"]
        self._post(client_for(system_admin_user), su, ["System Admins"])
        assert su.user.groups.filter(name="System Admins").exists()

    def test_limited_editor_does_not_strip_existing_admins_membership(
        self, client_for, system_admin_user, make_system_user
    ):
        """An editor who cannot grant Admins must not remove it either."""
        target = make_system_user("Admins", username="target-admin")
        target.groups.add(Group.objects.get(name="System Staff"))
        self._post(client_for(system_admin_user), target.system_user, ["System Admins"])
        assert set(target.groups.values_list("name", flat=True)) == {"Admins", "System Admins"}

    def test_full_editor_can_remove_admins_membership(self, client_for, admin_user, make_system_user):
        target = make_system_user("Admins", username="target-admin")
        self._post(client_for(admin_user), target.system_user, ["System Staff"])
        assert set(target.groups.values_list("name", flat=True)) == {"System Staff"}

    def test_school_level_groups_are_preserved(self, client_for, superuser, system_users):
        su = system_users["moe"]
        su.user.groups.add(Group.objects.get(name="Teachers"))
        self._post(client_for(superuser), su, ["System Staff"])
        assert set(su.user.groups.values_list("name", flat=True)) == {"System Staff", "Teachers"}

    def test_groups_required(self, client_for, superuser, system_users):
        su = system_users["moe"]
        response = client_for(superuser).post(self.url(su), {"organization": "x", "position_title": "y", "groups": []})
        assert response.status_code == 200
        assert "groups" in response.context["form"].errors
