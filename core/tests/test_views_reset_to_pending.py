"""
View tests for resetting an on-boarded user back to pending: the profile,
school assignments and groups go; the User row and everything the user
created or edited stay.

Admins and superusers may reset a user with no audit footprint. Only a
superuser may force a reset when a footprint exists, and must tick the
acknowledgement. Nobody can reset themself or a superuser.
"""

import pytest
from django.contrib.auth import get_user_model
from django.contrib.messages import get_messages
from django.urls import reverse

from conftest import StudentFactory, SystemUserFactory
from core.models import SchoolStaff, SchoolStaffAssignment, Student, SystemUser
from core.views import user_audit_footprint

User = get_user_model()
pytestmark = pytest.mark.django_db


def url(user):
    return reverse("core:reset_user_to_pending", kwargs={"user_id": user.pk})


def messages_of(response):
    return [str(m) for m in get_messages(response.wsgi_request)]


def is_pending(user):
    user.refresh_from_db()
    return (
        not SchoolStaff.objects.filter(user=user).exists()
        and not SystemUser.objects.filter(user=user).exists()
        and user.groups.count() == 0
    )


class TestAccess:
    @pytest.mark.parametrize(
        "role", ["system_admin_user", "system_staff_user", "school_admin_user", "teacher_user", "school_staff_user"]
    )
    def test_non_admins_forbidden(self, request, client_for, teacher_user, school_staff_user, role):
        actor = request.getfixturevalue(role)
        target = school_staff_user if actor is not school_staff_user else teacher_user
        client = client_for(actor)
        assert client.get(url(target)).status_code == 403
        assert client.post(url(target)).status_code == 403
        assert not is_pending(target)

    @pytest.mark.parametrize("role", ["superuser", "admin_user"])
    def test_admins_see_confirm_page(self, request, client_for, teacher_user, role):
        response = client_for(request.getfixturevalue(role)).get(url(teacher_user))
        assert response.status_code == 200
        assert response.context["has_footprint"] is False
        assert response.context["profile_kind"] == "School Staff"
        assert len(response.context["assignments"]) == 1
        assert response.context["group_names"] == ["Teachers"]

    def test_cannot_reset_self(self, client_for, admin_user):
        response = client_for(admin_user).post(url(admin_user))
        assert response.status_code == 302
        assert any("your own account" in m for m in messages_of(response))
        assert not is_pending(admin_user)

    def test_cannot_reset_superuser(self, client_for, admin_user, superuser):
        SystemUserFactory(user=superuser)
        response = client_for(admin_user).post(url(superuser))
        assert response.status_code == 302
        assert any("Superusers cannot be reset" in m for m in messages_of(response))
        assert SystemUser.objects.filter(user=superuser).exists()

    def test_already_pending_redirects_to_list(self, client_for, admin_user, pending_user):
        response = client_for(admin_user).get(url(pending_user))
        assert response.status_code == 302
        assert response["Location"] == reverse("core:pending_users_list")

    def test_unknown_user_404(self, client_for, admin_user):
        assert client_for(admin_user).get(reverse("core:reset_user_to_pending", kwargs={"user_id": 999999})).status_code == 404


class TestCleanReset:
    def test_admin_resets_school_staff(self, client_for, admin_user, teacher_user, school_a):
        assert SchoolStaffAssignment.objects.filter(school_staff__user=teacher_user).count() == 1
        response = client_for(admin_user).post(url(teacher_user))
        assert response.status_code == 302
        assert response["Location"] == reverse("core:pending_users_list")
        assert is_pending(teacher_user)
        assert User.objects.filter(pk=teacher_user.pk).exists()
        assert not SchoolStaffAssignment.objects.filter(school_staff__user=teacher_user).exists()
        assert any("1 school assignment and 1 group were removed" in m for m in messages_of(response))

    def test_admin_resets_system_user(self, client_for, admin_user, system_staff_user):
        response = client_for(admin_user).post(url(system_staff_user))
        assert response.status_code == 302
        assert is_pending(system_staff_user)
        assert any("0 school assignments and 1 group" in m for m in messages_of(response))

    def test_reset_user_shows_up_as_pending_and_is_locked_out(self, client_for, admin_user, teacher_user, client):
        client_for(admin_user).post(url(teacher_user))
        listed = client_for(admin_user).get(reverse("core:pending_users_list")).context["page_obj"].object_list
        assert teacher_user.pk in {u.pk for u in listed}
        client.logout()
        client.force_login(teacher_user)
        response = client.get(reverse("core:dashboard"))
        assert response.status_code == 302
        assert response["Location"] == reverse("accounts:no_permissions")

    def test_reset_user_can_be_onboarded_again(self, client_for, admin_user, teacher_user, school_b, job_title):
        from django.contrib.auth.models import Group

        client = client_for(admin_user)
        client.post(url(teacher_user))
        response = client.post(
            reverse("core:assign_school_staff", kwargs={"user_id": teacher_user.pk}),
            {
                "school": school_b.pk,
                "job_title": job_title.pk,
                "start_date": "2026-02-01",
                "groups": [Group.objects.get(name="School Staff").pk],
            },
        )
        assert response.status_code == 302
        staff = SchoolStaff.objects.get(user=teacher_user)
        assert staff.staff_type == "non_teaching"
        assert staff.assignments.get().school == school_b


class TestFootprint:
    @pytest.fixture
    def busy_teacher(self, teacher_user, school_a, school_year, class_level):
        """A teacher who created two students and edited a third."""
        StudentFactory(created_by=teacher_user, last_updated_by=teacher_user)
        StudentFactory(created_by=teacher_user, last_updated_by=teacher_user)
        StudentFactory(last_updated_by=teacher_user)
        return teacher_user

    def test_footprint_counts_and_excludes_own_profile(self, busy_teacher, admin_user):
        # admin_user created nothing, so even the profiles they hold are not a footprint
        assert user_audit_footprint(admin_user) == []
        # own profile and assignment are excluded even when self-attributed
        staff = busy_teacher.school_staff
        SchoolStaff.objects.filter(pk=staff.pk).update(created_by=busy_teacher)
        SchoolStaffAssignment.objects.filter(school_staff=staff).update(last_updated_by=busy_teacher)
        assert user_audit_footprint(busy_teacher) == [("Students", 3)]

    def test_footprint_counts_other_profiles(self, admin_user, teacher_user, system_staff_user):
        SchoolStaff.objects.filter(user=teacher_user).update(created_by=admin_user)
        SystemUser.objects.filter(user=system_staff_user).update(last_updated_by=admin_user)
        assert user_audit_footprint(admin_user) == [
            ("School staff profiles", 1),
            ("System user profiles", 1),
        ]

    def test_admin_sees_footprint_but_cannot_force(self, client_for, admin_user, busy_teacher):
        client = client_for(admin_user)
        response = client.get(url(busy_teacher))
        assert response.status_code == 200
        assert response.context["footprint"] == [("Students", 3)]
        assert response.context["can_force"] is False
        assert "only a superuser can reset" in response.content.decode()
        assert client.post(url(busy_teacher), {"acknowledge": "yes"}).status_code == 403
        assert not is_pending(busy_teacher)

    def test_superuser_must_acknowledge(self, client_for, superuser, busy_teacher):
        response = client_for(superuser).post(url(busy_teacher))
        assert response.status_code == 200
        assert response.context["acknowledge_error"] is True
        assert not is_pending(busy_teacher)

    def test_superuser_forces_reset_and_records_are_kept(self, client_for, superuser, busy_teacher):
        response = client_for(superuser).post(url(busy_teacher), {"acknowledge": "yes"})
        assert response.status_code == 302
        assert is_pending(busy_teacher)
        assert Student.objects.count() == 3
        assert Student.objects.filter(created_by=busy_teacher).count() == 2
        assert Student.objects.filter(last_updated_by=busy_teacher).count() == 3


class TestDetailPageButtons:
    def test_admin_sees_reset_on_staff_and_system_user_pages(
        self, client_for, admin_user, teacher_user, system_staff_user
    ):
        client = client_for(admin_user)
        staff_page = client.get(reverse("core:staff_detail", kwargs={"pk": teacher_user.school_staff.pk}))
        assert url(teacher_user) in staff_page.content.decode()
        su_page = client.get(reverse("core:system_user_detail", kwargs={"pk": system_staff_user.system_user.pk}))
        assert url(system_staff_user) in su_page.content.decode()

    def test_no_reset_button_on_own_page(self, client_for, admin_user):
        page = client_for(admin_user).get(reverse("core:staff_detail", kwargs={"pk": admin_user.school_staff.pk}))
        assert url(admin_user) not in page.content.decode()

    def test_system_admin_does_not_see_reset(self, client_for, system_admin_user, system_staff_user):
        page = client_for(system_admin_user).get(
            reverse("core:system_user_detail", kwargs={"pk": system_staff_user.system_user.pk})
        )
        assert url(system_staff_user) not in page.content.decode()
