from django.db import models


class EmisSchool(models.Model):
    emis_school_no = models.CharField(max_length=32, primary_key=True)
    emis_school_name = models.CharField(max_length=255)
    active = models.BooleanField(default=True)

    class Meta:
        ordering = ["emis_school_no"]

    def __str__(self):
        return f"{self.emis_school_no} — {self.emis_school_name}"


class EmisClassLevel(models.Model):
    code = models.CharField(
        max_length=16, primary_key=True
    )  # from core.lookups.levels.C
    label = models.CharField(max_length=128)  # from core.lookups.levels.N
    active = models.BooleanField(default=True)

    class Meta:
        ordering = ["code"]

    def __str__(self):
        return f"{self.code} — {self.label}"


class EmisJobTitle(models.Model):
    """
    Lookup table for teacher roles / job titles.
    Mirrors core.lookups.teacherRoles.
    """

    code = models.CharField(
        max_length=16, primary_key=True
    )  # from core.lookups.teacherRoles.C
    label = models.CharField(max_length=128)  # from core.lookups.teacherRoles.N
    active = models.BooleanField(default=True)

    class Meta:
        ordering = ["code"]
        verbose_name = "Job Title"
        verbose_name_plural = "Job Titles"

    def __str__(self):
        return f"{self.code} — {self.label}"


class EmisWarehouseYear(models.Model):
    """
    Lookup table for warehouse years (with school year formatted)
    """

    code = models.CharField(
        max_length=16, primary_key=True
    )  # from core.lookups.warehouseYears.C
    label = models.CharField(
        max_length=128
    )  # from core.lookups.warehouseYears.FormattedYear
    active = models.BooleanField(default=True)

    class Meta:
        ordering = ["code"]
        verbose_name = "School Year"

    def __str__(self):
        return f"{self.label}"
