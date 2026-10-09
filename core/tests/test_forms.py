"""
Unit tests for core.forms: duplicate detection (PR #70), per-role narrowing
of school and group choices, and the dynamic CFT fields.
"""

import datetime as dt

import pytest
from django.contrib.auth.models import Group

from conftest import (
    EmisSchoolFactory,
    EmisWarehouseYearFactory,
    SchoolStaffAssignmentFactory,
    SchoolStaffFactory,
    StudentFactory,
    StudentSchoolEnrolmentFactory,
    SystemUserFactory,
)
from core import permissions as perms
from core.cft_meta import CFT_QUESTION_META
from core.forms import (
    AssignSchoolStaffForm,
    AssignSystemUserForm,
    SchoolStaffAssignmentForm,
    SchoolStaffEditForm,
    StudentCoreForm,
    StudentDisabilityIntakeForm,
    StudentEnrolmentForm,
    SystemUserEditForm,
)
from core.forms import TestEmailForm as EmailRecipientForm
from core.models import SchoolStaffAssignment, StudentSchoolEnrolment

pytestmark = pytest.mark.django_db

SCHOOL_GROUPS_ALL = ["Admins", "School Admins", "School Staff", "Teachers"]
SCHOOL_GROUPS_NO_ADMINS = ["School Admins", "School Staff", "Teachers"]
SYSTEM_GROUPS_ALL = ["Admins", "System Admins", "System Staff"]
SYSTEM_GROUPS_NO_ADMINS = ["System Admins", "System Staff"]


def group_names(form):
    return list(form.fields["groups"].queryset.values_list("name", flat=True))


# ============================================================================
# SchoolStaffAssignmentForm
# ============================================================================


class TestSchoolStaffAssignmentForm:
    def _data(self, school, job_title, start=None, end=None):
        return {
            "school": school.pk,
            "job_title": job_title.pk,
            "start_date": start.isoformat() if start else "",
            "end_date": end.isoformat() if end else "",
        }

    def test_valid_new_assignment(self, superuser, school_a, job_title):
        staff = SchoolStaffFactory()
        form = SchoolStaffAssignmentForm(
            self._data(school_a, job_title),
            instance=SchoolStaffAssignment(school_staff=staff),
            user=superuser,
        )
        assert form.is_valid(), form.errors

    def test_duplicate_open_ended_assignment_is_rejected(self, superuser, school_a, job_title):
        existing = SchoolStaffAssignmentFactory(school=school_a, job_title=job_title)
        form = SchoolStaffAssignmentForm(
            self._data(school_a, job_title),
            instance=SchoolStaffAssignment(school_staff=existing.school_staff),
            user=superuser,
        )
        assert not form.is_valid()
        assert "school" in form.errors
        assert "already has an assignment" in form.errors["school"][0]

    def test_duplicate_with_same_explicit_dates_is_rejected(self, superuser, school_a, job_title):
        start, end = dt.date(2024, 1, 1), dt.date(2024, 12, 31)
        existing = SchoolStaffAssignmentFactory(
            school=school_a, job_title=job_title, start_date=start, end_date=end
        )
        form = SchoolStaffAssignmentForm(
            self._data(school_a, job_title, start, end),
            instance=SchoolStaffAssignment(school_staff=existing.school_staff),
            user=superuser,
        )
        assert not form.is_valid()

    def test_same_school_with_different_dates_is_allowed(self, superuser, school_a, job_title):
        existing = SchoolStaffAssignmentFactory(
            school=school_a, job_title=job_title, end_date=dt.date(2023, 12, 31)
        )
        form = SchoolStaffAssignmentForm(
            self._data(school_a, job_title, start=dt.date(2024, 1, 1)),
            instance=SchoolStaffAssignment(school_staff=existing.school_staff),
            user=superuser,
        )
        assert form.is_valid(), form.errors

    def test_editing_an_assignment_does_not_collide_with_itself(self, superuser, school_a, job_title):
        existing = SchoolStaffAssignmentFactory(school=school_a, job_title=job_title)
        form = SchoolStaffAssignmentForm(
            self._data(school_a, job_title), instance=existing, user=superuser
        )
        assert form.is_valid(), form.errors

    def test_other_staff_at_same_school_is_not_a_duplicate(self, superuser, school_a, job_title):
        SchoolStaffAssignmentFactory(school=school_a, job_title=job_title)
        form = SchoolStaffAssignmentForm(
            self._data(school_a, job_title),
            instance=SchoolStaffAssignment(school_staff=SchoolStaffFactory()),
            user=superuser,
        )
        assert form.is_valid(), form.errors

    @pytest.mark.parametrize("role", ["superuser", "admin_user", "system_admin_user"])
    def test_admins_choose_from_all_active_schools(self, request, school_a, school_b, role):
        inactive = EmisSchoolFactory(emis_school_no="KPS900", active=False)
        form = SchoolStaffAssignmentForm(user=request.getfixturevalue(role))
        schools = list(form.fields["school"].queryset)
        assert schools == [school_a, school_b]
        assert inactive not in schools

    def test_school_admin_chooses_only_own_schools(self, school_admin_user, school_a, school_b):
        form = SchoolStaffAssignmentForm(user=school_admin_user)
        assert list(form.fields["school"].queryset) == [school_a]

    def test_school_admin_cannot_submit_other_school(self, school_admin_user, school_b, job_title):
        form = SchoolStaffAssignmentForm(
            self._data(school_b, job_title),
            instance=SchoolStaffAssignment(school_staff=SchoolStaffFactory()),
            user=school_admin_user,
        )
        assert not form.is_valid()
        assert "school" in form.errors

    def test_no_user_offers_no_schools(self, school_a):
        """Safe default: a form built without a user cannot assign any school."""
        form = SchoolStaffAssignmentForm()
        assert not form.fields["school"].queryset.exists()


# ============================================================================
# SchoolStaffEditForm
# ============================================================================


class TestSchoolStaffEditForm:
    @pytest.mark.parametrize("role", ["superuser", "admin_user"])
    def test_full_admins_may_assign_admins_group(self, request, role):
        form = SchoolStaffEditForm(user=request.getfixturevalue(role))
        assert form.can_assign_admins is True
        assert form.can_edit_groups is True
        assert group_names(form) == SCHOOL_GROUPS_ALL
        assert form.fields["groups"].disabled is False

    @pytest.mark.parametrize("role", ["system_admin_user", "school_admin_user"])
    def test_limited_admins_cannot_assign_admins_group(self, request, role):
        form = SchoolStaffEditForm(user=request.getfixturevalue(role))
        assert form.can_assign_admins is False
        assert form.can_edit_groups is True
        assert group_names(form) == SCHOOL_GROUPS_NO_ADMINS
        assert "Only full Admins" in form.fields["groups"].help_text

    @pytest.mark.parametrize("role", ["teacher_user", "school_staff_user", "system_staff_user"])
    def test_others_cannot_edit_groups(self, request, role):
        form = SchoolStaffEditForm(user=request.getfixturevalue(role))
        assert form.can_edit_groups is False
        assert form.fields["groups"].disabled is True

    def test_initial_values_come_from_staff(self, superuser, teacher_user):
        staff = teacher_user.school_staff
        form = SchoolStaffEditForm(user=superuser, school_staff=staff)
        assert form.initial["staff_type"] == staff.staff_type
        assert list(form.initial["groups"].values_list("name", flat=True)) == ["Teachers"]

    def test_initial_groups_hide_admins_from_limited_editor(self, school_admin_user, admin_user):
        form = SchoolStaffEditForm(user=school_admin_user, school_staff=admin_user.school_staff)
        assert list(form.initial["groups"]) == []

    def test_posting_admins_group_as_system_admin_is_rejected(self, system_admin_user, teacher_user):
        admins = Group.objects.get(name="Admins")
        form = SchoolStaffEditForm(
            {"staff_type": "teaching", "groups": [admins.pk]},
            user=system_admin_user,
            school_staff=teacher_user.school_staff,
        )
        assert not form.is_valid()
        assert "groups" in form.errors

    def test_at_least_one_group_required(self, superuser, teacher_user):
        form = SchoolStaffEditForm(
            {"staff_type": "teaching", "groups": []},
            user=superuser,
            school_staff=teacher_user.school_staff,
        )
        assert not form.is_valid()


# ============================================================================
# Student forms
# ============================================================================


class TestStudentCoreForm:
    def test_fields(self):
        assert list(StudentCoreForm().fields) == ["first_name", "last_name", "date_of_birth", "gender"]

    def test_gender_is_optional(self):
        form = StudentCoreForm({"first_name": "A", "last_name": "B", "date_of_birth": "2015-01-01", "gender": ""})
        assert form.is_valid(), form.errors
        assert form.cleaned_data["gender"] is None

    def test_date_required(self):
        form = StudentCoreForm({"first_name": "A", "last_name": "B", "date_of_birth": ""})
        assert not form.is_valid()
        assert "date_of_birth" in form.errors


class TestStudentDisabilityIntakeForm:
    def _base(self, school, year, level, **extra):
        data = {
            "first_name": "Ana",
            "last_name": "Teata",
            "date_of_birth": "2015-03-04",
            "gender": "",
            "school": school.pk,
            "school_year": year.pk,
            "class_level": level.pk,
        }
        data.update(extra)
        return data

    def test_has_one_field_per_cft_question(self):
        form = StudentDisabilityIntakeForm()
        for field_name, code, _label, choices in CFT_QUESTION_META:
            assert field_name in form.fields
            assert form.fields[field_name].label == code
            assert form.fields[field_name].required is False
            assert form.fields[field_name].choices[0] == ("", "— Select —")
            assert form.fields[field_name].choices[1:] == list(choices)

    def test_defaults_school_year_to_latest_code(self, school_year):
        EmisWarehouseYearFactory(code="2023")
        latest = EmisWarehouseYearFactory(code="2027")
        form = StudentDisabilityIntakeForm()
        assert form.initial["school_year"] == latest

    def test_valid_minimal_submission(self, school_a, school_year, class_level):
        form = StudentDisabilityIntakeForm(self._base(school_a, school_year, class_level))
        assert form.is_valid(), form.errors
        assert form.cleaned_data["gender"] is None
        assert form.get_cft_cleaned_data() == {}

    def test_cft_values_are_coerced_to_int_and_blanks_dropped(self, school_a, school_year, class_level):
        form = StudentDisabilityIntakeForm(
            self._base(
                school_a, school_year, class_level,
                cft1_wears_glasses="1", cft3_difficulty_seeing="4", cft19_anxious_frequency="",
            )
        )
        assert form.is_valid(), form.errors
        assert form.get_cft_cleaned_data() == {"cft1_wears_glasses": 1, "cft3_difficulty_seeing": 4}

    def test_out_of_range_cft_value_is_rejected(self, school_a, school_year, class_level):
        form = StudentDisabilityIntakeForm(
            self._base(school_a, school_year, class_level, cft1_wears_glasses="3")
        )
        assert not form.is_valid()
        assert "cft1_wears_glasses" in form.errors

    def test_gender_coerced_to_int(self, school_a, school_year, class_level):
        form = StudentDisabilityIntakeForm(self._base(school_a, school_year, class_level, gender="2"))
        assert form.is_valid(), form.errors
        assert form.cleaned_data["gender"] == 2

    def test_inactive_school_and_level_are_not_offered(self, school_a, school_year, class_level):
        from conftest import EmisClassLevelFactory

        inactive_school = EmisSchoolFactory(emis_school_no="KPS901", active=False)
        inactive_level = EmisClassLevelFactory(code="ZZ", active=False)
        form = StudentDisabilityIntakeForm()
        assert inactive_school not in form.fields["school"].queryset
        assert inactive_level not in form.fields["class_level"].queryset


class TestStudentEnrolmentForm:
    def _data(self, school, year, level, **extra):
        data = {"school": school.pk, "school_year": year.pk, "class_level": level.pk, "start_date": "", "end_date": ""}
        data.update(extra)
        return data

    def test_cft_widgets_get_bootstrap_classes(self):
        form = StudentEnrolmentForm()
        for name, field in form.fields.items():
            if name.startswith("cft"):
                assert "form-select" in field.widget.attrs["class"], name

    def test_duplicate_student_school_year_is_rejected(self, school_a, school_year, class_level):
        existing = StudentSchoolEnrolmentFactory(school=school_a, school_year=school_year, class_level=class_level)
        form = StudentEnrolmentForm(
            self._data(school_a, school_year, class_level),
            instance=StudentSchoolEnrolment(student=existing.student),
        )
        assert not form.is_valid()
        assert "already has an enrolment" in form.errors["school"][0]

    def test_editing_existing_enrolment_is_not_a_duplicate_of_itself(self, school_a, school_year, class_level):
        existing = StudentSchoolEnrolmentFactory(school=school_a, school_year=school_year, class_level=class_level)
        form = StudentEnrolmentForm(
            self._data(school_a, school_year, class_level, cft1_wears_glasses="2"), instance=existing
        )
        assert form.is_valid(), form.errors

    def test_other_year_is_allowed(self, school_a, school_year, class_level):
        existing = StudentSchoolEnrolmentFactory(school=school_a, school_year=school_year, class_level=class_level)
        other = EmisWarehouseYearFactory(code="2026")
        form = StudentEnrolmentForm(
            self._data(school_a, other, class_level),
            instance=StudentSchoolEnrolment(student=existing.student),
        )
        assert form.is_valid(), form.errors

    def test_other_student_is_allowed(self, school_a, school_year, class_level):
        StudentSchoolEnrolmentFactory(school=school_a, school_year=school_year, class_level=class_level)
        form = StudentEnrolmentForm(
            self._data(school_a, school_year, class_level),
            instance=StudentSchoolEnrolment(student=StudentFactory()),
        )
        assert form.is_valid(), form.errors


# ============================================================================
# Pending-user assignment forms and SystemUserEditForm
# ============================================================================


class TestAssignForms:
    @pytest.mark.parametrize("role", ["superuser", "admin_user"])
    def test_full_admins_see_admins_group(self, request, role):
        user = request.getfixturevalue(role)
        assert group_names(AssignSchoolStaffForm(user=user)) == SCHOOL_GROUPS_ALL
        assert group_names(AssignSystemUserForm(user=user)) == SYSTEM_GROUPS_ALL

    def test_system_admin_does_not_see_admins_group(self, system_admin_user):
        assert group_names(AssignSchoolStaffForm(user=system_admin_user)) == SCHOOL_GROUPS_NO_ADMINS
        assert group_names(AssignSystemUserForm(user=system_admin_user)) == SYSTEM_GROUPS_NO_ADMINS

    def test_no_user_means_no_admins_group(self):
        assert group_names(AssignSchoolStaffForm()) == SCHOOL_GROUPS_NO_ADMINS
        assert group_names(AssignSystemUserForm()) == SYSTEM_GROUPS_NO_ADMINS

    def test_system_admin_posting_admins_group_is_invalid(self, system_admin_user):
        admins = Group.objects.get(name="Admins")
        form = AssignSystemUserForm({"groups": [admins.pk]}, user=system_admin_user)
        assert not form.is_valid()
        form = AssignSchoolStaffForm({"staff_type": "teaching", "groups": [admins.pk]}, user=system_admin_user)
        assert not form.is_valid()

    def test_assign_school_staff_defaults_to_non_teaching(self):
        assert AssignSchoolStaffForm().fields["staff_type"].initial == "non_teaching"

    def test_organization_fields_optional(self, superuser):
        staff_group = Group.objects.get(name="System Staff")
        form = AssignSystemUserForm({"groups": [staff_group.pk]}, user=superuser)
        assert form.is_valid(), form.errors
        assert form.cleaned_data["organization"] == ""


class TestSystemUserEditForm:
    @pytest.mark.parametrize("role", ["superuser", "admin_user"])
    def test_full_admins(self, request, role):
        form = SystemUserEditForm(user=request.getfixturevalue(role))
        assert form.can_assign_admins and form.can_edit_groups
        assert group_names(form) == SYSTEM_GROUPS_ALL

    def test_system_admin(self, system_admin_user):
        form = SystemUserEditForm(user=system_admin_user)
        assert form.can_edit_groups is True
        assert form.can_assign_admins is False
        assert group_names(form) == SYSTEM_GROUPS_NO_ADMINS

    @pytest.mark.parametrize("role", ["system_staff_user", "school_admin_user"])
    def test_read_only_roles_have_groups_disabled(self, request, role):
        form = SystemUserEditForm(user=request.getfixturevalue(role))
        assert form.can_edit_groups is False
        assert form.fields["groups"].disabled is True

    def test_initial_values(self, superuser):
        su = SystemUserFactory(organization="MOE", position_title="Analyst")
        su.user.groups.add(Group.objects.get(name="System Staff"))
        form = SystemUserEditForm(user=superuser, system_user=su)
        assert form.initial["organization"] == "MOE"
        assert form.initial["position_title"] == "Analyst"
        assert list(form.initial["groups"].values_list("name", flat=True)) == ["System Staff"]


class TestTestEmailForm:
    def test_requires_valid_email(self):
        assert not EmailRecipientForm({"recipient": "not-an-email"}).is_valid()
        assert EmailRecipientForm({"recipient": "someone@example.org"}).is_valid()
