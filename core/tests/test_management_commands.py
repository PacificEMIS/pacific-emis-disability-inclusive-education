"""
Tests for the core management commands: seed_groups, migrate_legacy_groups
and seed_students_disability_data.
"""

import datetime as dt
from io import StringIO

import pytest
from django.contrib.auth.models import Group, Permission
from django.core.management import CommandError, call_command

from conftest import EmisClassLevelFactory, EmisSchoolFactory, EmisWarehouseYearFactory, UserFactory
from core.management.commands import seed_students_disability_data as seed_mod
from core.models import Student, StudentSchoolEnrolment

pytestmark = pytest.mark.django_db

GROUPS = ["Admins", "School Admins", "School Staff", "Teachers", "System Admins", "System Staff"]


def run(name, *args, **kwargs):
    out = StringIO()
    call_command(name, *args, stdout=out, **kwargs)
    return out.getvalue()


class TestSeedGroups:
    def test_groups_exist_with_access_app(self):
        """The session fixture already ran the command; verify its result."""
        for name in GROUPS:
            g = Group.objects.get(name=name)
            assert g.permissions.filter(codename="access_app").exists(), name

    def test_rerun_is_idempotent(self):
        before = {g.name: set(g.permissions.values_list("id", flat=True)) for g in Group.objects.all()}
        out = run("seed_groups")
        after = {g.name: set(g.permissions.values_list("id", flat=True)) for g in Group.objects.all()}
        assert before == after
        assert "0 created, 6 already existed" in out
        assert "Permissions assigned: 0 new" in out

    def test_reset_restores_removed_and_drops_extra_permissions(self):
        teachers = Group.objects.get(name="Teachers")
        access = Permission.objects.get(codename="access_app")
        extra = Permission.objects.get(codename="delete_user")
        teachers.permissions.remove(access)
        teachers.permissions.add(extra)

        out = run("seed_groups", "--reset")
        assert "Cleared existing permissions" in out
        assert teachers.permissions.filter(pk=access.pk).exists()
        assert not teachers.permissions.filter(pk=extra.pk).exists()

    def test_without_reset_extra_permission_is_kept(self):
        teachers = Group.objects.get(name="Teachers")
        extra = Permission.objects.get(codename="delete_user")
        teachers.permissions.add(extra)
        run("seed_groups")
        assert teachers.permissions.filter(pk=extra.pk).exists()

    def test_recreates_deleted_group(self):
        Group.objects.get(name="Teachers").delete()
        out = run("seed_groups")
        assert "Created group: Teachers" in out
        assert Group.objects.get(name="Teachers").permissions.filter(codename="access_app").exists()

    def test_read_only_groups_cannot_change_students(self):
        for name in ("School Staff", "System Staff"):
            g = Group.objects.get(name=name)
            assert not g.permissions.filter(codename__in=["add_student", "change_student", "delete_student"]).exists(), name

    def test_admins_can_delete_students_but_teachers_cannot(self):
        assert Group.objects.get(name="Admins").permissions.filter(codename="delete_student").exists()
        assert not Group.objects.get(name="Teachers").permissions.filter(codename="delete_student").exists()


class TestMigrateLegacyGroups:
    @pytest.fixture
    def legacy(self, db):
        legacy_teachers = Group.objects.create(name="InclusiveEd - Teachers")
        legacy_admins = Group.objects.create(name="InclusiveEd - Admins")
        u1 = UserFactory(username="legacy-one")
        u2 = UserFactory(username="legacy-two")
        u1.groups.add(legacy_teachers)
        u2.groups.add(legacy_teachers, legacy_admins)
        u2.groups.add(Group.objects.get(name="Teachers"))  # already migrated for one group
        return {"u1": u1, "u2": u2}

    def test_dry_run_changes_nothing(self, legacy):
        out = run("migrate_legacy_groups")
        assert "DRY RUN" in out
        assert "Would delete legacy group: InclusiveEd - Teachers" in out
        assert Group.objects.filter(name="InclusiveEd - Teachers").exists()
        assert not legacy["u1"].groups.filter(name="Teachers").exists()

    def test_commit_moves_users_and_deletes_legacy_groups(self, legacy):
        out = run("migrate_legacy_groups", "--commit")
        assert "Migration complete: 3 user(s) migrated, 2 legacy group(s) deleted." in out
        assert not Group.objects.filter(name__startswith="InclusiveEd - ").exists()
        assert set(legacy["u1"].groups.values_list("name", flat=True)) == {"Teachers"}
        assert set(legacy["u2"].groups.values_list("name", flat=True)) == {"Teachers", "Admins"}
        assert "legacy-two already in 'Teachers'" in out

    def test_missing_legacy_groups_are_skipped(self):
        out = run("migrate_legacy_groups", "--commit")
        assert out.count("does not exist, skipping") == 6
        assert "0 user(s) migrated, 0 legacy group(s) deleted" in out

    def test_creates_new_group_when_missing(self, legacy):
        Group.objects.get(name="Admins").delete()
        run("migrate_legacy_groups", "--commit")
        assert Group.objects.filter(name="Admins").exists()
        assert legacy["u2"].groups.filter(name="Admins").exists()


class TestSeedStudentsDisabilityData:
    @pytest.fixture
    def seeded_lookups(self, db):
        EmisWarehouseYearFactory(code="2025")
        for code in seed_mod.LEVELS_BY_PATTERN["KPS"] + seed_mod.LEVELS_BY_PATTERN["KJSS"] + seed_mod.LEVELS_BY_PATTERN["KSSS"]:
            EmisClassLevelFactory(code=code)
        EmisSchoolFactory(emis_school_no="KPS001")
        EmisSchoolFactory(emis_school_no="KJSS001")
        EmisSchoolFactory(emis_school_no="KSSS001")
        EmisSchoolFactory(emis_school_no="KECE001")  # must be ignored

    def test_missing_year_is_an_error(self, db):
        with pytest.raises(CommandError, match="EmisWarehouseYear"):
            run("seed_students_disability_data", "--year", "1999")

    def test_missing_levels_is_an_error(self, db):
        EmisWarehouseYearFactory(code="2025")
        with pytest.raises(CommandError, match="Missing EmisClassLevel codes"):
            run("seed_students_disability_data")

    def test_dry_run_writes_nothing(self, seeded_lookups):
        out = run("seed_students_disability_data", "--dry-run", "--seed", "1")
        assert "DRY RUN" in out
        assert "Schools: KPS=1  KJSS=1  KSSS=1" in out
        assert Student.objects.count() == 0

    def test_seed_creates_students_with_single_enrolment_each(self, seeded_lookups):
        out = run("seed_students_disability_data", "--seed", "42")
        assert "Done. Created" in out
        n = Student.objects.count()
        assert n > 0
        assert StudentSchoolEnrolment.objects.count() == n
        assert not StudentSchoolEnrolment.objects.filter(school__emis_school_no__startswith="KECE").exists()
        for e in StudentSchoolEnrolment.objects.select_related("school", "class_level"):
            prefix = next(p for p in ("KJSS", "KSSS", "KPS") if e.school.emis_school_no.startswith(p))
            assert e.class_level.code in seed_mod.LEVELS_BY_PATTERN[prefix]
            assert e.school_year.code == "2025"

    def test_seed_is_deterministic(self, seeded_lookups):
        run("seed_students_disability_data", "--seed", "7")
        first = list(Student.objects.order_by("pk").values_list("first_name", "last_name", "date_of_birth"))
        Student.objects.all().delete()
        run("seed_students_disability_data", "--seed", "7")
        second = list(Student.objects.order_by("pk").values_list("first_name", "last_name", "date_of_birth"))
        assert first == second

    def test_dob_for_level_matches_official_age(self):
        dob = seed_mod.dob_for_level("P1", "2025")
        age = 2025 - dob.year
        official = seed_mod.OFFICIAL_AGE["P1"]
        assert age in (official - 1, official, official + 1)

    def test_random_helpers_stay_within_choices(self):
        for _ in range(200):
            assert seed_mod.random_yes_no_or_none() in (None, 1, 2)
            assert seed_mod.random_difficulty_or_none() in (None, 1, 2, 3, 4)
            assert seed_mod.random_emotional_freq_or_none() in (None, 1, 2, 3, 4, 5)
            assert seed_mod.pick_size_bucket() > 0
