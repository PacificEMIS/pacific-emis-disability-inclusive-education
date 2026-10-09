"""
Tests for the username/password sign-in view and the custom 403 handler.
"""

import pytest
from django.contrib.messages import get_messages
from django.urls import reverse

from conftest import TEST_PASSWORD

pytestmark = pytest.mark.django_db
LOGIN = reverse("accounts:login")


def test_successful_login_redirects_to_dashboard(client, teacher_user):
    response = client.post(LOGIN, {"username": teacher_user.username, "password": TEST_PASSWORD})
    assert response.status_code == 302
    assert response["Location"] == reverse("core:dashboard")
    assert client.get(reverse("core:dashboard")).status_code == 200


def test_next_parameter_is_honoured(client, teacher_user):
    target = reverse("core:student_list")
    response = client.post(LOGIN, {"username": teacher_user.username, "password": TEST_PASSWORD, "next": target})
    assert response["Location"] == target


def test_next_from_query_string(client, teacher_user):
    target = reverse("core:staff_list")
    response = client.post(f"{LOGIN}?next={target}", {"username": teacher_user.username, "password": TEST_PASSWORD})
    assert response["Location"] == target


def test_bad_password_shows_error(client, teacher_user):
    response = client.post(LOGIN, {"username": teacher_user.username, "password": "wrong"})
    assert response.status_code == 200
    assert "Invalid username or password." in [str(m) for m in get_messages(response.wsgi_request)]
    assert client.get(reverse("core:dashboard")).status_code == 302


def test_inactive_user_cannot_login(client, teacher_user):
    teacher_user.is_active = False
    teacher_user.save()
    response = client.post(LOGIN, {"username": teacher_user.username, "password": TEST_PASSWORD})
    assert response.status_code == 200


def test_login_page_keeps_next_in_context(client, db):
    response = client.get(LOGIN, {"next": "/students/"})
    assert response.context["next"] == "/students/"


def test_login_with_email_via_allauth_backend(client, teacher_user):
    """ACCOUNT_LOGIN_METHODS includes email; allauth's backend accepts it."""
    response = client.post(LOGIN, {"username": teacher_user.email, "password": TEST_PASSWORD})
    assert response.status_code == 302


def test_forbidden_page_uses_custom_template(client_for, teacher_user):
    response = client_for(teacher_user).get(reverse("core:pending_users_list"))
    assert response.status_code == 403
    assert "accounts/forbidden.html" in [t.name for t in response.templates]
