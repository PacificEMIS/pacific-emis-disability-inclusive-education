"""
Middleware for core app.

Provides app-level access control to ensure only users with proper
profiles and group memberships can access the application.
"""
from django.shortcuts import redirect
from django.urls import reverse

from core.permissions import has_app_access


class AppAccessMiddleware:
    """
    Middleware that enforces app-level access control.

    Users must have:
    1. Authentication (handled by @login_required)
    2. Profile (SchoolStaff OR SystemUser)
    3. Group membership (at least one group)

    Without all three, users are redirected to the no_permissions page.

    This middleware only applies to URLs under the 'core' namespace.
    """

    # URL names that should be exempt from access checks
    EXEMPT_URL_NAMES = {
        "accounts:login",
        "accounts:logout",
        "accounts:no_permissions",
        "accounts:post_login_router",
    }

    # URL path prefixes that should be exempt
    EXEMPT_PATH_PREFIXES = (
        "/accounts/",
        "/admin/",
        "/__debug__/",
        "/static/",
        "/media/",
    )

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        # Skip for unauthenticated users (let @login_required handle it)
        if not request.user.is_authenticated:
            return self.get_response(request)

        # Skip for exempt paths
        path = request.path
        if any(path.startswith(prefix) for prefix in self.EXEMPT_PATH_PREFIXES):
            return self.get_response(request)

        # Check if user has app access
        if not has_app_access(request.user):
            # Redirect to no_permissions page
            no_perms_url = reverse("accounts:no_permissions")
            # Avoid redirect loop
            if path != no_perms_url:
                return redirect(no_perms_url)

        return self.get_response(request)
