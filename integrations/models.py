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
    code = models.CharField(max_length=16, primary_key=True)   # from core.lookups.levels.C
    label = models.CharField(max_length=128)                   # from core.lookups.levels.N
    active = models.BooleanField(default=True)

    class Meta:
        ordering = ["code"]

    def __str__(self):
        return f"{self.code} — {self.label}"
