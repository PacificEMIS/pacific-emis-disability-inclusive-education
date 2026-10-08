"""
Project-wide pytest fixtures and model factories.

Everything here is shared by the test packages in accounts/, core/ and
integrations/. Tests never touch the development database: pytest-django
creates a throwaway test database and every test runs inside a transaction
that is rolled back at the end.

Conventions
-----------
- Factories build valid rows with sensible defaults; override only what the
  test cares about.
- Role fixtures (superuser, admin_user, teacher_user, ...) return a Django
  User already wired with the profile, group and school assignment that the
  role requires. `school_a` is the school every school-level role is
  assigned to; `school_b` is a school they are NOT assigned to.
- All outbound HTTP is blocked. Use the `responses` library (or patch the
  EMIS client) in tests that exercise the integration layer.
"""

import datetime as dt
from io import StringIO

import factory
import pytest
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.core.management import call_command

from core import permissions as perms
from core.models import (
    SchoolStaff,
    SchoolStaffAssignment,
    Student,
    StudentSchoolEnrolment,
    SystemUser,
)
from integrations.models import (
    EmisClassLevel,
    EmisJobTitle,
    EmisSchool,
    EmisWarehouseYear,
)

User = get_user_model()

TEST_PASSWORD = "test-password-123"


# ============================================================================
# Factories
# ============================================================================


class UserFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = User

    username = factory.Sequence(lambda n: f"user{n:04d}")
    email = factory.LazyAttribute(lambda o: f"{o.username}@example.org")
    first_name = factory.Sequence(lambda n: f"First{n}")
    last_name = factory.Sequence(lambda n: f"Last{n}")
    password = factory.django.Password(TEST_PASSWORD)
    is_active = True


class EmisSchoolFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = EmisSchool
        django_get_or_create = ("emis_school_no",)

    emis_school_no = factory.Sequence(lambda n: f"KPS{n:03d}")
    emis_school_name = factory.Sequence(lambda n: f"Test School {n}")
    active = True


class EmisClassLevelFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = EmisClassLevel
        django_get_or_create = ("code",)

    code = factory.Sequence(lambda n: f"L{n}")
    label = factory.LazyAttribute(lambda o: f"Level {o.code}")
    active = True


class EmisJobTitleFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = EmisJobTitle
        django_get_or_create = ("code",)

    code = factory.Sequence(lambda n: f"JT{n}")
    label = factory.LazyAttribute(lambda o: f"Job Title {o.code}")
    active = True


class EmisWarehouseYearFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = EmisWarehouseYear
        django_get_or_create = ("code",)

    code = factory.Sequence(lambda n: str(2000 + n))
    label = factory.LazyAttribute(lambda o: f"SY{o.code}")
    active = True


class SchoolStaffFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = SchoolStaff

    user = factory.SubFactory(UserFactory)
    staff_type = SchoolStaff.TEACHING_STAFF


class SchoolStaffAssignmentFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = SchoolStaffAssignment

    school_staff = factory.SubFactory(SchoolStaffFactory)
    school = factory.SubFactory(EmisSchoolFactory)
    job_title = factory.SubFactory(EmisJobTitleFactory)
    start_date = None
    end_date = None


class SystemUserFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = SystemUser

    user = factory.SubFactory(UserFactory)
    organization = "Ministry of Education"
    position_title = "Data Analyst"


class StudentFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = Student

    first_name = factory.Sequence(lambda n: f"Student{n}")
    last_name = factory.Sequence(lambda n: f"Family{n}")
    date_of_birth = dt.date(2015, 6, 15)
    gender = Student.Gender.MALE


class StudentSchoolEnrolmentFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = StudentSchoolEnrolment

    student = factory.SubFactory(StudentFactory)
    school = factory.SubFactory(EmisSchoolFactory)
    school_year = factory.SubFactory(EmisWarehouseYearFactory)
    class_level = factory.SubFactory(EmisClassLevelFactory)
    start_date = None
    end_date = None


# ============================================================================
# Global safety nets
# ============================================================================


@pytest.fixture(autouse=True)
def no_outbound_http(monkeypatch):
    """
    Fail any test that tries to make a real HTTP request.

    Patches the lowest layer of `requests`. The `responses` library patches
    the same attribute when activated, so tests using it still work.
    """
    from requests.adapters import HTTPAdapter

    def _blocked(self, request, *args, **kwargs):
        raise RuntimeError(
            f"Outbound HTTP blocked in tests: {request.method} {request.url}. "
            "Mock the EMIS client or use the `responses` library."
        )

    monkeypatch.setattr(HTTPAdapter, "send", _blocked)


@pytest.fixture(scope="session")
def django_db_setup(django_db_setup, django_db_blocker):
    """
    Seed the permission groups once per session using the real management
    command, so every test sees the same groups and permissions production
    has. Per-test changes are rolled back with the test transaction.
    """
    with django_db_blocker.unblock():
        call_command("seed_groups", stdout=StringIO())


# ============================================================================
# Lookup fixtures
# ============================================================================


@pytest.fixture
def school_a(db):
    """The school that every school-level role fixture is assigned to."""
    return EmisSchoolFactory(emis_school_no="KPS001", emis_school_name="Alpha Primary")


@pytest.fixture
def school_b(db):
    """A second school that no role fixture is assigned to."""
    return EmisSchoolFactory(emis_school_no="KPS002", emis_school_name="Beta Primary")


@pytest.fixture
def school_year(db):
    return EmisWarehouseYearFactory(code="2025", label="SY2025")


@pytest.fixture
def class_level(db):
    return EmisClassLevelFactory(code="P1", label="Primary 1")


@pytest.fixture
def job_title(db):
    return EmisJobTitleFactory(code="T", label="Teacher")


# ============================================================================
# Role builders and role fixtures
# ============================================================================


def group(name):
    return Group.objects.get(name=name)


@pytest.fixture
def make_school_user(db, job_title):
    """
    Build a user with a SchoolStaff profile.

    make_school_user(group_name=None, schools=(), **user_kwargs)
    Each school in `schools` becomes an open-ended active assignment.
    """

    def _make(group_name=None, schools=(), **user_kwargs):
        user = UserFactory(**user_kwargs)
        staff = SchoolStaffFactory(user=user)
        if group_name:
            user.groups.add(group(group_name))
        for school in schools:
            SchoolStaffAssignmentFactory(
                school_staff=staff, school=school, job_title=job_title
            )
        return user

    return _make


@pytest.fixture
def make_system_user(db):
    """Build a user with a SystemUser profile and an optional group."""

    def _make(group_name=None, **user_kwargs):
        user = UserFactory(**user_kwargs)
        SystemUserFactory(user=user)
        if group_name:
            user.groups.add(group(group_name))
        return user

    return _make


@pytest.fixture
def superuser(db):
    return UserFactory(username="root", is_superuser=True, is_staff=True)


@pytest.fixture
def admin_user(make_school_user):
    """Member of the 'Admins' group (system-wide, SchoolStaff profile)."""
    return make_school_user(perms.GROUP_ADMINS, username="admin")


@pytest.fixture
def system_admin_user(make_system_user):
    return make_system_user(perms.GROUP_SYSTEM_ADMINS, username="sysadmin")


@pytest.fixture
def system_staff_user(make_system_user):
    return make_system_user(perms.GROUP_SYSTEM_STAFF, username="sysstaff")


@pytest.fixture
def school_admin_user(make_school_user, school_a):
    return make_school_user(
        perms.GROUP_SCHOOL_ADMINS, schools=[school_a], username="schooladmin"
    )


@pytest.fixture
def teacher_user(make_school_user, school_a):
    return make_school_user(perms.GROUP_TEACHERS, schools=[school_a], username="teacher")


@pytest.fixture
def school_staff_user(make_school_user, school_a):
    return make_school_user(
        perms.GROUP_SCHOOL_STAFF, schools=[school_a], username="schoolstaff"
    )


@pytest.fixture
def pending_user(db):
    """Authenticated user with no profile and no group: must be locked out."""
    return UserFactory(username="pending")


@pytest.fixture
def profile_only_user(make_school_user):
    """Has a SchoolStaff profile but no group: must also be locked out."""
    return make_school_user(None, username="nogroup")


ROLE_FIXTURES = [
    "superuser",
    "admin_user",
    "system_admin_user",
    "system_staff_user",
    "school_admin_user",
    "teacher_user",
    "school_staff_user",
]


@pytest.fixture(params=ROLE_FIXTURES)
def any_app_user(request):
    """Parametrised over every role that is allowed into the app."""
    return request.getfixturevalue(request.param)


@pytest.fixture
def sync_email_threads(monkeypatch):
    """
    Run the fire-and-forget email threads in core.emails inline so tests
    can assert on django.core.mail.outbox right after the call.
    """
    import core.emails

    class InlineThread:
        def __init__(self, target=None, daemon=None, **kwargs):
            self._target = target

        def start(self):
            self._target()

    monkeypatch.setattr(core.emails, "Thread", InlineThread)


# ============================================================================
# Client helpers
# ============================================================================


@pytest.fixture
def client_for(client):
    """client_for(user) -> test client logged in as that user."""

    def _login(user):
        client.force_login(user)
        return client

    return _login
