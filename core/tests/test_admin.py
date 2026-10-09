"""
Tests for the Django admin registrations: every registered model's list,
add and change pages render, the custom user role filter works, and the
audit mixin stamps created_by / last_updated_by through the admin (including
inline formsets).
"""

import datetime as dt

import pytest
from django.contrib import admin
from django.contrib.auth import get_user_model
from django.test import RequestFactory
from django.urls import reverse

from conftest import (
    SchoolStaffAssignmentFactory,
    SchoolStaffFactory,
    StudentFactory,
    StudentSchoolEnrolmentFactory,
    SystemUserFactory,
    UserFactory,
)
from core.admin import CustomUserAdmin, HasRoleFilter
from core.mixins import CreatedUpdatedAuditMixin
from core.models import SchoolStaff, SchoolStaffAssignment, Student, StudentSchoolEnrolment, SystemUser
from integrations.models import EmisClassLevel, EmisJobTitle, EmisSchool, EmisWarehouseYear

User = get_user_model()
pytestmark = pytest.mark.django_db


def admin_url(model, page, *args):
    return reverse(f"admin:{model._meta.app_label}_{model._meta.model_name}_{page}", args=args)


@pytest.fixture
def objects(db, school_a, school_year, class_level, job_title):
    staff = SchoolStaffAssignmentFactory(school=school_a, job_title=job_title).school_staff
    enrolment = StudentSchoolEnrolmentFactory(school=school_a, school_year=school_year, class_level=class_level)
    return {
        User: staff.user,
        SchoolStaff: staff,
        SystemUser: SystemUserFactory(),
        Student: enrolment.student,
        EmisSchool: school_a,
        EmisClassLevel: class_level,
        EmisJobTitle: job_title,
        EmisWarehouseYear: school_year,
    }


REGISTERED = [User, SchoolStaff, SystemUser, Student, EmisSchool, EmisClassLevel, EmisJobTitle, EmisWarehouseYear]


class TestAdminPagesRender:
    def test_expected_models_are_registered(self):
        for model in REGISTERED:
            assert model in admin.site._registry, model
        assert SchoolStaffAssignment not in admin.site._registry
        assert StudentSchoolEnrolment not in admin.site._registry

    @pytest.mark.parametrize("model", REGISTERED, ids=[m.__name__ for m in REGISTERED])
    def test_changelist_add_change(self, client_for, superuser, objects, model):
        client = client_for(superuser)
        assert client.get(admin_url(model, "changelist")).status_code == 200
        assert client.get(admin_url(model, "add")).status_code == 200
        assert client.get(admin_url(model, "change", objects[model].pk)).status_code == 200

    @pytest.mark.parametrize("model", REGISTERED, ids=[m.__name__ for m in REGISTERED])
    def test_search_does_not_error(self, client_for, superuser, objects, model):
        response = client_for(superuser).get(admin_url(model, "changelist"), {"q": "a"})
        assert response.status_code == 200

    def test_student_changelist_related_filters(self, client_for, superuser, objects, school_a):
        response = client_for(superuser).get(
            admin_url(Student, "changelist"), {"enrolments__school__emis_school_no__exact": school_a.pk}
        )
        assert response.status_code == 200
        assert list(response.context["cl"].queryset) == [objects[Student]]

    def test_autocomplete_endpoints(self, client_for, superuser, objects):
        client = client_for(superuser)
        response = client.get(
            reverse("admin:autocomplete"),
            {"app_label": "core", "model_name": "schoolstaffassignment", "field_name": "school", "term": "Alpha"},
        )
        assert response.status_code == 200
        assert [r["id"] for r in response.json()["results"]] == ["KPS001"]

    def test_non_staff_user_cannot_enter_admin(self, client_for, admin_user):
        response = client_for(admin_user).get("/admin/")
        assert response.status_code == 302  # bounced to admin login


class TestCustomUserAdmin:
    def _changelist(self, client, **params):
        return client.get(admin_url(User, "changelist"), params).context["cl"].queryset

    def test_role_filter_lookups(self, client_for, superuser, teacher_user, system_staff_user, pending_user):
        client = client_for(superuser)
        both = UserFactory(username="both")
        SchoolStaffFactory(user=both)
        SystemUserFactory(user=both)

        assert set(self._changelist(client, role="no_role")) == {superuser, pending_user}
        assert set(self._changelist(client, role="school_staff")) == {teacher_user, both}
        assert set(self._changelist(client, role="system_user")) == {system_staff_user, both}
        assert set(self._changelist(client, role="both")) == {both}
        assert self._changelist(client).count() == 5

    def test_role_status_labels(self, teacher_user, system_staff_user, pending_user):
        ma = CustomUserAdmin(User, admin.site)
        qs = ma.get_queryset(RequestFactory().get("/"))
        assert "School Staff" in ma.role_status(qs.get(pk=teacher_user.pk))
        assert "System User" in ma.role_status(qs.get(pk=system_staff_user.pk))
        assert "No role" in ma.role_status(qs.get(pk=pending_user.pk))
        both = UserFactory(username="both")
        SchoolStaffFactory(user=both)
        SystemUserFactory(user=both)
        assert "Both roles" in ma.role_status(qs.get(pk=both.pk))

    def test_filter_with_unknown_value_returns_all(self, superuser):
        f = HasRoleFilter(RequestFactory().get("/"), {"role": ["weird"]}, User, CustomUserAdmin(User, admin.site))
        assert f.queryset(None, User.objects.all()).count() == User.objects.count()


class TestAuditMixinThroughAdmin:
    def test_adding_student_with_inline_stamps_audit_fields(
        self, client_for, superuser, school_a, school_year, class_level
    ):
        data = {
            "first_name": "Admin",
            "last_name": "Added",
            "date_of_birth": "2015-01-01",
            "gender": "",
            "enrolments-TOTAL_FORMS": "1",
            "enrolments-INITIAL_FORMS": "0",
            "enrolments-MIN_NUM_FORMS": "0",
            "enrolments-MAX_NUM_FORMS": "1000",
            "enrolments-0-school": school_a.pk,
            "enrolments-0-school_year": school_year.pk,
            "enrolments-0-class_level": class_level.pk,
            "enrolments-0-cft1_wears_glasses": "2",
        }
        response = client_for(superuser).post(admin_url(Student, "add"), data)
        assert response.status_code == 302, response.context["adminform"].form.errors if response.context else response
        student = Student.objects.get(last_name="Added")
        assert student.created_by == superuser and student.last_updated_by == superuser
        enrolment = student.enrolments.get()
        assert enrolment.created_by == superuser and enrolment.last_updated_by == superuser
        assert enrolment.cft1_wears_glasses == 2

    def test_changing_system_user_keeps_creator_and_updates_updater(self, client_for, superuser, admin_user):
        su = SystemUserFactory(created_by=admin_user, last_updated_by=admin_user)
        response = client_for(superuser).post(
            admin_url(SystemUser, "change", su.pk),
            {"user": su.user.pk, "organization": "Changed", "position_title": ""},
        )
        assert response.status_code == 302
        su.refresh_from_db()
        assert su.organization == "Changed"
        assert su.created_by == admin_user
        assert su.last_updated_by == superuser

    def test_deleting_inline_assignment_through_admin(self, client_for, superuser, school_a, job_title):
        assignment = SchoolStaffAssignmentFactory(school=school_a, job_title=job_title)
        staff = assignment.school_staff
        data = {
            "user": staff.user.pk,
            "staff_type": "teaching",
            "assignments-TOTAL_FORMS": "1",
            "assignments-INITIAL_FORMS": "1",
            "assignments-MIN_NUM_FORMS": "0",
            "assignments-MAX_NUM_FORMS": "1000",
            "assignments-0-id": assignment.pk,
            "assignments-0-school_staff": staff.pk,
            "assignments-0-school": school_a.pk,
            "assignments-0-job_title": job_title.pk,
            "assignments-0-start_date": "",
            "assignments-0-end_date": "",
            "assignments-0-DELETE": "on",
        }
        response = client_for(superuser).post(admin_url(SchoolStaff, "change", staff.pk), data)
        assert response.status_code == 302
        assert not SchoolStaffAssignment.objects.filter(pk=assignment.pk).exists()
        staff.refresh_from_db()
        assert staff.staff_type == "teaching" and staff.last_updated_by == superuser


class TestAuditMixinUnit:
    class _Base:
        def save_model(self, request, obj, form, change):
            obj.save()

    class _Admin(CreatedUpdatedAuditMixin, _Base):
        pass

    def _request(self, user):
        request = RequestFactory().post("/")
        request.user = user
        return request

    def test_create_sets_both_when_empty(self, superuser):
        obj = SystemUserFactory.build(user=UserFactory())
        self._Admin().save_model(self._request(superuser), obj, None, change=False)
        assert obj.created_by == superuser and obj.last_updated_by == superuser

    def test_create_preserves_explicit_creator(self, superuser, admin_user):
        obj = SystemUserFactory.build(user=UserFactory(), created_by=admin_user)
        self._Admin().save_model(self._request(superuser), obj, None, change=False)
        assert obj.created_by == admin_user and obj.last_updated_by == superuser

    def test_change_only_touches_updater(self, superuser, admin_user):
        obj = SystemUserFactory(created_by=admin_user, last_updated_by=admin_user)
        self._Admin().save_model(self._request(superuser), obj, None, change=True)
        assert obj.created_by == admin_user and obj.last_updated_by == superuser

    def test_object_without_audit_fields_is_fine(self, superuser):
        obj = EmisSchool(emis_school_no="KPS111", emis_school_name="x")
        self._Admin().save_model(self._request(superuser), obj, None, change=False)
