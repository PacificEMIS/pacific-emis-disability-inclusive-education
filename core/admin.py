# core/admin.py
from django.contrib import admin
from django.contrib.auth import get_user_model
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin
from django.utils import timezone
from django.utils.html import format_html

from core.models import SchoolStaff, SchoolStaffAssignment, SystemUser, Student, StudentSchoolEnrolment
from core.mixins import CreatedUpdatedAuditMixin

User = get_user_model()


# ============================================================================
# Custom User Admin with Role Status
# ============================================================================


class HasRoleFilter(admin.SimpleListFilter):
    """Custom filter to show users by role assignment status."""

    title = "role assignment"
    parameter_name = "role"

    def lookups(self, request, model_admin):
        return (
            ("no_role", "No role assigned"),
            ("school_staff", "Has School Staff profile"),
            ("system_user", "Has System User profile"),
            ("both", "Has both profiles"),
        )

    def queryset(self, request, queryset):
        if self.value() == "no_role":
            return queryset.filter(school_staff__isnull=True, system_user__isnull=True)
        elif self.value() == "school_staff":
            return queryset.filter(school_staff__isnull=False)
        elif self.value() == "system_user":
            return queryset.filter(system_user__isnull=False)
        elif self.value() == "both":
            return queryset.filter(
                school_staff__isnull=False, system_user__isnull=False
            )
        return queryset


class CustomUserAdmin(BaseUserAdmin):
    """
    Custom User admin that helps manage role assignments.

    Adds filters to identify users without SchoolStaff or SystemUser profiles,
    making it easy for admins to assign roles to newly signed-up users.
    """

    list_display = (
        "username",
        "email",
        "first_name",
        "last_name",
        "is_staff",
        "is_active",
        "role_status",
        "date_joined",
    )
    list_filter = (
        HasRoleFilter,
        "is_staff",
        "is_superuser",
        "is_active",
        "groups",
        "date_joined",
    )

    def get_queryset(self, request):
        """Optimize queries by prefetching related profiles."""
        qs = super().get_queryset(request)
        return qs.select_related("school_staff", "system_user")

    def role_status(self, obj):
        """Display whether user has SchoolStaff, SystemUser, or no role assigned."""
        has_school_staff = hasattr(obj, "school_staff") and obj.school_staff is not None
        has_system_user = hasattr(obj, "system_user") and obj.system_user is not None

        if has_school_staff and has_system_user:
            return format_html('<span style="color: orange;">⚠ Both roles</span>')
        elif has_school_staff:
            return format_html('<span style="color: green;">✓ School Staff</span>')
        elif has_system_user:
            return format_html('<span style="color: blue;">✓ System User</span>')
        else:
            return format_html('<span style="color: red;">✗ No role</span>')

    role_status.short_description = "Role Status"


# Unregister the default User admin and register our custom one
admin.site.unregister(User)
admin.site.register(User, CustomUserAdmin)


# ============================================================================
# SchoolStaff Admin
# ============================================================================


class SchoolStaffAssignmentInline(admin.TabularInline):
    model = SchoolStaffAssignment
    fk_name = "school_staff"
    extra = 0
    show_change_link = True
    can_delete = True
    fields = (
        "school",
        "job_title",
        "start_date",
        "end_date",
        "active_now",
        "created_at",
        "created_by",
        "last_updated_at",
        "last_updated_by",
    )
    readonly_fields = (
        "active_now",
        "created_at",
        "created_by",
        "last_updated_at",
        "last_updated_by",
    )
    autocomplete_fields = ("school", "job_title")

    def active_now(self, obj):
        """Computed 'active' indicator based on start/end dates."""
        today = timezone.now().date()
        starts_ok = (obj.start_date is None) or (obj.start_date <= today)
        ends_ok = (obj.end_date is None) or (obj.end_date >= today)
        return bool(starts_ok and ends_ok)

    active_now.boolean = True
    active_now.short_description = "Active now"


@admin.register(SchoolStaff)
class SchoolStaffAdmin(CreatedUpdatedAuditMixin, admin.ModelAdmin):
    list_display = (
        "user",
        "staff_type",
        "created_at",
        "created_by",
        "last_updated_at",
        "last_updated_by",
    )
    search_fields = (
        "user__username",
        "user__email",
        "user__first_name",
        "user__last_name",
    )
    list_filter = ("staff_type",)
    inlines = [SchoolStaffAssignmentInline]
    readonly_fields = ("created_at", "created_by", "last_updated_at", "last_updated_by")


@admin.register(SystemUser)
class SystemUserAdmin(CreatedUpdatedAuditMixin, admin.ModelAdmin):
    list_display = (
        "user",
        "organization",
        "position_title",
        "created_at",
        "created_by",
        "last_updated_at",
        "last_updated_by",
    )
    search_fields = (
        "user__username",
        "user__email",
        "user__first_name",
        "user__last_name",
        "organization",
        "position_title",
    )
    list_filter = ("organization",)
    readonly_fields = ("created_at", "created_by", "last_updated_at", "last_updated_by")


# Ensure the standalone admin is not registered anymore
try:
    admin.site.unregister(SchoolStaffAssignment)
except admin.sites.NotRegistered:
    pass


# ============================================================================
# Student Admin
# ============================================================================


class StudentSchoolEnrolmentInline(admin.TabularInline):
    """Inline to edit a student's school/year enrolments (with 20 CFT disability fields)."""
    model = StudentSchoolEnrolment
    extra = 1
    show_change_link = True
    autocomplete_fields = ("school", "school_year", "class_level")

    fields = (
        "school",
        "school_year",
        "class_level",
        "start_date",
        "end_date",
        # CFT 1–20 fields
        "cft1_wears_glasses",
        "cft2_difficulty_seeing_with_glasses",
        "cft3_difficulty_seeing",
        "cft4_has_hearing_aids",
        "cft5_difficulty_hearing_with_aids",
        "cft6_difficulty_hearing",
        "cft7_uses_walking_equipment",
        "cft8_difficulty_walking_without_equipment",
        "cft9_difficulty_walking_with_equipment",
        "cft10_difficulty_walking_compare_to_others",
        "cft11_difficulty_picking_up_small_objects",
        "cft12_difficulty_being_understood",
        "cft13_difficulty_learning",
        "cft14_difficulty_remembering",
        "cft15_difficulty_concentrating",
        "cft16_difficulty_accepting_change",
        "cft17_difficulty_controlling_behaviour",
        "cft18_difficulty_making_friends",
        "cft19_anxious_frequency",
        "cft20_depressed_frequency",
        # audit
        "created_at",
        "created_by",
        "last_updated_at",
        "last_updated_by",
    )

    readonly_fields = (
        "created_at",
        "created_by",
        "last_updated_at",
        "last_updated_by",
    )


@admin.register(Student)
class StudentAdmin(CreatedUpdatedAuditMixin, admin.ModelAdmin):
    ordering = ("last_name", "first_name")
    search_fields = ("first_name", "last_name")
    # Filter by related enrolment fields
    list_filter = (
        ("enrolments__school", admin.RelatedOnlyFieldListFilter),
        ("enrolments__school_year", admin.RelatedOnlyFieldListFilter),
        ("enrolments__class_level", admin.RelatedOnlyFieldListFilter),
    )
    readonly_fields = ("created_at", "created_by", "last_updated_at", "last_updated_by")
    inlines = [StudentSchoolEnrolmentInline]

    list_display = (
        "first_name",
        "last_name",
        "date_of_birth",
        "current_school_names",
        "active_enrolments_count",
        "created_by",
        "created_at",
    )

    def current_school_names(self, obj):
        # Uses the @property current_enrolments you added on Student
        names = [e.school.emis_school_name for e in obj.current_enrolments]
        return ", ".join(names) if names else "—"

    current_school_names.short_description = "Current schools"

    def active_enrolments_count(self, obj):
        return obj.current_enrolments.count()

    active_enrolments_count.short_description = "Active enrolments"
