"""
Tests for the two EMIS HTTP clients and the warehouse cache loader.

HTTP is recorded with the `responses` library; the global harness blocks any
request that is not registered here.
"""

import datetime as dt
import json
import pickle

import pytest
import responses
import time_machine
from django.core.cache import cache

from integrations import odata_client as oc
from integrations.emis_client import EmisClient
from integrations.odata_client import ODataClient

TOKEN_URL = "http://emis.invalid/api/token"
LOOKUPS_URL = "http://emis.invalid/api/lookups/collection/core"
ODATA_URL = "http://emis.invalid/api/odata/warehouse"


@pytest.fixture
def rsps():
    with responses.RequestsMock(assert_all_requests_are_fired=False) as mock:
        yield mock


class TestEmisClient:
    def test_fetches_token_then_lookups(self, rsps):
        rsps.post(TOKEN_URL, json={"access_token": "abc"})
        rsps.get(LOOKUPS_URL, json={"schoolCodes": []})
        client = EmisClient()
        assert client.get_core_lookups() == {"schoolCodes": []}

        token_call, lookups_call = rsps.calls
        assert "grant_type=password" in token_call.request.body
        assert "username=emis-test-user" in token_call.request.body
        assert lookups_call.request.headers["Authorization"] == "Bearer abc"

    def test_accepts_camel_case_token(self, rsps):
        rsps.post(TOKEN_URL, json={"accessToken": "camel"})
        rsps.get(LOOKUPS_URL, json={})
        EmisClient().get_core_lookups()
        assert rsps.calls[1].request.headers["Authorization"] == "Bearer camel"

    def test_token_is_reused_within_thirty_minutes_and_refreshed_after(self, rsps):
        rsps.post(TOKEN_URL, json={"access_token": "t1"})
        rsps.get(LOOKUPS_URL, json={})
        client = EmisClient()
        with time_machine.travel(dt.datetime(2026, 1, 1, 12, 0, tzinfo=dt.timezone.utc), tick=False) as tm:
            client.get_core_lookups()
            tm.shift(dt.timedelta(minutes=29))
            client.get_core_lookups()
            assert sum(1 for c in rsps.calls if c.request.url == TOKEN_URL) == 1
            tm.shift(dt.timedelta(minutes=2))
            client.get_core_lookups()
            assert sum(1 for c in rsps.calls if c.request.url == TOKEN_URL) == 2

    def test_http_error_on_token_raises(self, rsps):
        rsps.post(TOKEN_URL, status=401, json={"error": "bad"})
        with pytest.raises(Exception):
            EmisClient().get_core_lookups()

    def test_http_error_on_lookups_raises(self, rsps):
        rsps.post(TOKEN_URL, json={"access_token": "abc"})
        rsps.get(LOOKUPS_URL, status=500)
        with pytest.raises(Exception):
            EmisClient().get_core_lookups()

    def test_unmocked_request_is_blocked_by_harness(self):
        with pytest.raises(RuntimeError, match="Outbound HTTP blocked"):
            EmisClient().get_core_lookups()


class TestODataClient:
    def test_skips_auth_without_credentials(self, settings, rsps):
        settings.EMIS = {**settings.EMIS, "USERNAME": "", "PASSWORD": ""}
        rsps.get(f"{ODATA_URL}/EnrolSchool", json={"value": [{"a": 1}]})
        client = ODataClient()
        assert client._headers() == {}
        assert client.get_enrolment_by_school() == [{"a": 1}]
        assert all(c.request.url != TOKEN_URL for c in rsps.calls)

    def test_authenticates_with_credentials(self, rsps):
        rsps.post(TOKEN_URL, json={"access_token": "od"})
        assert ODataClient()._headers() == {"Authorization": "Bearer od"}

    def test_follows_next_links(self, rsps):
        rsps.get(
            f"{ODATA_URL}/EnrolSchool",
            json={"value": [{"n": 1}], "@odata.nextLink": f"{ODATA_URL}/EnrolSchool?$skip=1"},
            match=[responses.matchers.query_param_matcher({"$top": "1"})],
        )
        rsps.get(
            f"{ODATA_URL}/EnrolSchool",
            json={"value": [{"n": 2}], "odata.nextLink": f"{ODATA_URL}/EnrolSchool?$skip=2"},
            match=[responses.matchers.query_param_matcher({"$skip": "1"})],
        )
        rsps.get(
            f"{ODATA_URL}/EnrolSchool",
            json={"value": [{"n": 3}]},
            match=[responses.matchers.query_param_matcher({"$skip": "2"})],
        )
        data = ODataClient().get_enrolment_by_school(top=1)
        assert data == [{"n": 1}, {"n": 2}, {"n": 3}]

    def test_query_params_are_built(self, rsps):
        rsps.get(
            f"{ODATA_URL}/EnrolDistrict",
            json={"value": []},
            match=[
                responses.matchers.query_param_matcher(
                    {"$filter": "SurveyYear eq 2024", "$select": "A,B", "$orderby": "A asc", "$top": "5"}
                )
            ],
        )
        ODataClient().get_enrolment_by_district(
            filters="SurveyYear eq 2024", select=["A", "B"], orderby="A asc", top=5
        )

    @pytest.mark.parametrize(
        "method,suffix",
        [
            ("get_enrolment_by_school", "EnrolSchool"),
            ("get_enrolment_by_district", "EnrolDistrict"),
            ("get_enrolment_by_authority", "EnrolAuthority"),
            ("get_enrolment_by_nation", "EnrolNation"),
        ],
    )
    def test_endpoints(self, rsps, method, suffix):
        rsps.get(f"{ODATA_URL}/{suffix}", json={"value": [{"ok": True}]})
        assert getattr(ODataClient(), method)() == [{"ok": True}]

    def test_build_params_accepts_string_select(self):
        params = ODataClient()._build_odata_params(None, "A,B", None, None)
        assert params == {"$select": "A,B"}
        assert ODataClient()._build_odata_params(None, None, None, None) == {}

    def test_cache_key_is_stable_and_order_independent(self):
        client = ODataClient()
        k1 = client._generate_cache_key("e", {"a": 1, "b": 2})
        k2 = client._generate_cache_key("e", {"b": 2, "a": 1})
        assert k1 == k2 and k1.startswith("odata:")
        assert client._generate_cache_key("e", {"a": 2}) != k1

    def test_invalidate_cache_deletes_matching_key(self):
        client = ODataClient()
        params = client._build_odata_params("f", ["x"], None, None)
        key = client._generate_cache_key(f"{ODATA_URL}/EnrolSchool", params)
        cache.set(key, "cached")
        client.invalidate_cache("EnrolSchool", filters="f", select=["x"])
        assert cache.get(key) is None

    def test_clear_all_cache(self):
        cache.set("anything", 1)
        ODataClient().clear_all_cache()
        assert cache.get("anything") is None

    def test_http_error_raises(self, rsps):
        rsps.get(f"{ODATA_URL}/EnrolNation", status=503)
        with pytest.raises(Exception):
            ODataClient().get_enrolment_by_nation()


class TestLoadEnrollmentCache:
    @pytest.fixture
    def data_dir(self, settings, tmp_path):
        settings.BASE_DIR = tmp_path
        d = tmp_path / "data"
        d.mkdir()
        return d

    def test_missing_files_give_none(self, data_dir):
        assert oc.load_enrollment_cache() is None

    def test_pickle_is_preferred(self, data_dir):
        (data_dir / "enrollment_aggregated.pickle").write_bytes(pickle.dumps([{"from": "pickle"}]))
        (data_dir / "enrollment_aggregated.json").write_text(json.dumps([{"from": "json"}]))
        assert oc.load_enrollment_cache() == [{"from": "pickle"}]

    def test_json_fallback(self, data_dir):
        (data_dir / "enrollment_aggregated.json").write_text(json.dumps([{"from": "json"}]))
        assert oc.load_enrollment_cache() == [{"from": "json"}]

    def test_corrupt_pickle_falls_back_to_json(self, data_dir):
        (data_dir / "enrollment_aggregated.pickle").write_bytes(b"not a pickle")
        (data_dir / "enrollment_aggregated.json").write_text(json.dumps([{"from": "json"}]))
        assert oc.load_enrollment_cache() == [{"from": "json"}]

    def test_corrupt_everything_gives_none(self, data_dir):
        (data_dir / "enrollment_aggregated.pickle").write_bytes(b"x")
        (data_dir / "enrollment_aggregated.json").write_text("{not json")
        assert oc.load_enrollment_cache() is None
