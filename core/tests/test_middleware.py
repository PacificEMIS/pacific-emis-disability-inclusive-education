"""
Unit tests for core.middleware.AppAccessMiddleware: exempt paths, the
redirect for locked-out users, and the no-redirect-loop guard.
"""

import pytest
from django.contrib.auth.models import AnonymousUser
from django.http import HttpResponse
from django.test import RequestFactory
from django.urls import reverse

from core.middleware import AppAccessMiddleware

pytestmark = pytest.mark.django_db


def run(user, path):
    calls = []

    def get_response(request):
        calls.append(request)
        return HttpResponse("ok")

    request = RequestFactory().get(path)
    request.user = user
    response = AppAccessMiddleware(get_response)(request)
    return response, bool(calls)


def test_anonymous_passes_through(db):
    response, reached_view = run(AnonymousUser(), "/students/")
    assert reached_view and response.status_code == 200


def test_app_user_passes_through(teacher_user):
    response, reached_view = run(teacher_user, "/students/")
    assert reached_view and response.status_code == 200


@pytest.mark.parametrize("fixture_name", ["pending_user", "profile_only_user"])
def test_locked_out_user_is_redirected(request, fixture_name):
    user = request.getfixturevalue(fixture_name)
    response, reached_view = run(user, "/students/")
    assert not reached_view
    assert response.status_code == 302
    assert response["Location"] == reverse("accounts:no_permissions")


@pytest.mark.parametrize(
    "path", ["/accounts/anything/", "/admin/", "/static/x.css", "/media/x.png", "/__debug__/"]
)
def test_exempt_prefixes_bypass_check(pending_user, path):
    response, reached_view = run(pending_user, path)
    assert reached_view and response.status_code == 200


def test_no_redirect_loop_on_no_permissions_page(pending_user):
    response, reached_view = run(pending_user, reverse("accounts:no_permissions"))
    assert reached_view and response.status_code == 200


def test_middleware_is_installed_after_authentication(settings):
    mw = settings.MIDDLEWARE
    assert "core.middleware.AppAccessMiddleware" in mw
    assert mw.index("core.middleware.AppAccessMiddleware") > mw.index(
        "django.contrib.auth.middleware.AuthenticationMiddleware"
    )
