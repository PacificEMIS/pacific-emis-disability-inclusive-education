"""
Core models for the Pacific EMIS system.

This module contains fundamental person-related models that are shared across
multiple applications within the Pacific EMIS ecosystem.

Models:
    AuditModel: Abstract base model with audit fields (created_at, created_by, etc.)
    SchoolStaff: School-level user profiles (teachers, principals, etc.)
    SystemUser: System-level user profiles (MOE officials, analysts, etc.)
    SchoolStaffAssignment: Links school staff to schools with job titles
    Student: Student profiles with basic information
    StudentSchoolEnrolment: Student enrolments at schools with disability data (CFT 1-20)
    PermissionsAnchor: Dummy model for app-level permissions
"""

from typing import TYPE_CHECKING

from django.conf import settings
from django.contrib.postgres.indexes import GinIndex
from django.db import models
from django.utils import timezone
from django.utils.translation import gettext_lazy as _

from integrations.models import (
    EmisSchool,
    EmisJobTitle,
    EmisWarehouseYear,
    EmisClassLevel,
)

if TYPE_CHECKING:
    from django.db.models.manager import RelatedManager


class AuditModel(models.Model):
    """
    Abstract base model that provides audit fields.

    All models that need audit tracking should inherit from this.
    Provides: created_at, created_by, last_updated_at, last_updated_by
    """

    created_at = models.DateTimeField(auto_now_add=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="%(app_label)s_%(class)s_created",
    )
    last_updated_at = models.DateTimeField(auto_now=True)
    last_updated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="%(app_label)s_%(class)s_updated",
    )

    class Meta:
        abstract = True


class SchoolStaff(AuditModel):
    """
    School-level staff profile for users who work at schools.

    Represents staff members such as teachers, principals, counselors, etc.
    Each SchoolStaff has a one-to-one relationship with a Django User.
    School assignments are managed through SchoolStaffAssignment.

    Attributes:
        user (User): Django user account (one-to-one)
        staff_type (str): Type of staff - Teaching or Non-Teaching
        schools (QuerySet[EmisSchool]): Schools this staff member is assigned to (via SchoolStaffAssignment)
        created_at (datetime): When this record was created
        created_by (User): Who created this record
        last_updated_at (datetime): When this record was last modified
        last_updated_by (User): Who last modified this record

    Example:
        >>> user = User.objects.get(username='jsmith')
        >>> staff = SchoolStaff.objects.create(
        ...     user=user,
        ...     staff_type=SchoolStaff.TEACHING_STAFF,
        ...     created_by=admin_user
        ... )
        >>> assignment = SchoolStaffAssignment.objects.create(
        ...     school_staff=staff,
        ...     school=some_school,
        ...     job_title=teacher_title
        ... )
    """

    TEACHING_STAFF = "teaching"
    NON_TEACHING_STAFF = "non_teaching"

    STAFF_TYPE_CHOICES = [
        (TEACHING_STAFF, "Teaching Staff"),
        (NON_TEACHING_STAFF, "Non-Teaching Staff"),
    ]

    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="school_staff",
        help_text="Django user account for this staff member",
    )

    staff_type = models.CharField(
        max_length=20,
        choices=STAFF_TYPE_CHOICES,
        default=NON_TEACHING_STAFF,
        help_text="Type of staff member - teaching or non-teaching",
    )

    # Many-to-many relationship with schools (through SchoolStaffAssignment)
    schools = models.ManyToManyField(
        EmisSchool,
        through="SchoolStaffAssignment",
        related_name="school_staff_members",
        blank=True,
    )

    if TYPE_CHECKING:
        # Type hint for the reverse relation from SchoolStaffAssignment
        assignments: "RelatedManager[SchoolStaffAssignment]"

    class Meta:
        ordering = ["user_id"]
        verbose_name = "School Staff"
        verbose_name_plural = "School Staff"

    def __str__(self):
        """Return string representation showing the user."""
        return f"SchoolStaff<{self.user}>"

    @property
    def active_assignments(self):
        """
        Get all currently active school assignments.

        Returns assignments where end_date is either null or in the future/today.

        Returns:
            QuerySet[SchoolStaffAssignment]: Active assignments for this staff member
        """
        today = timezone.now().date()
        return self.assignments.filter(
            models.Q(end_date__isnull=True) | models.Q(end_date__gte=today)
        )


class SchoolStaffAssignment(AuditModel):
    """
    School assignment for a SchoolStaff member.

    Links a staff member to a specific school with a job title and date range.
    Multiple assignments allow staff to work at different schools over time.

    Attributes:
        school_staff (SchoolStaff): The staff member being assigned
        school (EmisSchool): The school they're assigned to
        job_title (EmisJobTitle): Their role at this school (e.g., Teacher, Principal)
        start_date (date): When the assignment began (optional)
        end_date (date): When the assignment ended (null = currently active)
        created_at (datetime): When this record was created
        created_by (User): Who created this record
        last_updated_at (datetime): When this record was last modified
        last_updated_by (User): Who last modified this record

    Note:
        The is_active property considers an assignment active if end_date is None.
        Use the active_now admin method for date-range-based active status.

    Example:
        >>> assignment = SchoolStaffAssignment.objects.create(
        ...     school_staff=staff,
        ...     school=school,
        ...     job_title=title,
        ...     start_date=date(2024, 1, 1),
        ...     created_by=admin_user
        ... )
    """

    school_staff = models.ForeignKey(
        SchoolStaff,
        on_delete=models.CASCADE,
        related_name="assignments",
        help_text="Staff member being assigned",
    )
    school = models.ForeignKey(
        EmisSchool,
        on_delete=models.PROTECT,
        related_name="staff_assignments",
        help_text="School where staff is assigned",
    )
    job_title = models.ForeignKey(
        EmisJobTitle,
        on_delete=models.PROTECT,
        related_name="job_title_assignments",
        help_text="Job title/role at this school",
    )

    start_date = models.DateField(
        null=True, blank=True, help_text="When this assignment began"
    )
    end_date = models.DateField(
        null=True,
        blank=True,
        help_text="When this assignment ended (null = currently active)",
    )

    class Meta:
        indexes = [
            models.Index(fields=["start_date", "end_date"]),
        ]
        constraints = [
            models.UniqueConstraint(
                fields=["school_staff", "school", "start_date", "end_date"],
                name="uq_school_staff_assignment",
            ),
        ]
        ordering = ["school_staff_id", "school_id", "start_date"]
        verbose_name = "School Staff Assignment"
        verbose_name_plural = "School Staff Assignments"

    def __str__(self):
        """Return string representation showing staff and school."""
        return f"{self.school_staff.user} @ {self.school}"

    @property
    def is_active(self):
        """
        Check if this assignment is marked as active.

        An assignment is considered active if it has no end_date set.
        This is a simple active/inactive flag, not date-range based.

        Returns:
            bool: True if end_date is None, False otherwise

        Note:
            For date-range-based active status (checking if assignment
            is active TODAY), use the admin's active_now method.
        """
        return self.end_date is None


class SystemUser(AuditModel):
    """
    System-level user profile with cross-organizational access.

    Represents users who operate at a system-wide level rather than
    being tied to specific schools. Examples include:
    - Ministry of Education officials
    - District/regional office staff
    - System administrators
    - External consultants
    - Data analysts

    Unlike SchoolStaff (who work at specific schools), SystemUsers
    have permissions across the entire system.

    Attributes:
        user (User): Django user account (one-to-one)
        organization (str): Organization name (e.g., "Ministry of Education")
        position_title (str): Job title within the organization
        created_at (datetime): When this record was created
        created_by (User): Who created this record
        last_updated_at (datetime): When this record was last modified
        last_updated_by (User): Who last modified this record

    Example:
        >>> user = User.objects.get(username='jdoe')
        >>> system_user = SystemUser.objects.create(
        ...     user=user,
        ...     organization="Ministry of Education",
        ...     position_title="Data Analyst",
        ...     created_by=admin_user
        ... )
    """

    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="system_user",
        help_text="Django user account for this system user",
    )

    organization = models.CharField(
        max_length=255,
        blank=True,
        help_text="Organization or department (e.g., Ministry of Education, District Office)",
    )
    position_title = models.CharField(
        max_length=255,
        blank=True,
        help_text="Job title or position within the organization",
    )

    class Meta:
        ordering = ["user__last_name", "user__first_name"]
        verbose_name = "System User"
        verbose_name_plural = "System Users"

    def __str__(self):
        """
        Return string representation showing name and organization.

        Returns:
            str: User's full name (or username) with organization in parentheses if set
        """
        name = self.user.get_full_name() or self.user.username
        if self.organization:
            return f"{name} ({self.organization})"
        return name


# ============================================================================
# Student Models
# ============================================================================

#  Choice constants for disability questionnaire (CFT 1-20)
YES_NO_CHOICES = (
    (1, _("Yes")),
    (2, _("No")),
)

DIFFICULTY_CHOICES_4 = (
    (1, _("No difficulty")),
    (2, _("Some difficulty")),
    (3, _("A lot of difficulty")),
    (4, _("Cannot do at all")),
)

EMOTIONAL_FREQ_CHOICES_5 = (
    (1, _("Daily")),
    (2, _("Weekly")),
    (3, _("Monthly")),
    (4, _("A few times a year")),
    (5, _("Never")),
)


class Student(models.Model):
    """
    Student profile with basic demographic information.

    Students can be enrolled in multiple schools across different school years
    through the StudentSchoolEnrolment model.

    Attributes:
        first_name (str): Student's first name
        last_name (str): Student's last name
        date_of_birth (date): Student's date of birth
        schools (QuerySet[EmisSchool]): Schools student is/was enrolled in (via StudentSchoolEnrolment)
        created_at (datetime): When this record was created
        created_by (User): Who created this record
        last_updated_at (datetime): When this record was last modified
        last_updated_by (User): Who last modified this record
    """

    class Gender(models.IntegerChoices):
        MALE = 1, "Male"
        FEMALE = 2, "Female"

    first_name = models.CharField(max_length=100)
    last_name = models.CharField(max_length=100)
    date_of_birth = models.DateField()
    gender = models.IntegerField(choices=Gender.choices, null=True, blank=True)

    # Many-to-many relationship with schools (through StudentSchoolEnrolment)
    schools = models.ManyToManyField(
        EmisSchool,
        through="StudentSchoolEnrolment",
        related_name="student_enrolments",
        blank=True,
    )

    # Audit fields
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="students_created",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    last_updated_at = models.DateTimeField(auto_now=True)
    last_updated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="students_updated",
    )

    if TYPE_CHECKING:
        # Type hint for the reverse relation from StudentSchoolEnrolment
        enrolments: "RelatedManager[StudentSchoolEnrolment]"

    class Meta:
        indexes = [
            models.Index(fields=["last_name", "first_name"]),
        ]
        ordering = ["last_name", "first_name"]

    def __str__(self):
        return f"{self.last_name}, {self.first_name}"

    @property
    def current_enrolments(self):
        """
        Get all currently active enrolments for this student.

        An enrolment is considered active if:
        - end_date is null (no end date set), OR
        - end_date is today or in the future

        Returns:
            QuerySet[StudentSchoolEnrolment]: Active enrolments
        """
        today = timezone.now().date()
        return self.enrolments.select_related(  # type: ignore[attr-defined]
            "school", "class_level", "school_year"
        ).filter(models.Q(end_date__isnull=True) | models.Q(end_date__gte=today))

    @property
    def current_school_names(self):
        """
        Get comma-separated list of current school names.

        Returns:
            str: School names joined by ", " or empty string if none
        """
        return ", ".join(e.school.emis_school_name for e in self.current_enrolments)


class StudentSchoolEnrolment(models.Model):
    """
    Student enrolment at a school for a specific school year.

    Tracks one student's enrolment at one school for one school year.
    Includes all CFT 1-20 disability indicator fields (Child Functioning Tool).

    The disability data lives here because it can vary by year/school.

    Attributes:
        student (Student): The student being enrolled
        school (EmisSchool): The school where enrolled
        school_year (EmisWarehouseYear): The school year for this enrolment
        class_level (EmisClassLevel): Student's class/grade level
        start_date (date): When enrolment began (optional)
        end_date (date): When enrolment ended (null = currently enrolled)
        cft1_wears_glasses through cft20_depressed_frequency: Disability indicator responses
        created_at (datetime): When this record was created
        created_by (User): Who created this record
        last_updated_at (datetime): When this record was last modified
        last_updated_by (User): Who last modified this record
    """

    student = models.ForeignKey(
        Student, on_delete=models.CASCADE, related_name="enrolments"
    )
    school = models.ForeignKey(
        EmisSchool, on_delete=models.PROTECT, related_name="enrolments"
    )
    school_year = models.ForeignKey(
        EmisWarehouseYear, on_delete=models.PROTECT, related_name="student_enrolments"
    )
    class_level = models.ForeignKey(
        EmisClassLevel,
        on_delete=models.PROTECT,
        related_name="student_enrolments",
        to_field="code",
    )

    # Enrolment date range
    start_date = models.DateField(null=True, blank=True)
    end_date = models.DateField(null=True, blank=True)

    # --- CFT 1–20: Child Functioning Tool disability indicators ---
    # NOTE: Question texts are in cft_meta.py for easy translation and UI display

    # CFT 1-3: Vision
    cft1_wears_glasses = models.IntegerField(
        null=True, blank=True, choices=YES_NO_CHOICES
    )
    cft2_difficulty_seeing_with_glasses = models.IntegerField(
        null=True, blank=True, choices=DIFFICULTY_CHOICES_4
    )
    cft3_difficulty_seeing = models.IntegerField(
        null=True, blank=True, choices=DIFFICULTY_CHOICES_4
    )

    # CFT 4-6: Hearing
    cft4_has_hearing_aids = models.IntegerField(
        null=True, blank=True, choices=YES_NO_CHOICES
    )
    cft5_difficulty_hearing_with_aids = models.IntegerField(
        null=True, blank=True, choices=DIFFICULTY_CHOICES_4
    )
    cft6_difficulty_hearing = models.IntegerField(
        null=True, blank=True, choices=DIFFICULTY_CHOICES_4
    )

    # CFT 7-11: Physical/Mobility
    cft7_uses_walking_equipment = models.IntegerField(
        null=True, blank=True, choices=YES_NO_CHOICES
    )
    cft8_difficulty_walking_without_equipment = models.IntegerField(
        null=True, blank=True, choices=DIFFICULTY_CHOICES_4
    )
    cft9_difficulty_walking_with_equipment = models.IntegerField(
        null=True, blank=True, choices=DIFFICULTY_CHOICES_4
    )
    cft10_difficulty_walking_compare_to_others = models.IntegerField(
        null=True, blank=True, choices=DIFFICULTY_CHOICES_4
    )
    cft11_difficulty_picking_up_small_objects = models.IntegerField(
        null=True, blank=True, choices=DIFFICULTY_CHOICES_4
    )

    # CFT 12: Communication
    cft12_difficulty_being_understood = models.IntegerField(
        null=True, blank=True, choices=DIFFICULTY_CHOICES_4
    )

    # CFT 13-16: Learning/Cognitive
    cft13_difficulty_learning = models.IntegerField(
        null=True, blank=True, choices=DIFFICULTY_CHOICES_4
    )
    cft14_difficulty_remembering = models.IntegerField(
        null=True, blank=True, choices=DIFFICULTY_CHOICES_4
    )
    cft15_difficulty_concentrating = models.IntegerField(
        null=True, blank=True, choices=DIFFICULTY_CHOICES_4
    )
    cft16_difficulty_accepting_change = models.IntegerField(
        null=True, blank=True, choices=DIFFICULTY_CHOICES_4
    )

    # CFT 17-18: Behavioral/Social
    cft17_difficulty_controlling_behaviour = models.IntegerField(
        null=True, blank=True, choices=DIFFICULTY_CHOICES_4
    )
    cft18_difficulty_making_friends = models.IntegerField(
        null=True, blank=True, choices=DIFFICULTY_CHOICES_4
    )

    # CFT 19-20: Emotional
    cft19_anxious_frequency = models.IntegerField(
        null=True, blank=True, choices=EMOTIONAL_FREQ_CHOICES_5
    )
    cft20_depressed_frequency = models.IntegerField(
        null=True, blank=True, choices=EMOTIONAL_FREQ_CHOICES_5
    )

    # Audit fields
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="student_enrolments_created",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    last_updated_at = models.DateTimeField(auto_now=True)
    last_updated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="student_enrolments_updated",
    )

    class Meta:
        # One row per (student, school, year) — prevents duplicate enrolments
        constraints = [
            models.UniqueConstraint(
                fields=["student", "school", "school_year"],
                name="uq_student_school_year",
            ),
        ]
        indexes = [
            models.Index(fields=["school", "school_year"]),
            models.Index(fields=["student", "school_year"]),
            models.Index(fields=["class_level"]),
        ]
        ordering = ["school_year__code", "school__emis_school_no", "student_id"]

    def __str__(self):
        return f"{self.student} @ {self.school} — {self.school_year}"

    @property
    def is_active(self):
        """
        Check if this enrolment is currently active.

        An enrolment is active if end_date is None or >= today.

        Returns:
            bool: True if active, False otherwise
        """
        today = timezone.now().date()
        return self.end_date is None or self.end_date >= today


# ============================================================================
# Permissions Anchor
# ============================================================================


class PermissionsAnchor(models.Model):
    """
    Dummy model that only exists to host app-level custom permissions.

    This model is not managed by Django (managed=False), so no database
    table is created. It only exists to define custom permissions that
    can be assigned to users/groups.
    """

    class Meta:
        managed = False
        default_permissions = ()
        verbose_name = "Disability-Inclusive Education app"
        verbose_name_plural = "Disability-Inclusive Education app"
        permissions = (
            (
                "access_app",
                "Can access the Disability-Inclusive Education app",
            ),
        )
