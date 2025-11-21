# accounts/admin.py
from django.contrib import admin
from django.utils import timezone
from accounts.models import Staff, StaffSchoolMembership
from accounts.mixins import CreatedUpdatedAuditMixin


class StaffSchoolMembershipInline(admin.TabularInline):
    model = StaffSchoolMembership
    fk_name = "staff"
    extra = 0
    show_change_link = True
    can_delete = True
    fields = (
        "school",
        "login_role",
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

    # If your model already has an is_active property/field, you can simply:
    # def active_now(self, obj): return getattr(obj, "is_active", False)

    def active_now(self, obj):
        """Computed 'active' indicator based on start/end dates."""
        today = timezone.now().date()
        starts_ok = (obj.start_date is None) or (obj.start_date <= today)
        ends_ok = (obj.end_date is None) or (obj.end_date >= today)
        return bool(starts_ok and ends_ok)

    active_now.boolean = True
    active_now.short_description = "Active now"


@admin.register(Staff)
class StaffAdmin(CreatedUpdatedAuditMixin, admin.ModelAdmin):
    list_display = (
        "user",
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
    inlines = [StaffSchoolMembershipInline]
    readonly_fields = ("created_at", "created_by", "last_updated_at", "last_updated_by")


# Ensure the standalone admin is not registered anymore
try:
    admin.site.unregister(StaffSchoolMembership)
except admin.sites.NotRegistered:
    pass

# Not needed stand alone
# @admin.register(StaffSchoolMembership)
# class StaffSchoolMembershipAdmin(CreatedUpdatedAuditMixin, admin.ModelAdmin):
#    list_display = ("staff", "school", "job_title", "login_role", "start_date", "end_date", "created_at", "created_by")
#    readonly_fields = ("created_at", "created_by")
#    autocomplete_fields = ("staff", "school", "job_title")
