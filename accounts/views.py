from django.conf import settings
from django.contrib.auth import authenticate, login, logout
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.core.paginator import Paginator
from django.db.models import Q, Prefetch
from django.shortcuts import render, redirect
from django.urls import reverse, NoReverseMatch

from accounts.models import Staff, StaffSchoolMembership

@login_required
def post_login_router(request):
    user = request.user
    if user.is_superuser or user.has_perm("inclusive_ed.access_inclusive_ed"):
        try:
            return redirect("inclusive_ed:dashboard")
        except NoReverseMatch:
            return redirect("accounts:no_permissions")
    return redirect("accounts:no_permissions")

@login_required
def no_permissions(request):
    support_email = getattr(settings, "APP_SUPPORT_EMAIL", None)
    return render(request, "accounts/no_permissions.html", {"support_email": support_email})

def sign_in(request):
    if request.user.is_authenticated:
        return redirect("inclusive_ed:dashboard")

    if request.method == "POST":
        username = request.POST.get("username")
        password = request.POST.get("password")
        user = authenticate(request, username=username, password=password)
        if user is not None:
            login(request, user)
            next_url = request.POST.get("next") or request.GET.get("next")
            return redirect(next_url or reverse("inclusive_ed:dashboard"))
        messages.error(request, "Invalid username or password.")

    # preserve ?next=... if present
    return render(request, "accounts/login.html", {"next": request.GET.get("next", "")})

@login_required
def sign_out(request):
    logout(request)
    return redirect("accounts:login")

def _page_window(page_obj, radius=2, edges=2):
    """
    Build a compact pagination window like:
    1 2 … 8 9 10 11 12 … 29 30
    Returns a list of ints and '…' strings.
    """
    total = page_obj.paginator.num_pages
    current = page_obj.number
    pages = set()

    # edges
    for p in range(1, min(edges, total) + 1):
        pages.add(p)
    for p in range(max(1, total - edges + 1), total + 1):
        pages.add(p)

    # window around current
    for p in range(current - radius, current + radius + 1):
        if 1 <= p <= total:
            pages.add(p)

    pages = sorted(pages)
    window = []
    prev = 0
    for p in pages:
        if prev and p != prev + 1:
            window.append("…")
        window.append(p)
        prev = p
    return window

@login_required
def staff_list(request):
    q = (request.GET.get("q") or "").strip()
    per_page = int(request.GET.get("per_page", 25))

    staff_qs = Staff.objects.select_related("user")
    if q:
        staff_qs = staff_qs.filter(
            Q(user__username__icontains=q) |
            Q(user__first_name__icontains=q) |
            Q(user__last_name__icontains=q) |
            Q(user__email__icontains=q)
        )

    memberships_qs = StaffSchoolMembership.objects.select_related("school", "job_title")
    staff_qs = staff_qs.prefetch_related(Prefetch("memberships", queryset=memberships_qs))

    paginator = Paginator(staff_qs.order_by("user__last_name", "user__first_name"), per_page)
    page_obj = paginator.get_page(request.GET.get("page"))

    return render(
        request,
        "accounts/staff_list.html",
        {
            "active": "staff",
            "page_obj": page_obj,
            "q": q,
            "per_page": per_page,
            "page_size_options": [10, 25, 50, 100],
            "page_links": _page_window(page_obj),
        },
    )