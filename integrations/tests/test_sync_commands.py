"""
Tests for the EMIS sync management commands: emis_sync_lookups (upserts the
four lookup tables) and emis_sync_warehouse_data (aggregates OData enrolment
into a filesystem cache for the dashboard).
"""

import datetime as dt
import json
import pickle
from io import StringIO

import pytest
from django.core.cache import cache
from django.core.management import call_command

from conftest import EmisClassLevelFactory, EmisSchoolFactory
from integrations.emis_client import EmisClient
from integrations.management.commands.emis_sync_lookups import LAST_SYNC_CACHE_KEY
from integrations.models import EmisClassLevel, EmisJobTitle, EmisSchool, EmisWarehouseYear
from integrations.odata_client import ODataClient

pytestmark = pytest.mark.django_db


def run(name, *args, **kwargs):
    out = StringIO()
    call_command(name, *args, stdout=out, **kwargs)
    return out.getvalue()


# ============================================================================
# emis_sync_lookups
# ============================================================================


class TestSyncLookups:
    @pytest.fixture(autouse=True)
    def clear_cache(self):
        cache.clear()
        yield
        cache.clear()

    def payload(self, monkeypatch, **overrides):
        data = {
            "schoolCodes": [{"C": "KPS001", "N": "Alpha Primary"}, {"C": "KPS002", "N": "Beta Primary"}],
            "levels": [{"C": "P1", "N": "Primary 1"}, {"C": 2, "N": None}],
            "teacherRoles": [{"C": "T", "N": "Teacher"}],
            "warehouseYears": [{"C": 2025, "FormattedYear": "SY2025"}, {"C": "2026"}],
        }
        data.update(overrides)
        monkeypatch.setattr(EmisClient, "get_core_lookups", lambda self: data)
        return data

    def test_creates_all_lookups_and_reports_counts(self, monkeypatch):
        self.payload(monkeypatch)
        out = run("emis_sync_lookups")
        assert "Schools +2/0, Levels +2/0, Job Titles +1/0, Warehouse Years +2/0" in out
        assert EmisSchool.objects.get(pk="KPS001").emis_school_name == "Alpha Primary"
        # numeric codes are stringified and missing labels fall back to the code
        assert EmisClassLevel.objects.get(pk="2").label == "2"
        assert EmisWarehouseYear.objects.get(pk="2025").label == "SY2025"
        assert EmisWarehouseYear.objects.get(pk="2026").label == "2026"
        assert EmisJobTitle.objects.get(pk="T").label == "Teacher"

    def test_updates_existing_and_reactivates(self, monkeypatch):
        EmisSchoolFactory(emis_school_no="KPS001", emis_school_name="Old Name", active=False)
        EmisClassLevelFactory(code="P1", label="Old", active=False)
        self.payload(monkeypatch)
        out = run("emis_sync_lookups")
        assert "Schools +1/1" in out and "Levels +1/1" in out
        s = EmisSchool.objects.get(pk="KPS001")
        assert s.emis_school_name == "Alpha Primary" and s.active is True
        assert EmisClassLevel.objects.get(pk="P1").active is True

    def test_items_without_code_are_skipped(self, monkeypatch):
        self.payload(monkeypatch, schoolCodes=[{"C": "", "N": "no code"}, {"N": "none"}])
        out = run("emis_sync_lookups")
        assert "Schools +0/0" in out
        assert EmisSchool.objects.count() == 0

    def test_missing_sections_are_tolerated(self, monkeypatch):
        monkeypatch.setattr(EmisClient, "get_core_lookups", lambda self: {})
        out = run("emis_sync_lookups")
        assert "Schools +0/0, Levels +0/0, Job Titles +0/0, Warehouse Years +0/0" in out

    def test_local_only_records_are_kept(self, monkeypatch):
        """Sync is additive: a school no longer in EMIS stays, untouched."""
        local = EmisSchoolFactory(emis_school_no="KPS999", emis_school_name="Local Only")
        self.payload(monkeypatch)
        run("emis_sync_lookups")
        local.refresh_from_db()
        assert local.emis_school_name == "Local Only" and local.active is True

    def test_records_last_sync_in_cache(self, monkeypatch):
        self.payload(monkeypatch)
        run("emis_sync_lookups")
        last = cache.get(LAST_SYNC_CACHE_KEY)
        assert last["message"].startswith("Schools +2/0")
        assert isinstance(last["at"], dt.datetime)

    def test_client_failure_propagates_and_writes_nothing(self, monkeypatch):
        def boom(self):
            raise RuntimeError("EMIS down")

        monkeypatch.setattr(EmisClient, "get_core_lookups", boom)
        with pytest.raises(RuntimeError, match="EMIS down"):
            run("emis_sync_lookups")
        assert EmisSchool.objects.count() == 0
        assert cache.get(LAST_SYNC_CACHE_KEY) is None

    def test_is_atomic(self, monkeypatch):
        """A bad row later in the payload rolls back rows already written."""
        self.payload(monkeypatch, levels=[{"C": "P1", "N": "x" * 500}])  # label too long
        with pytest.raises(Exception):
            run("emis_sync_lookups")
        assert EmisSchool.objects.count() == 0


# ============================================================================
# emis_sync_warehouse_data
# ============================================================================


RECORDS = [
    {"SurveyYear": 2025, "SchoolNo": "KPS001", "SchoolName": "Alpha", "GenderCode": "M", "Enrol": 10},
    {"SurveyYear": 2025, "SchoolNo": "KPS001", "SchoolName": "Alpha", "GenderCode": "M", "Enrol": 5},
    {"SurveyYear": 2025, "SchoolNo": "KPS001", "SchoolName": "Alpha", "GenderCode": "F", "Enrol": 7},
    {"SurveyYear": "2024", "SchoolNo": "KPS002", "SchoolName": None, "GenderCode": None, "Enrol": None},
    {"SurveyYear": None, "SchoolNo": "KPS003", "Enrol": 99},  # dropped: no year
]


class TestSyncWarehouseData:
    @pytest.fixture
    def base_dir(self, settings, tmp_path):
        settings.BASE_DIR = tmp_path
        return tmp_path

    @pytest.fixture
    def odata(self, monkeypatch):
        calls = []

        def fake(self, filters=None, select=None, orderby=None, top=None):
            calls.append((filters, select))
            return list(RECORDS)

        monkeypatch.setattr(ODataClient, "get_enrolment_by_school", fake)
        return calls

    def test_aggregates_and_writes_pickle_and_metadata(self, base_dir, odata):
        out = run("emis_sync_warehouse_data")
        assert "Fetched 5 records" in out
        assert "Aggregated to 3 unique combinations" in out
        assert odata == [(None, None)]

        data = pickle.loads((base_dir / "data" / "enrollment_aggregated.pickle").read_bytes())
        by_key = {(r["SurveyYear"], r["SchoolNo"], r["GenderCode"]): r for r in data}
        assert by_key[(2025, "KPS001", "M")]["Enrol"] == 15
        assert by_key[(2025, "KPS001", "F")]["Enrol"] == 7
        unknown = by_key[(2024, "KPS002", "U")]
        assert unknown["Enrol"] == 0 and unknown["SchoolName"] == ""

        meta = json.loads((base_dir / "data" / "enrollment_metadata.json").read_text())
        assert meta["record_count"] == 3 and meta["source_record_count"] == 5
        assert meta["format"] == "pickle"
        assert meta["endpoint"].endswith("/EnrolSchool")

    def test_json_format(self, base_dir, odata):
        run("emis_sync_warehouse_data", "--format", "json")
        data = json.loads((base_dir / "data" / "enrollment_aggregated.json").read_text())
        assert len(data) == 3

    def test_recent_cache_is_not_refreshed_without_force(self, base_dir, odata):
        run("emis_sync_warehouse_data")
        out = run("emis_sync_warehouse_data")
        assert "less than 24 hours old" in out
        assert len(odata) == 1

    def test_force_refreshes(self, base_dir, odata):
        run("emis_sync_warehouse_data")
        run("emis_sync_warehouse_data", "--force")
        assert len(odata) == 2

    def test_stale_cache_is_refreshed(self, base_dir, odata):
        run("emis_sync_warehouse_data")
        meta_file = base_dir / "data" / "enrollment_metadata.json"
        meta = json.loads(meta_file.read_text())
        meta["last_sync"] = (dt.datetime.now() - dt.timedelta(hours=25)).isoformat()
        meta_file.write_text(json.dumps(meta))
        run("emis_sync_warehouse_data")
        assert len(odata) == 2

    def test_unreadable_metadata_triggers_refresh(self, base_dir, odata):
        run("emis_sync_warehouse_data")
        (base_dir / "data" / "enrollment_metadata.json").write_text("{broken")
        out = run("emis_sync_warehouse_data")
        assert "Could not read metadata" in out
        assert len(odata) == 2

    def test_fetch_failure_raises(self, base_dir, monkeypatch):
        def boom(self, **kwargs):
            raise RuntimeError("odata down")

        monkeypatch.setattr(ODataClient, "get_enrolment_by_school", boom)
        with pytest.raises(RuntimeError, match="odata down"):
            run("emis_sync_warehouse_data")
        assert not (base_dir / "data" / "enrollment_aggregated.pickle").exists()

    def test_dashboard_loader_reads_what_the_command_wrote(self, base_dir, odata):
        from integrations.odata_client import load_enrollment_cache

        run("emis_sync_warehouse_data")
        data = load_enrollment_cache()
        assert sum(r["Enrol"] for r in data) == 22
