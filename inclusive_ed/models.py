from django.conf import settings
from django.contrib.postgres.indexes import GinIndex
from django.db import models
from django.utils import timezone
from django.utils.translation import gettext_lazy as _

from integrations.models import EmisSchool, EmisWarehouseYear, EmisClassLevel

class Student(models.Model):
    first_name = models.CharField(max_length=100)
    last_name = models.CharField(max_length=100)
    date_of_birth = models.DateField()

    # NEW: enrolments via through table
    schools = models.ManyToManyField(
        EmisSchool,
        through="StudentSchoolEnrolment",
        related_name="student_enrolments",
        blank=True,
    )

    # Audit
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True,
        on_delete=models.SET_NULL, related_name="students_created"
    )
    created_at = models.DateTimeField(auto_now_add=True)
    last_updated_at = models.DateTimeField(auto_now=True)
    last_updated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True,
        on_delete=models.SET_NULL, related_name="students_updated"
    )

    class Meta:
        indexes = [
            models.Index(fields=["last_name", "first_name"]),
        ]
        ordering = ["last_name", "first_name"]

    def __str__(self):
        return f"{self.last_name}, {self.first_name}"

    @property
    def current_enrolments(self):
        today = timezone.now().date()
        return self.enrolments.select_related("school", "class_level", "school_year").filter(
            models.Q(end_date__isnull=True) | models.Q(end_date__gte=today)
        )

    @property
    def current_school_names(self):
        return ", ".join(e.school.emis_school_name for e in self.current_enrolments)


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

class StudentSchoolEnrolment(models.Model):
    """
    One student enrolled in one school for one school_year (optionally with dates).
    All disability indicators and questionnaire 'answers' live here (they vary by year).
    """
    student = models.ForeignKey(
        Student, on_delete=models.CASCADE, related_name="enrolments"
    )
    school = models.ForeignKey(
        EmisSchool, on_delete=models.PROTECT, related_name="enrolments"
    )
    # If your WarehouseYear primary key is 'code' (e.g. '2024'), FK to it; adjust target if needed.
    school_year = models.ForeignKey(
        EmisWarehouseYear, on_delete=models.PROTECT, related_name="student_enrolments"
    )
    # Class level at this enrolment
    class_level = models.ForeignKey(
        EmisClassLevel, on_delete=models.PROTECT, related_name="student_enrolments",
        to_field="code"
    )

    # Enrolment start and end date for that school year
    start_date = models.DateField(null=True, blank=True)
    end_date = models.DateField(null=True, blank=True)

    # --- CFT 1–20: one field per question ---
    # NOTE: question texts are kept in a metadata structure below, not in help_text,
    # so they are easy to translate and easy to show in the UI.

    cft1_wears_glasses = models.IntegerField(
        null=True, blank=True, choices=YES_NO_CHOICES
    )
    cft2_difficulty_seeing_with_glasses = models.IntegerField(
        null=True, blank=True, choices=DIFFICULTY_CHOICES_4
    )
    cft3_difficulty_seeing = models.IntegerField(
        null=True, blank=True, choices=DIFFICULTY_CHOICES_4
    )
    cft4_has_hearing_aids = models.IntegerField(
        null=True, blank=True, choices=YES_NO_CHOICES
    )
    cft5_difficulty_hearing_with_aids = models.IntegerField(
        null=True, blank=True, choices=DIFFICULTY_CHOICES_4
    )
    cft6_difficulty_hearing = models.IntegerField(
        null=True, blank=True, choices=DIFFICULTY_CHOICES_4
    )
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
    cft12_difficulty_being_understood = models.IntegerField(
        null=True, blank=True, choices=DIFFICULTY_CHOICES_4
    )
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
    cft17_difficulty_controlling_behaviour = models.IntegerField(
        null=True, blank=True, choices=DIFFICULTY_CHOICES_4
    )
    cft18_difficulty_making_friends = models.IntegerField(
        null=True, blank=True, choices=DIFFICULTY_CHOICES_4
    )
    cft19_anxious_frequency = models.IntegerField(
        null=True, blank=True, choices=EMOTIONAL_FREQ_CHOICES_5
    )
    cft20_depressed_frequency = models.IntegerField(
        null=True, blank=True, choices=EMOTIONAL_FREQ_CHOICES_5
    )

    # Audit
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True,
        on_delete=models.SET_NULL, related_name="student_enrolments_created"
    )
    created_at = models.DateTimeField(auto_now_add=True)
    last_updated_at = models.DateTimeField(auto_now=True)
    last_updated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True,
        on_delete=models.SET_NULL, related_name="student_enrolments_updated"
    )

    class Meta:
        # One row per (student, school, year) — prevents dup enrolments in same year/school
        constraints = [
            models.UniqueConstraint(
                fields=["student", "school", "school_year"], name="uq_student_school_year"
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
        today = timezone.now().date()
        return self.end_date is None or self.end_date >= today

class PermissionsAnchor(models.Model):
    """
    Dummy model that only exists to host app-level custom permissions.
    """
    class Meta:
        managed = False
        default_permissions = ()
        verbose_name = "Disability-Inclusive Education app"
        verbose_name_plural = "Disability-Inclusive Education app"
        permissions = (
            ("access_inclusive_ed", "Can access the Disability-Inclusive Education app"),
        )
