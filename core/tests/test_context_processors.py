"""
The deployment name split into the system and its environment, and the
not-production warning every page carries outside production.
"""

import pytest
from django.urls import reverse

from pacemis_inclusive_ed.context_processors import emis_context


@pytest.mark.parametrize(
    ("context", "name", "environment"),
    [
        ("KEMIS (Dev)", "KEMIS", "Dev"),
        ("KEMIS (Test)", "KEMIS", "Test"),
        ("FEDEMIS ( Staging )", "FEDEMIS", "Staging"),
        ("KEMIS", "KEMIS", None),
        ("Pacific EMIS", "Pacific EMIS", None),
    ],
)
def test_context_splits_into_name_and_environment(settings, context, name, environment):
    settings.EMIS = {**settings.EMIS, "CONTEXT": context}

    result = emis_context(None)

    assert result["emis_context"] == context
    assert result["emis_name"] == name
    assert result["emis_environment"] == environment


def test_logo_is_the_first_word_of_the_context(settings):
    settings.EMIS = {**settings.EMIS, "CONTEXT": "KEMIS (Dev)"}

    assert emis_context(None)["emis_logo"] == "kemis"


@pytest.mark.django_db
def test_pages_outside_production_warn_everywhere(client, settings):
    settings.EMIS = {**settings.EMIS, "CONTEXT": "KEMIS (Test)"}

    response = client.get(reverse("accounts:login"))

    html = response.content.decode()
    assert "app-env-banner" in html
    assert "TEST environment" in html
    assert "not the production KEMIS" in html
    assert "[TEST]" in html.split("<title>")[1].split("</title>")[0]


@pytest.mark.django_db
def test_production_pages_carry_no_warning(client, settings):
    settings.EMIS = {**settings.EMIS, "CONTEXT": "KEMIS"}

    response = client.get(reverse("accounts:login"))

    html = response.content.decode()
    assert "app-env-banner" not in html
    assert "app-env-badge" not in html
    assert "not production" not in html


@pytest.mark.django_db
def test_signed_in_pages_show_the_environment_under_the_seal(client_for, superuser, settings):
    settings.EMIS = {**settings.EMIS, "CONTEXT": "KEMIS (Dev)"}

    html = client_for(superuser).get(reverse("core:dashboard")).content.decode()

    assert "app-env-badge" in html
    assert ">DEV<" in html
    assert 'class="sidebar-app-title fw-bold">KEMIS<' in html
