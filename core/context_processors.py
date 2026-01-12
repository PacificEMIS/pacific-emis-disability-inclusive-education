"""
Context processors for core app.

Provides template context variables related to user profiles (SchoolStaff, SystemUser).
"""

from django.urls import reverse
from core.models import SchoolStaff, SystemUser
from core.permissions import is_admin, is_system_level_user, can_manage_pending_users


def staff_context(request):
    """
    Adds user_profile_url for linking to the user's own profile page.
    Checks for SchoolStaff, then SystemUser, then falls back to admin user page.

    Also adds:
    - is_admin_user: True for Admins or System Admins (general admin features)
    - can_manage_pending_users: True for Admins or System Admins (Pending Users management)
    - is_system_level_user: True for system-level users (Admins, System Admins, System Staff)
    """
    user = request.user
    context: dict[str, int | str | bool | None] = {
        "staff_pk_for_request_user": None,
        "system_user_pk_for_request_user": None,
        "user_profile_url": None,
        "is_admin_user": False,
        "can_manage_pending_users": False,
        "is_system_level_user": False,
    }

    if user.is_authenticated:
        # Check if user is an admin (for showing admin-only menu items)
        context["is_admin_user"] = is_admin(user)
        # Check if user can manage pending users (Admins or System Admins)
        context["can_manage_pending_users"] = can_manage_pending_users(user)
        # Check if user is a system-level user (for Staff UI visibility)
        context["is_system_level_user"] = is_system_level_user(user)
        # Check for SchoolStaff profile first
        try:
            staff = SchoolStaff.objects.only("pk").get(user=user)
            context["staff_pk_for_request_user"] = staff.pk
            context["user_profile_url"] = reverse(
                "core:staff_detail", kwargs={"pk": staff.pk}
            )
            return context
        except SchoolStaff.DoesNotExist:
            pass

        # Check for SystemUser profile
        try:
            system_user = SystemUser.objects.only("pk").get(user=user)
            context["system_user_pk_for_request_user"] = system_user.pk
            context["user_profile_url"] = reverse(
                "core:system_user_detail", kwargs={"pk": system_user.pk}
            )
            return context
        except SystemUser.DoesNotExist:
            pass

        # Fall back to admin user change page for superusers/staff without a profile
        if user.is_superuser or user.is_staff:
            context["user_profile_url"] = reverse(
                "admin:auth_user_change", args=[user.pk]
            )

    return context
