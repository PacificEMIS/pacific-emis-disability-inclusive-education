"""
Unit tests for small pure helpers: template filters, context processors,
CFT question metadata and the private view helpers (pagination windows,
fuzzy name scoring, permission summarising).
"""

import pytest
from django.contrib.auth.models import Group, Permission
from django.core.paginator import Paginator
from django.test import RequestFactory
from django.urls import reverse

from conftest import SchoolStaffFactory, SystemUserFactory, UserFactory
from core import views
from core.cft_meta import CFT_QUESTION_META, build_cft_meta_for_name
from core.context_processors import staff_context
from core.models import DIFFICULTY_CHOICES_4, EMOTIONAL_FREQ_CHOICES_5, YES_NO_CHOICES
from core.templatetags import cft_display, core_perms, dict_extras, form_extras
from pacemis_inclusive_ed.context_processors import app_name, emis_context, terminology


# ============================================================================
# CFT metadata
# ============================================================================


class TestCftMeta:
    def test_twenty_questions_in_order(self):
        assert len(CFT_QUESTION_META) == 20
        codes = [code for _, code, _, _ in CFT_QUESTION_META]
        assert codes == [f"CFT{i}" for i in range(1, 21)]

    def test_field_names_match_model(self):
        from core.models import StudentSchoolEnrolment

        model_fields = {f.name for f in StudentSchoolEnrolment._meta.fields}
        for field_name, _, _, _ in CFT_QUESTION_META:
            assert field_name in model_fields

    def test_choice_sets_match_question_type(self):
        by_code = {code: choices for _, code, _, choices in CFT_QUESTION_META}
        assert by_code["CFT1"] == by_code["CFT4"] == by_code["CFT7"] == YES_NO_CHOICES
        assert by_code["CFT19"] == by_code["CFT20"] == EMOTIONAL_FREQ_CHOICES_5
        for i in (2, 3, 5, 6, 8, 9, 10, 11, 12, 13, 14, 15, 16, 17, 18):
            assert by_code[f"CFT{i}"] == DIFFICULTY_CHOICES_4, i

    def test_every_label_has_name_placeholder(self):
        for _, code, label, _ in CFT_QUESTION_META:
            assert "%(name)s" in str(label), code

    def test_build_cft_meta_substitutes_name(self):
        meta = build_cft_meta_for_name("Ana Teata")
        assert len(meta) == 20
        for _, _, label, _ in meta:
            assert "Ana Teata" in str(label)
            assert "%(name)s" not in str(label)

    def test_build_cft_meta_falls_back_to_the_child(self):
        for empty in (None, ""):
            meta = build_cft_meta_for_name(empty)
            assert "the child" in str(meta[0][2])


# ============================================================================
# Template filters
# ============================================================================


class TestCftDisplayFilters:
    @pytest.mark.parametrize(
        "fn,value,fragment",
        [
            (cft_display.cft_difficulty_badge, None, "Not recorded"),
            (cft_display.cft_difficulty_badge, 1, "No difficulty"),
            (cft_display.cft_difficulty_badge, 4, "Cannot do at all"),
            (cft_display.cft_difficulty_badge, 99, ""),
            (cft_display.cft_yesno_badge, None, "Not recorded"),
            (cft_display.cft_yesno_badge, 1, "Yes"),
            (cft_display.cft_yesno_badge, 2, "No"),
            (cft_display.cft_yesno_badge, 3, ""),
            (cft_display.cft_emotional_badge, None, "Not recorded"),
            (cft_display.cft_emotional_badge, 1, "Daily"),
            (cft_display.cft_emotional_badge, 5, "Never"),
            (cft_display.cft_emotional_badge, 6, ""),
        ],
    )
    def test_badges(self, fn, value, fragment):
        out = fn(value)
        if fragment:
            assert fragment in out
        else:
            assert out == ""

    def test_badges_cover_every_choice(self):
        for value, _ in DIFFICULTY_CHOICES_4:
            assert cft_display.cft_difficulty_badge(value)
        for value, _ in YES_NO_CHOICES:
            assert cft_display.cft_yesno_badge(value)
        for value, _ in EMOTIONAL_FREQ_CHOICES_5:
            assert cft_display.cft_emotional_badge(value)


class TestDictAndFormExtras:
    def test_get_item(self):
        assert dict_extras.get_item({"a": 1}, "a") == 1
        assert dict_extras.get_item({"a": 1}, "b") is None
        assert dict_extras.get_item(None, "a") is None

    def test_getfield(self):
        class Obj:
            x = 5

        assert dict_extras.getfield(Obj(), "x") == 5
        assert dict_extras.getfield(Obj(), "missing") == ""

    def test_form_field(self):
        from core.forms import TestEmailForm as EmailRecipientForm

        form = EmailRecipientForm()
        assert form_extras.form_field(form, "recipient").name == "recipient"
        assert form_extras.form_field(form, "nope") is None


@pytest.mark.django_db
class TestCorePermsFilters:
    def test_filters_delegate_to_permissions(self, superuser, school_staff_user):
        from conftest import StudentFactory

        student = StudentFactory()
        assert core_perms.can_create_student_filter(superuser) is True
        assert core_perms.can_create_student_filter(school_staff_user) is False
        assert core_perms.can_edit_student_filter(superuser, student) is True
        assert core_perms.can_delete_student_filter(superuser, student) is True

    def test_none_arguments_are_safe(self, superuser):
        assert core_perms.can_edit_student_filter(None, None) is False
        assert core_perms.can_edit_student_filter(superuser, None) is False
        assert core_perms.can_delete_student_filter(None, None) is False


# ============================================================================
# Context processors
# ============================================================================


def _request(user):
    request = RequestFactory().get("/")
    request.user = user
    return request


@pytest.mark.django_db
class TestStaffContext:
    def test_anonymous(self):
        from django.contrib.auth.models import AnonymousUser

        ctx = staff_context(_request(AnonymousUser()))
        assert ctx == {
            "staff_pk_for_request_user": None,
            "system_user_pk_for_request_user": None,
            "user_profile_url": None,
            "is_admin_user": False,
            "can_manage_pending_users": False,
            "is_system_level_user": False,
        }

    def test_school_staff_profile(self, teacher_user):
        ctx = staff_context(_request(teacher_user))
        staff = teacher_user.school_staff
        assert ctx["staff_pk_for_request_user"] == staff.pk
        assert ctx["user_profile_url"] == reverse("core:staff_detail", kwargs={"pk": staff.pk})
        assert ctx["is_admin_user"] is False
        assert ctx["is_system_level_user"] is False

    def test_system_user_profile(self, system_admin_user):
        ctx = staff_context(_request(system_admin_user))
        su = system_admin_user.system_user
        assert ctx["system_user_pk_for_request_user"] == su.pk
        assert ctx["user_profile_url"] == reverse("core:system_user_detail", kwargs={"pk": su.pk})
        assert ctx["is_admin_user"] is True
        assert ctx["can_manage_pending_users"] is True
        assert ctx["is_system_level_user"] is True

    def test_superuser_without_profile_links_to_admin(self, superuser):
        ctx = staff_context(_request(superuser))
        assert ctx["user_profile_url"] == reverse("admin:auth_user_change", args=[superuser.pk])

    def test_pending_user_has_no_profile_url(self, pending_user):
        assert staff_context(_request(pending_user))["user_profile_url"] is None


class TestProjectContextProcessors:
    def test_emis_context_and_logo(self, settings):
        settings.EMIS = {**settings.EMIS, "CONTEXT": "KEMIS (Dev)"}
        ctx = emis_context(None)
        assert ctx == {"emis_context": "KEMIS (Dev)", "emis_logo": "kemis"}

    def test_emis_context_empty(self, settings):
        settings.EMIS = {**settings.EMIS, "CONTEXT": ""}
        assert emis_context(None) == {"emis_context": None, "emis_logo": "logo"}

    def test_app_name(self, settings):
        settings.APP_NAME = "My App"
        assert app_name(None) == {"app_name": "My App"}

    def test_terminology_defaults_and_overrides(self, settings):
        settings.TERMINOLOGY = {}
        assert terminology(None)["terminology"] == {
            "system_users_singular": "System User",
            "system_users_plural": "System Users",
        }
        settings.TERMINOLOGY = {"SYSTEM_USERS_SINGULAR": "MOE Staff", "SYSTEM_USERS_PLURAL": "MOE Staff"}
        assert terminology(None)["terminology"]["system_users_plural"] == "MOE Staff"


# ============================================================================
# Private view helpers
# ============================================================================


def _page(total_items, per_page, number):
    return Paginator(list(range(total_items)), per_page).get_page(number)


class TestPaginationWindows:
    def test_page_window_small(self):
        assert views._page_window(_page(30, 10, 2)) == [1, 2, 3]

    def test_page_window_with_gaps(self):
        assert views._page_window(_page(300, 10, 10)) == [1, 2, "…", 8, 9, 10, 11, 12, "…", 29, 30]

    def test_page_window_at_edges(self):
        assert views._page_window(_page(300, 10, 1)) == [1, 2, 3, "…", 29, 30]
        assert views._page_window(_page(300, 10, 30)) == [1, 2, "…", 28, 29, 30]

    def test_page_links_short_returns_all(self):
        assert views._page_links(_page(70, 10, 3)) == [1, 2, 3, 4, 5, 6, 7]

    def test_page_links_with_gaps(self):
        assert views._page_links(_page(200, 10, 10)) == [1, "…", 9, 10, 11, "…", 20]

    def test_page_links_near_start(self):
        assert views._page_links(_page(200, 10, 1)) == [1, 2, "…", 20]


class TestNameSimilarity:
    def test_identical_is_one(self):
        assert views._name_similarity("Teata", "Teata") == 1.0

    def test_prefix_is_strong(self):
        assert views._name_similarity("Jon", "Jonathan") >= 0.9

    def test_empty_is_zero(self):
        assert views._name_similarity("", "Teata") == 0.0
        assert views._name_similarity("Teata", None) == 0.0

    def test_unrelated_is_low(self):
        assert views._name_similarity("Teata", "Mwemwe") < 0.8


@pytest.mark.django_db
class TestSummarizePermissions:
    def test_buckets_by_action_and_special_access(self):
        perms = Permission.objects.filter(
            codename__in=["view_student", "add_student", "change_schoolstaff", "delete_systemuser", "access_app"]
        )
        sections = views._summarize_permissions(perms)
        by_key = {s["key"]: s["models"] for s in sections}
        assert by_key["view"] == ["Student"]
        assert by_key["add"] == ["Student"]
        assert by_key["change"] == ["School Staff"]
        assert by_key["delete"] == ["System User"]
        assert by_key["access"] == ["Disability-Inclusive Education app"]
        assert [s["key"] for s in sections] == ["view", "add", "change", "delete", "access"]

    def test_empty_queryset_gives_no_sections(self):
        assert views._summarize_permissions(Permission.objects.none()) == []

    def test_seeded_groups_have_access_app(self):
        """Every seeded group must grant core.access_app or logins bounce."""
        for name in ["Admins", "School Admins", "School Staff", "Teachers", "System Admins", "System Staff"]:
            group = Group.objects.get(name=name)
            assert group.permissions.filter(codename="access_app").exists(), name
