from django.conf import settings
from django.db import models
from django.utils import timezone

# Assuming these exist in integrations
from integrations.models import (
    EmisSchool,
    EmisJobTitle,
)  # adjust import if your lookup is elsewhere


class Staff(models.Model):
    """
    One Staff per auth user (extensible place for HR-ish attributes later).
    """

    user = models.OneToOneField(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="staff"
    )

    # Audit
    created_at = models.DateTimeField(auto_now_add=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="staff_created",
    )
    last_updated_at = models.DateTimeField(auto_now=True)
    last_updated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="staff_updated",
    )

    # Associations to schools live on the through model:
    schools = models.ManyToManyField(
        EmisSchool,
        through="StaffSchoolMembership",
        related_name="staff_members",
        blank=True,
    )

    class Meta:
        ordering = ["user_id"]

    def __str__(self):
        return f"Staff<{self.user}>"

    @property
    def active_memberships(self):
        today = timezone.now().date()
        return self.memberships.filter(
            models.Q(end_date__isnull=True) | models.Q(end_date__gte=today)
        )


class StaffSchoolMembership(models.Model):
    """
    Staff ↔ School association with role, job title, and validity window.
    """

    class LoginRole(models.TextChoices):
        TEACHER = "Teacher", "Teacher"
        ADMINISTRATOR = "Administrator", "Administrator"

    staff = models.ForeignKey(
        Staff, on_delete=models.CASCADE, related_name="memberships"
    )
    school = models.ForeignKey(
        EmisSchool, on_delete=models.PROTECT, related_name="memberships"
    )
    job_title = models.ForeignKey(
        EmisJobTitle, on_delete=models.PROTECT, related_name="staff_memberships"
    )
    login_role = models.CharField(max_length=32, choices=LoginRole.choices)

    start_date = models.DateField(null=True, blank=True)
    end_date = models.DateField(null=True, blank=True)

    # Audit
    created_at = models.DateTimeField(auto_now_add=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="staffschoolmembership_created",
    )
    last_updated_at = models.DateTimeField(auto_now=True)
    last_updated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="staffschoolmembership_updated",
    )

    class Meta:
        indexes = [
            models.Index(fields=["login_role"]),
            models.Index(fields=["start_date", "end_date"]),
        ]
        constraints = [
            models.UniqueConstraint(
                fields=["staff", "school", "start_date", "end_date", "login_role"],
                name="uq_membership_exact_tuple",
            ),
        ]
        ordering = ["staff_id", "school_id", "start_date"]

    def __str__(self):
        return f"{self.staff.user} @ {self.school} ({self.login_role})"

    @property
    def is_active(self):
        """
        Active if no end_date is set.
        Any end_date (past, present, or future) means inactive.
        """
        return self.end_date is None
