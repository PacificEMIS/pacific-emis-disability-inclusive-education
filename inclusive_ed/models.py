from django.conf import settings
from django.db import models
from django.utils import timezone
from django.contrib.postgres.indexes import GinIndex

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

    # Optional date window (useful for within-year moves)
    start_date = models.DateField(null=True, blank=True)
    end_date = models.DateField(null=True, blank=True)

    # Questionnaire + disability flags (moved from Student)
    answers = models.JSONField(default=dict, blank=True)
    seeing_flag = models.BooleanField(null=True, blank=True)
    hearing_flag = models.BooleanField(null=True, blank=True)
    mobility_flag = models.BooleanField(null=True, blank=True)
    fine_motor_flag = models.BooleanField(null=True, blank=True)
    speech_flag = models.BooleanField(null=True, blank=True)
    learning_flag = models.BooleanField(null=True, blank=True)
    memory_flag = models.BooleanField(null=True, blank=True)
    attention_flag = models.BooleanField(null=True, blank=True)
    behaviour_flag = models.BooleanField(null=True, blank=True)
    social_flag = models.BooleanField(null=True, blank=True)
    anxiety_freq = models.IntegerField(null=True, blank=True)
    depression_freq = models.IntegerField(null=True, blank=True)

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
            GinIndex(fields=["answers"]),
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
        permissions = (
            ("access_inclusive_ed", "Can access the Disability-Inclusive Education app"),
        )