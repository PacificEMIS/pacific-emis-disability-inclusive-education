from django.contrib import admin
from .models import TeacherAssignment

@admin.register(TeacherAssignment)
class TeacherAssignmentAdmin(admin.ModelAdmin):
    list_display = ("user", "emis_school_no", "emis_school_name", "is_active", "created_at")
    list_filter = ("is_active",)
    search_fields = ("user__username", "user__email", "emis_school_no", "emis_school_name")
