from django.conf import settings
from django.contrib.auth import authenticate, login, logout
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.core.paginator import Paginator
from django.db.models import Q, Prefetch, OuterRef, Subquery
from django.shortcuts import render, redirect, get_object_or_404
from django.urls import reverse, NoReverseMatch
from django.utils.text import capfirst

from accounts.models import Staff, StaffSchoolMembership
from accounts.forms import StaffSchoolMembershipForm
from integrations.models import EmisSchool


PAGE_SIZE_OPTIONS = [10, 25, 50, 100]

SPECIAL_PERMISSIONS = {
    # codename: (bucket_key, human_model_label)
    "access_inclusive_ed": ("access", "Disability-Inclusive Education app"),
}


def _summarize_permissions(perms_queryset):
    """
    Group permissions into action buckets (view/add/change/delete/access/other)
    and return a list of sections ready for templates, e.g.:

    [
      {"key": "view", "label": "View", "models": ["Staff", "School"]},
      {"key": "access", "label": "Access", "models": ["Disability-Inclusive Education app"]},
      ...
    ]
    """
    buckets = {
        "view": set(),
        "add": set(),
        "change": set(),
        "delete": set(),
        "access": set(),  # for app-level access perms
        "other": set(),
    }

    # Preload content_type for efficiency
    perms = perms_queryset.select_related("content_type")

    for p in perms:
        codename = p.codename

        # 1) Check for special/app-level custom permissions
        special = SPECIAL_PERMISSIONS.get(codename)
        if special is not None:
            bucket_key, model_label = special
            buckets[bucket_key].add(model_label)
            continue

        # 2) Standard Django model perms: view/add/change/delete_*
        action_key = "other"
        for action in ("view", "add", "change", "delete"):
            if codename.startswith(f"{action}_"):
                action_key = action
                break

        # 3) Use the model's verbose_name when available
        model_class = p.content_type.model_class()
        if model_class is not None:
            model_label = capfirst(model_class._meta.verbose_name)
        else:
            model_label = capfirst(p.content_type.model.replace("_", " "))

        buckets[action_key].add(model_label)

    labels = {
        "view": "View",
        "add": "Add",
        "change": "Change",
        "delete": "Delete",
        "access": "Access",
        "other": "Other",
    }

    sections = []
    for key in ("view", "add", "change", "delete", "access", "other"):
        models = sorted(buckets[key])
        if models:
            sections.append(
                {
                    "key": key,
                    "label": labels[key],
                    "models": models,
                }
            )
    return sections


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
    return render(
        request, "accounts/no_permissions.html", {"support_email": support_email}
    )


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

    emis_context = (
        settings.EMIS.get("CONTEXT") if getattr(settings, "EMIS", None) else None
    )
    # preserve ?next=... if present
    return render(
        request,
        "accounts/login.html",
        {
            "next": request.GET.get("next", ""),
            "emis_context": emis_context,
        },
    )


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

    # Filters
    school_filter = (
        request.GET.get("school") or ""
    ).strip()  # EmisSchool.emis_school_no
    email_filter = (request.GET.get("email") or "").strip()

    # Sorting
    sort = (request.GET.get("sort") or "").strip().lower()
    dir_ = (request.GET.get("dir") or "asc").strip().lower()
    dir_ = "desc" if dir_ == "desc" else "asc"  # sanitize

    # Per-page
    try:
        per_page = int(request.GET.get("per_page", 25))
    except ValueError:
        per_page = 25
    if per_page not in PAGE_SIZE_OPTIONS:
        per_page = 25

    # Picklists (active only; adjust if you want all)
    schools = EmisSchool.objects.filter(active=True).order_by("emis_school_no")

    # ---- Latest membership subqueries (for "current appointment" + filtering/sorting helper)
    membership_qs = StaffSchoolMembership.objects.filter(staff=OuterRef("pk")).order_by(
        "-id"
    )  # most recently created membership; simple + robust

    latest_school_no = Subquery(membership_qs.values("school__emis_school_no")[:1])
    latest_school_name = Subquery(membership_qs.values("school__emis_school_name")[:1])

    staff_qs = (
        Staff.objects.select_related("user")
        .annotate(
            latest_school_no=latest_school_no,
            latest_school_name=latest_school_name,
        )
        .prefetch_related(
            Prefetch(
                "memberships",
                queryset=StaffSchoolMembership.objects.select_related(
                    "school", "job_title"
                ),
            )
        )
    )

    # Search by name
    if q:
        staff_qs = staff_qs.filter(
            Q(user__first_name__icontains=q) | Q(user__last_name__icontains=q)
        )

    # Search by email
    if email_filter:
        staff_qs = staff_qs.filter(user__email__icontains=email_filter)

    # Filter by school (any membership at that school)
    if school_filter:
        staff_qs = staff_qs.filter(
            memberships__school__emis_school_no=school_filter
        ).distinct()

    # Sorting map: align with table columns: Name, Email, Current Appointment
    sort_map = {
        "name": ("user__last_name", "user__first_name"),
        "email": ("user__email", "user__last_name", "user__first_name"),
        "appointment": (
            "latest_school_name",
            "latest_school_no",
            "user__last_name",
            "user__first_name",
        ),
    }

    if sort in sort_map:
        order_fields = sort_map[sort]
        if dir_ == "desc":
            order_fields = tuple(f"-{f}" for f in order_fields)
        staff_qs = staff_qs.order_by(*order_fields)
    else:
        # Default ordering by name
        staff_qs = staff_qs.order_by("user__last_name", "user__first_name")

    # Pagination
    paginator = Paginator(staff_qs, per_page)
    page_number = request.GET.get("page") or 1
    page_obj = paginator.get_page(page_number)

    return render(
        request,
        "accounts/staff_list.html",
        {
            "active": "staff",
            "page_obj": page_obj,
            "q": q,
            "per_page": per_page,
            "page_size_options": PAGE_SIZE_OPTIONS,
            "page_links": _page_window(page_obj),
            # filters + lists
            "school": school_filter,
            "email": email_filter,
            "schools": schools,
            # sorting
            "sort": sort,
            "dir": dir_,
        },
    )


@login_required
def staff_detail(request, pk):
    staff = get_object_or_404(
        Staff.objects.select_related("user").prefetch_related(
            "memberships__school",
            "memberships__job_title",
            "memberships__created_by",
            "memberships__last_updated_by",
            "user__groups__permissions",
            "user__user_permissions",
        ),
        pk=pk,
    )

    # Permission: who can add memberships?
    can_add_membership = request.user.is_superuser or request.user.has_perm(
        "accounts.add_staffschoolmembership"
    )

    membership_form = (
        StaffSchoolMembershipForm(request.POST or None) if can_add_membership else None
    )

    if request.method == "POST":
        if not can_add_membership:
            messages.error(
                request, "You do not have permission to add school memberships."
            )
        elif membership_form.is_valid():
            obj = membership_form.save(commit=False)
            obj.staff = staff

            # audit fields (if defined on the model)
            if hasattr(obj, "created_by_id") and obj.created_by_id is None:
                obj.created_by = request.user
            if hasattr(obj, "last_updated_by_id") and obj.last_updated_by_id is None:
                obj.last_updated_by = request.user

            obj.save()
            messages.success(request, "School membership added.")
            return redirect("accounts:staff_detail", pk=staff.pk)

    user_obj = staff.user

    groups = (
        user_obj.groups.all()
        .prefetch_related("permissions__content_type")
        .order_by("name")
    )

    group_permissions = []
    for g in groups:
        group_permissions.append(
            {
                "group": g,
                "sections": _summarize_permissions(g.permissions.all()),
            }
        )

    direct_permission_sections = _summarize_permissions(
        user_obj.user_permissions.all().select_related("content_type")
    )

    context = {
        "staff": staff,
        "active": "staff",
        "membership_form": membership_form,
        "can_add_membership": can_add_membership,
        "group_permissions": group_permissions,
        "direct_permission_sections": direct_permission_sections,
    }
    return render(request, "accounts/staff_detail.html", context)


@login_required
def staff_membership_edit(request, staff_id, pk):
    """
    Edit an existing StaffSchoolMembership for a given staff member.
    """
    staff = get_object_or_404(Staff, pk=staff_id)
    membership = get_object_or_404(
        StaffSchoolMembership,
        pk=pk,
        staff=staff,
    )

    can_edit = request.user.is_superuser or request.user.has_perm(
        "accounts.change_staffschoolmembership"
    )
    if not can_edit:
        messages.error(
            request, "You do not have permission to edit school memberships."
        )
        return redirect("accounts:staff_detail", pk=staff.pk)

    if request.method == "POST":
        form = StaffSchoolMembershipForm(request.POST, instance=membership)
        if form.is_valid():
            obj = form.save(commit=False)

            # Audit: stamp last_updated_by if field exists
            if hasattr(obj, "last_updated_by_id"):
                obj.last_updated_by = request.user

            obj.save()
            messages.success(request, "School membership updated.")
            return redirect("accounts:staff_detail", pk=staff.pk)
    else:
        form = StaffSchoolMembershipForm(instance=membership)

    context = {
        "active": "staff",
        "staff": staff,
        "membership": membership,
        "form": form,
    }
    return render(request, "accounts/staff_membership_edit.html", context)


@login_required
def staff_membership_delete(request, staff_id, pk):
    """
    Confirm and delete a StaffSchoolMembership for a given staff member.
    """
    staff = get_object_or_404(Staff, pk=staff_id)
    membership = get_object_or_404(
        StaffSchoolMembership,
        pk=pk,
        staff=staff,
    )

    can_delete = request.user.is_superuser or request.user.has_perm(
        "accounts.delete_staffschoolmembership"
    )
    if not can_delete:
        messages.error(
            request, "You do not have permission to delete school memberships."
        )
        return redirect("accounts:staff_detail", pk=staff.pk)

    if request.method == "POST":
        membership.delete()
        messages.success(request, "School membership deleted.")
        return redirect("accounts:staff_detail", pk=staff.pk)

    context = {
        "active": "staff",
        "staff": staff,
        "membership": membership,
    }
    return render(request, "accounts/staff_membership_confirm_delete.html", context)
