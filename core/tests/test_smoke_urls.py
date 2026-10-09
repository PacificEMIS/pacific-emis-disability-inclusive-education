"""
Smoke tests: every named URL in the app responds the way its access layer
promises, for three baseline identities.

- superuser: every page renders (200), except endpoints that only accept POST.
- anonymous: every protected page redirects to the login page.
- pending user (authenticated, no profile/group): the app-access middleware
  redirects every app page to the no-permissions page.

A meta-test asserts the URL inventory below covers every name in
core.urls, so adding a view without a smoke entry fails the suite.

Detailed per-role authorisation lives in test_views_*.py; this file is the
tripwire for template errors, broken reverses and missing @login_required.
"""

import pytest
from django.urls import reverse

from core import urls as core_urls
from conftest import (
    SchoolStaffAssignmentFactory,
    StudentSchoolEnrolmentFactory,
    SystemUserFactory,
    UserFactory,
)


@pytest.fixture
def smoke_objects(db, school_a, school_year, class_level, job_title):
    """One of every object the detail/edit URLs need a primary key for."""
    assignment = SchoolStaffAssignmentFactory(school=school_a, job_title=job_title)
    enrolment = StudentSchoolEnrolmentFactory(
        school=school_a, school_year=school_year, class_level=class_level
    )
    return {
        "staff": assignment.school_staff,
        "assignment": assignment,
        "system_user": SystemUserFactory(),
        "student": enrolment.student,
        "enrolment": enrolment,
        "pending": UserFactory(username="someone-pending"),
        "school": school_a,
    }


# (url name, kwargs builder, expected status for a superuser GET)
CORE_URLS = [
    ("dashboard", lambda o: {}, 200),
    ("staff_list", lambda o: {}, 200),
    ("staff_detail", lambda o: {"pk": o["staff"].pk}, 200),
    ("staff_edit", lambda o: {"pk": o["staff"].pk}, 200),
    (
        "staff_assignment_edit",
        lambda o: {"staff_id": o["staff"].pk, "pk": o["assignment"].pk},
        200,
    ),
    (
        "staff_assignment_delete",
        lambda o: {"staff_id": o["staff"].pk, "pk": o["assignment"].pk},
        200,
    ),
    ("system_user_list", lambda o: {}, 200),
    ("system_user_detail", lambda o: {"pk": o["system_user"].pk}, 200),
    ("system_user_edit", lambda o: {"pk": o["system_user"].pk}, 200),
    ("student_list", lambda o: {}, 200),
    ("student_new", lambda o: {}, 200),
    ("student_matches", lambda o: {}, 200),
    ("student_detail", lambda o: {"pk": o["student"].pk}, 200),
    ("student_edit", lambda o: {"pk": o["student"].pk}, 200),
    ("student_enrolment_add", lambda o: {"student_pk": o["student"].pk}, 200),
    (
        "student_enrolment_edit",
        lambda o: {"student_pk": o["student"].pk, "enrolment_pk": o["enrolment"].pk},
        200,
    ),
    (
        "student_enrolment_delete",
        lambda o: {"student_pk": o["student"].pk, "enrolment_pk": o["enrolment"].pk},
        200,
    ),
    ("pending_users_list", lambda o: {}, 200),
    ("assign_school_staff", lambda o: {"user_id": o["pending"].pk}, 200),
    ("assign_system_user", lambda o: {"user_id": o["pending"].pk}, 200),
    ("delete_pending_user", lambda o: {"user_id": o["pending"].pk}, 200),
    ("settings", lambda o: {}, 200),
    ("sync_emis_lookups", lambda o: {}, 302),  # POST-only; GET redirects
    ("settings_lookup_list", lambda o: {"slug": "schools"}, 200),
    (
        "settings_lookup_update",
        lambda o: {"slug": "schools", "pk": o["school"].pk},
        405,  # POST-only JSON endpoint
    ),
    ("test_email", lambda o: {}, 200),
]

CORE_URL_IDS = [name for name, _, _ in CORE_URLS]


def test_inventory_covers_every_core_url_name():
    declared = {p.name for p in core_urls.urlpatterns}
    covered = set(CORE_URL_IDS)
    missing = declared - covered
    assert not missing, f"Add these URL names to CORE_URLS: {sorted(missing)}"
    unknown = covered - declared
    assert not unknown, f"CORE_URLS lists names that no longer exist: {sorted(unknown)}"


@pytest.mark.parametrize("name,kwargs_for,expected", CORE_URLS, ids=CORE_URL_IDS)
def test_superuser_get(client_for, superuser, smoke_objects, name, kwargs_for, expected):
    url = reverse(f"core:{name}", kwargs=kwargs_for(smoke_objects))
    response = client_for(superuser).get(url)
    assert response.status_code == expected, url


@pytest.mark.parametrize("name,kwargs_for,_", CORE_URLS, ids=CORE_URL_IDS)
def test_anonymous_is_redirected_to_login(client, smoke_objects, name, kwargs_for, _):
    url = reverse(f"core:{name}", kwargs=kwargs_for(smoke_objects))
    response = client.get(url)
    assert response.status_code == 302, url
    assert response["Location"].startswith(reverse("account_login")), url


@pytest.mark.parametrize("name,kwargs_for,_", CORE_URLS, ids=CORE_URL_IDS)
def test_user_without_profile_is_redirected_to_no_permissions(
    client_for, pending_user, smoke_objects, name, kwargs_for, _
):
    url = reverse(f"core:{name}", kwargs=kwargs_for(smoke_objects))
    response = client_for(pending_user).get(url)
    assert response.status_code == 302, url
    assert response["Location"] == reverse("accounts:no_permissions"), url


@pytest.mark.parametrize("name,kwargs_for,_", CORE_URLS, ids=CORE_URL_IDS)
def test_user_with_profile_but_no_group_is_redirected_to_no_permissions(
    client_for, profile_only_user, smoke_objects, name, kwargs_for, _
):
    url = reverse(f"core:{name}", kwargs=kwargs_for(smoke_objects))
    response = client_for(profile_only_user).get(url)
    assert response.status_code == 302, url
    assert response["Location"] == reverse("accounts:no_permissions"), url


def test_dashboard_renders_for_every_app_role(client_for, any_app_user):
    """Every role allowed into the app must at least reach the dashboard."""
    response = client_for(any_app_user).get(reverse("core:dashboard"))
    assert response.status_code == 200


def test_admin_site_loads_for_superuser(client_for, superuser):
    response = client_for(superuser).get("/admin/")
    assert response.status_code == 200
