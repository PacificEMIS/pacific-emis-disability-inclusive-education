from django.conf import settings
from django.contrib.auth import authenticate, login, logout
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.shortcuts import render, redirect
from django.urls import reverse, NoReverseMatch


@login_required
def post_login_router(request):
    user = request.user
    if user.is_superuser or user.has_perm("core.access_app"):
        try:
            return redirect("core:dashboard")
        except NoReverseMatch:
            return redirect("accounts:no_permissions")
    return redirect("accounts:no_permissions")


@login_required
def no_permissions(request):
    support_email = getattr(settings, "APP_SUPPORT_EMAIL", None)
    return render(
        request, "accounts/no_permissions.html", {"support_email": support_email}
    )


def sign_in(request):
    if request.user.is_authenticated:
        return redirect("core:dashboard")

    if request.method == "POST":
        username = request.POST.get("username")
        password = request.POST.get("password")
        user = authenticate(request, username=username, password=password)
        if user is not None:
            login(request, user)
            next_url = request.POST.get("next") or request.GET.get("next")
            return redirect(next_url or reverse("core:dashboard"))
        messages.error(request, "Invalid username or password.")

    # preserve ?next=... if present
    return render(
        request,
        "accounts/login.html",
        {
            "next": request.GET.get("next", ""),
        },
    )


@login_required
def sign_out(request):
    logout(request)
    return redirect("accounts:login")


def permission_denied_view(request, exception=None):
    """
    Custom 403 handler that renders a styled forbidden page.
    """
    return render(request, "accounts/forbidden.html", status=403)
