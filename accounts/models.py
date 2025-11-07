from django.conf import settings
from django.db import models

class TeacherAssignment(models.Model):
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    emis_school_no = models.CharField(max_length=32)
    emis_school_name = models.CharField(max_length=255, blank=True, default="")
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True,
        on_delete=models.SET_NULL, related_name="teacherassignment_created"
    )

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["user", "emis_school_no"], name="uq_teacher_school_once"
            )
        ]
        indexes = [
            models.Index(fields=["emis_school_no"]),
            models.Index(fields=["is_active"]),
        ]
        ordering = ["user_id", "emis_school_no"]

    def __str__(self):
        return f"{self.user} → {self.emis_school_no}"
