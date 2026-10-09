"""
Smoke tests for the accounts URLs: login page, logout, the post-login
router and the no-permissions page.
"""

import pytest
from django.urls import reverse


def test_login_page_renders_for_anonymous(client, db):
    response = client.get(reverse("accounts:login"))
    assert response.status_code == 200


def test_login_page_redirects_authenticated_user_to_dashboard(client_for, superuser):
    response = client_for(superuser).get(reverse("accounts:login"))
    assert response.status_code == 302
    assert response["Location"] == reverse("core:dashboard")


def test_no_permissions_page_requires_login(client, db):
    response = client.get(reverse("accounts:no_permissions"))
    assert response.status_code == 302
    assert response["Location"].startswith(reverse("account_login"))


def test_no_permissions_page_renders_for_pending_user(client_for, pending_user):
    response = client_for(pending_user).get(reverse("accounts:no_permissions"))
    assert response.status_code == 200


def test_post_login_router_sends_app_user_to_dashboard(client_for, any_app_user):
    response = client_for(any_app_user).get(reverse("accounts:post_login_router"))
    assert response.status_code == 302
    assert response["Location"] == reverse("core:dashboard")


@pytest.mark.parametrize("fixture_name", ["pending_user", "profile_only_user"])
def test_post_login_router_sends_locked_out_user_to_no_permissions(
    request, client_for, fixture_name
):
    user = request.getfixturevalue(fixture_name)
    response = client_for(user).get(reverse("accounts:post_login_router"))
    assert response.status_code == 302
    assert response["Location"] == reverse("accounts:no_permissions")


def test_logout_ends_session(client_for, superuser):
    client = client_for(superuser)
    response = client.get(reverse("accounts:logout"))
    assert response.status_code == 302
    assert response["Location"] == reverse("accounts:login")
    # Session is gone: a protected page now bounces to login.
    follow_up = client.get(reverse("core:dashboard"))
    assert follow_up.status_code == 302
    assert follow_up["Location"].startswith(reverse("account_login"))
