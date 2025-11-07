from django.contrib import admin
from .models import EmisSchool, EmisClassLevel

@admin.register(EmisSchool)
class EmisSchoolAdmin(admin.ModelAdmin):
    list_display = ("emis_school_no", "emis_school_name", "active")
    search_fields = ("emis_school_no", "emis_school_name")
    list_filter = ("active",)

@admin.register(EmisClassLevel)
class EmisClassLevelAdmin(admin.ModelAdmin):
    list_display = ("code", "label", "active")
    search_fields = ("code", "label")
    list_filter = ("active",)
