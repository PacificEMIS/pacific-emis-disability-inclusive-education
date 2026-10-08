"""
View tests for the admin Settings pages (EMIS lookup sync and review) and
the Utilities test-email page.
"""

import pytest
from django.contrib.messages import get_messages
from django.core import mail
from django.core.cache import cache
from django.urls import reverse

from conftest import EmisClassLevelFactory, EmisSchoolFactory
from integrations.emis_client import EmisClient
from integrations.management.commands.emis_sync_lookups import LAST_SYNC_CACHE_KEY
from integrations.models import EmisClassLevel, EmisSchool

pytestmark = pytest.mark.django_db

MANAGERS = ["superuser", "admin_user", "system_admin_user"]
NON_MANAGERS = ["system_staff_user", "school_admin_user", "teacher_user", "school_staff_user"]


def messages_of(response):
    return [str(m) for m in get_messages(response.wsgi_request)]


@pytest.fixture(autouse=True)
def clear_cache():
    cache.clear()
    yield
    cache.clear()


@pytest.fixture
def lookup_payload(monkeypatch):
    payload = {
        "schoolCodes": [{"C": "KPS001", "N": "Alpha Primary (renamed)"}, {"C": "KPS777", "N": "New School"}],
        "levels": [{"C": "P1", "N": "Primary 1"}],
        "teacherRoles": [{"C": "T", "N": "Teacher"}],
        "warehouseYears": [{"C": "2025", "FormattedYear": "SY2025"}],
    }
    monkeypatch.setattr(EmisClient, "get_core_lookups", lambda self: payload)
    return payload


class TestAdminSettings:
    url = reverse("core:settings")

    @pytest.mark.parametrize("role", MANAGERS)
    def test_managers_see_counts(self, request, client_for, school_a, class_level, role):
        ctx = client_for(request.getfixturevalue(role)).get(self.url).context
        by_slug = {c["slug"]: c["count"] for c in ctx["lookup_categories"]}
        assert set(by_slug) == {"schools", "class-levels", "job-titles", "school-years"}
        assert by_slug["schools"] == 1 and by_slug["class-levels"] == 1 and by_slug["school-years"] == 0
        assert ctx["last_sync"] is None
        assert ctx["emis_base_url"].startswith("http://emis.invalid")

    @pytest.mark.parametrize("role", NON_MANAGERS)
    def test_others_forbidden(self, request, client_for, role):
        assert client_for(request.getfixturevalue(role)).get(self.url).status_code == 403

    def test_last_sync_shown_after_sync(self, client_for, superuser, lookup_payload):
        client = client_for(superuser)
        client.post(reverse("core:sync_emis_lookups"))
        assert client.get(self.url).context["last_sync"]["message"].startswith("Schools")


class TestSyncEmisLookups:
    url = reverse("core:sync_emis_lookups")

    def test_get_redirects(self, client_for, superuser):
        response = client_for(superuser).get(self.url)
        assert response.status_code == 302 and response["Location"] == reverse("core:settings")

    @pytest.mark.parametrize("role", NON_MANAGERS)
    def test_others_forbidden(self, request, client_for, role):
        assert client_for(request.getfixturevalue(role)).post(self.url).status_code == 403

    def test_post_syncs_and_reports(self, client_for, system_admin_user, school_a, lookup_payload):
        response = client_for(system_admin_user).post(self.url)
        assert response.status_code == 302
        assert any(m.startswith("Schools +1/1") for m in messages_of(response))
        school_a.refresh_from_db()
        assert school_a.emis_school_name == "Alpha Primary (renamed)"
        assert EmisSchool.objects.filter(pk="KPS777").exists()
        assert cache.get(LAST_SYNC_CACHE_KEY)["message"].startswith("Schools")

    def test_ajax_post_returns_json(self, client_for, superuser, lookup_payload):
        response = client_for(superuser).post(self.url, HTTP_X_REQUESTED_WITH="XMLHttpRequest")
        assert response.status_code == 200
        body = response.json()
        assert body["ok"] is True and body["message"].startswith("Schools")

    def test_failure_is_reported_not_raised(self, client_for, superuser, monkeypatch):
        def boom(self):
            raise RuntimeError("EMIS down")

        monkeypatch.setattr(EmisClient, "get_core_lookups", boom)
        response = client_for(superuser).post(self.url, HTTP_X_REQUESTED_WITH="XMLHttpRequest")
        assert response.status_code == 200
        body = response.json()
        assert body["ok"] is False and "EMIS down" in body["message"]

        response = client_for(superuser).post(self.url)
        assert response.status_code == 302
        assert any("Sync failed" in m for m in messages_of(response))

    def test_real_http_is_blocked_by_the_test_harness(self, client_for, superuser):
        """Without a mock the sync must fail loudly, never reach the network."""
        response = client_for(superuser).post(self.url, HTTP_X_REQUESTED_WITH="XMLHttpRequest")
        assert response.json()["ok"] is False
        assert "Outbound HTTP blocked" in response.json()["message"]


class TestSettingsLookupList:
    def url(self, slug):
        return reverse("core:settings_lookup_list", kwargs={"slug": slug})

    @pytest.mark.parametrize("slug,model", [("schools", EmisSchool), ("class-levels", EmisClassLevel)])
    def test_lists_items(self, client_for, superuser, school_a, class_level, slug, model):
        ctx = client_for(superuser).get(self.url(slug)).context
        assert ctx["slug"] == slug
        assert list(ctx["items"]) == list(model.objects.all())

    def test_unknown_slug_404(self, client_for, superuser):
        assert client_for(superuser).get(self.url("nope")).status_code == 404

    def test_forbidden(self, client_for, teacher_user):
        assert client_for(teacher_user).get(self.url("schools")).status_code == 403


class TestSettingsLookupUpdate:
    def url(self, slug, pk):
        return reverse("core:settings_lookup_update", kwargs={"slug": slug, "pk": pk})

    def test_get_not_allowed(self, client_for, superuser, school_a):
        response = client_for(superuser).get(self.url("schools", school_a.pk))
        assert response.status_code == 405 and response.json()["ok"] is False

    def test_forbidden(self, client_for, school_admin_user, school_a):
        assert client_for(school_admin_user).post(self.url("schools", school_a.pk)).status_code == 403

    def test_toggle_active_off_and_on(self, client_for, superuser, school_a):
        client = client_for(superuser)
        response = client.post(self.url("schools", school_a.pk), {"active": "false"})
        assert response.json() == {"ok": True, "active": False}
        school_a.refresh_from_db()
        assert school_a.active is False
        response = client.post(self.url("schools", school_a.pk), {"active": "true"})
        assert response.json()["active"] is True

    def test_post_without_active_leaves_item_unchanged(self, client_for, superuser, class_level):
        response = client_for(superuser).post(self.url("class-levels", class_level.pk), {})
        assert response.json() == {"ok": True, "active": True}

    def test_unknown_slug_and_item(self, client_for, superuser, school_a):
        client = client_for(superuser)
        assert client.post(self.url("nope", school_a.pk), {"active": "true"}).status_code == 404
        assert client.post(self.url("schools", "KPS000"), {"active": "true"}).status_code == 404


class TestTestEmail:
    url = reverse("core:test_email")

    @pytest.mark.parametrize("role", NON_MANAGERS)
    def test_forbidden(self, request, client_for, role):
        assert client_for(request.getfixturevalue(role)).get(self.url).status_code == 403

    def test_get_prefills_own_address_and_shows_config(self, client_for, admin_user):
        ctx = client_for(admin_user).get(self.url).context
        assert ctx["form"].initial["recipient"] == admin_user.email
        assert ctx["email_config"]["backend"].endswith("locmem.EmailBackend")

    def test_post_sends_and_redirects(self, client_for, admin_user):
        response = client_for(admin_user).post(self.url, {"recipient": "check@example.org"})
        assert response.status_code == 302
        assert len(mail.outbox) == 1
        msg = mail.outbox[0]
        assert msg.to == ["check@example.org"]
        assert msg.subject.endswith("Test email")
        assert admin_user.get_full_name() in msg.body or admin_user.username in msg.body
        assert any("Test email sent" in m for m in messages_of(response))

    def test_invalid_address_rerenders(self, client_for, admin_user):
        response = client_for(admin_user).post(self.url, {"recipient": "nope"})
        assert response.status_code == 200 and mail.outbox == []

    def test_smtp_failure_is_shown_to_admin(self, client_for, admin_user, monkeypatch):
        import core.views

        def boom(**kwargs):
            raise ConnectionRefusedError("smtp refused")

        monkeypatch.setattr(core.views, "send_test_email", boom)
        response = client_for(admin_user).post(self.url, {"recipient": "check@example.org"})
        assert response.status_code == 200
        assert any("ConnectionRefusedError: smtp refused" in m for m in messages_of(response))
