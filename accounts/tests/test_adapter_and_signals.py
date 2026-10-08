"""
Unit tests for the allauth account adapter (signup domain restriction) and
the signup signal that notifies admins about a new pending user.
"""

import pytest
from allauth.account.signals import user_signed_up
from django.contrib.auth import get_user_model
from django.core import mail
from django.core.exceptions import PermissionDenied
from django.test import RequestFactory
from django.urls import reverse

from accounts.account_adapter import DomainRestrictedAdapter
from conftest import UserFactory

User = get_user_model()
pytestmark = pytest.mark.django_db


class _StubForm:
    """Minimal stand-in for the allauth signup form the adapter reads."""

    def __init__(self, email, username):
        self.cleaned_data = {
            "email": email,
            "username": username,
            "first_name": "",
            "last_name": "",
            "password1": "x",
        }


class TestDomainRestrictedAdapter:
    def _save(self, settings, email, allowed):
        if allowed is None:
            if hasattr(settings, "ALLOWED_SIGNUP_DOMAINS"):
                delattr(settings, "ALLOWED_SIGNUP_DOMAINS")
        else:
            settings.ALLOWED_SIGNUP_DOMAINS = allowed
        adapter = DomainRestrictedAdapter()
        request = RequestFactory().get("/")
        return adapter.save_user(request, User(), _StubForm(email, "newbie"), commit=True)

    def test_open_for_signup(self):
        assert DomainRestrictedAdapter().is_open_for_signup(RequestFactory().get("/")) is True

    def test_no_restriction_saves_any_domain(self, settings):
        user = self._save(settings, "anyone@elsewhere.org", None)
        assert user.pk and user.email == "anyone@elsewhere.org"

    def test_allowed_domain_saves_case_insensitively(self, settings):
        user = self._save(settings, "Teacher@MOE.GOV.KI", ["moe.gov.ki"])
        assert user.pk

    def test_disallowed_domain_raises_and_does_not_save(self, settings):
        with pytest.raises(PermissionDenied):
            self._save(settings, "spy@elsewhere.org", ["moe.gov.ki"])
        assert not User.objects.filter(username="newbie").exists()

    def test_suffix_must_be_a_whole_domain(self, settings):
        with pytest.raises(PermissionDenied):
            self._save(settings, "x@notmoe.gov.ki", ["moe.gov.ki"])


class TestSignupSignal:
    def test_signup_notifies_pending_user_managers(
        self, sync_email_threads, admin_user, system_admin_user, teacher_user
    ):
        new_user = UserFactory(username="newbie", email="newbie@example.org")
        request = RequestFactory().get("/")
        user_signed_up.send(sender=User, request=request, user=new_user)

        assert len(mail.outbox) == 1
        msg = mail.outbox[0]
        assert set(msg.to) == {admin_user.email, system_admin_user.email}
        assert teacher_user.email not in msg.to
        assert "awaiting role assignment" in msg.subject
        assert reverse("core:pending_users_list") in msg.body
        assert msg.alternatives and msg.alternatives[0][1] == "text/html"

    def test_signup_without_request_still_sends(self, sync_email_threads, admin_user):
        user_signed_up.send(sender=User, request=None, user=UserFactory(username="newbie2"))
        assert len(mail.outbox) == 1

    def test_signup_with_no_managers_sends_nothing(self, sync_email_threads, teacher_user):
        user_signed_up.send(sender=User, request=None, user=UserFactory(username="newbie3"))
        assert mail.outbox == []

    def test_inactive_or_emailless_managers_are_skipped(
        self, sync_email_threads, admin_user, make_system_user
    ):
        make_system_user("System Admins", username="gone", is_active=False)
        make_system_user("System Admins", username="noemail", email="")
        user_signed_up.send(sender=User, request=None, user=UserFactory(username="newbie4"))
        assert mail.outbox[0].to == [admin_user.email]
