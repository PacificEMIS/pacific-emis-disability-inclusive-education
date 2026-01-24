"""
Views for core models (SchoolStaff, SystemUser, Student, StudentSchoolEnrolment).

Provides CRUD views for managing school staff, their assignments, and students.
"""
from datetime import timedelta

from django.utils import timezone
from django.utils.dateparse import parse_date
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.core.paginator import Paginator
from django.core.exceptions import PermissionDenied
from django.db import IntegrityError, transaction
from django.db.models import Q, Prefetch, OuterRef, Subquery, F
from django.http import JsonResponse
from django.shortcuts import render, redirect, get_object_or_404
from django.urls import reverse
from django.utils.text import capfirst

import logging

logger = logging.getLogger(__name__)

from rapidfuzz import fuzz

from core.models import SchoolStaff, SchoolStaffAssignment, Student, StudentSchoolEnrolment, SystemUser
from core.forms import (
    SchoolStaffAssignmentForm,
    SchoolStaffEditForm,
    StudentCoreForm,
    StudentDisabilityIntakeForm,
    StudentEnrolmentForm,
    SystemUserEditForm,
)
from core.cft_meta import CFT_QUESTION_META, build_cft_meta_for_name
from core.emails import send_student_created_email_async
from core.permissions import (
    filter_staff_for_user,
    can_view_staff,
    can_edit_staff,
    can_edit_staff_groups,
    can_create_staff_assignment,
    can_edit_staff_assignment,
    can_delete_staff_assignment,
    can_create_student,
    can_view_student,
    filter_students_for_user,
    can_edit_student,
    can_delete_student,
    get_allowed_enrolment_schools,
    is_system_level_user,
    is_admins_group,
    is_school_admin,
    can_edit_system_user,
    can_edit_system_user_groups,
    GROUP_SYSTEM_ADMINS,
    _in_group,
)
from integrations.models import EmisSchool, EmisClassLevel, EmisWarehouseYear


PAGE_SIZE_OPTIONS = [10, 25, 50, 100]

SPECIAL_PERMISSIONS = {
    # codename: (bucket_key, human_model_label)
    "access_app": ("access", "Disability-Inclusive Education app"),
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
    schools = EmisSchool.objects.filter(active=True).order_by("emis_school_name")

    # ---- Latest assignment subqueries (for "current appointment" + filtering/sorting helper)
    assignment_qs = SchoolStaffAssignment.objects.filter(school_staff=OuterRef("pk")).order_by(
        "-id"
    )  # most recently created assignment; simple + robust

    latest_school_no = Subquery(assignment_qs.values("school__emis_school_no")[:1])
    latest_school_name = Subquery(assignment_qs.values("school__emis_school_name")[:1])

    staff_qs = (
        SchoolStaff.objects.select_related("user")
        .annotate(
            latest_school_no=latest_school_no,
            latest_school_name=latest_school_name,
        )
        .prefetch_related(
            Prefetch(
                "assignments",
                queryset=SchoolStaffAssignment.objects.select_related(
                    "school", "job_title"
                ),
            ),
            "user__groups",  # Prefetch groups for display in list
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

    # Filter by school (any assignment at that school)
    if school_filter:
        staff_qs = staff_qs.filter(
            assignments__school__emis_school_no=school_filter
        ).distinct()

    # Apply row-level permissions
    staff_qs = filter_staff_for_user(staff_qs, request.user)

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

    # Check if user can edit staff (for showing Edit buttons)
    # Superusers, Admins, System Admins, and School Admins can edit
    user_can_edit = (
        request.user.is_superuser
        or is_admins_group(request.user)
        or _in_group(request.user, GROUP_SYSTEM_ADMINS)
        or is_school_admin(request.user)
    )

    return render(
        request,
        "core/staff_list.html",
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
            # permissions
            "user_can_edit": user_can_edit,
        },
    )


@login_required
def staff_detail(request, pk):
    staff = get_object_or_404(
        SchoolStaff.objects.select_related("user").prefetch_related(
            "assignments__school",
            "assignments__job_title",
            "assignments__created_by",
            "assignments__last_updated_by",
            "user__groups__permissions",
            "user__user_permissions",
        ),
        pk=pk,
    )

    # Permission: can this user view this staff member?
    if not can_view_staff(request.user, staff):
        messages.error(request, "You do not have permission to view this staff member.")
        return redirect("core:staff_list")

    # Permission: who can add assignments?
    can_add_assignment = can_create_staff_assignment(request.user)

    assignment_form = (
        SchoolStaffAssignmentForm(request.POST or None, user=request.user)
        if can_add_assignment
        else None
    )

    if request.method == "POST":
        if not can_create_staff_assignment(request.user):
            messages.error(
                request, "You do not have permission to add school assignments."
            )
        elif assignment_form.is_valid():
            obj = assignment_form.save(commit=False)
            obj.school_staff = staff

            # Additional validation: School Admins can only create assignments for their schools
            if not can_create_staff_assignment(request.user, obj.school):
                messages.error(
                    request,
                    f"You do not have permission to create assignments for {obj.school.emis_school_name}.",
                )
            else:
                # audit fields (if defined on the model)
                if hasattr(obj, "created_by_id") and obj.created_by_id is None:
                    obj.created_by = request.user
                if hasattr(obj, "last_updated_by_id") and obj.last_updated_by_id is None:
                    obj.last_updated_by = request.user

                obj.save()
                messages.success(request, "School assignment added.")
                return redirect("core:staff_detail", pk=staff.pk)

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

    # Build per-assignment edit/delete permissions for template
    assignment_permissions = {}
    for assignment in staff.assignments.all():
        assignment_permissions[assignment.pk] = {
            "can_edit": can_edit_staff_assignment(request.user, assignment),
            "can_delete": can_delete_staff_assignment(request.user, assignment),
        }

    context = {
        "staff": staff,
        "active": "staff",
        "assignment_form": assignment_form,
        "can_add_assignment": can_add_assignment,
        "can_edit": can_edit_staff(request.user, staff),
        "assignment_permissions": assignment_permissions,
        "group_permissions": group_permissions,
        "direct_permission_sections": direct_permission_sections,
    }
    return render(request, "core/staff_detail.html", context)


@login_required
def staff_assignment_edit(request, staff_id, pk):
    """
    Edit an existing SchoolStaffAssignment for a given staff member.
    """
    staff = get_object_or_404(SchoolStaff, pk=staff_id)
    assignment = get_object_or_404(
        SchoolStaffAssignment,
        pk=pk,
        school_staff=staff,
    )

    # Permission: check if user can edit this specific assignment
    if not can_edit_staff_assignment(request.user, assignment):
        messages.error(
            request, "You do not have permission to edit this school assignment."
        )
        return redirect("core:staff_detail", pk=staff.pk)

    if request.method == "POST":
        form = SchoolStaffAssignmentForm(
            request.POST, instance=assignment, user=request.user
        )
        if form.is_valid():
            obj = form.save(commit=False)

            # Additional validation: ensure school hasn't changed to one outside user's scope
            if not can_create_staff_assignment(request.user, obj.school):
                messages.error(
                    request,
                    f"You do not have permission to assign assignments for {obj.school.emis_school_name}.",
                )
            else:
                # Audit: stamp last_updated_by if field exists
                if hasattr(obj, "last_updated_by_id"):
                    obj.last_updated_by = request.user

                obj.save()
                messages.success(request, "School assignment updated.")
                return redirect("core:staff_detail", pk=staff.pk)
    else:
        form = SchoolStaffAssignmentForm(instance=assignment, user=request.user)

    context = {
        "active": "staff",
        "staff": staff,
        "assignment": assignment,
        "form": form,
    }
    return render(request, "core/staff_assignment_edit.html", context)


@login_required
def staff_assignment_delete(request, staff_id, pk):
    """
    Confirm and delete a SchoolStaffAssignment for a given staff member.
    """
    staff = get_object_or_404(SchoolStaff, pk=staff_id)
    assignment = get_object_or_404(
        SchoolStaffAssignment,
        pk=pk,
        school_staff=staff,
    )

    # Permission: check if user can delete this specific assignment
    if not can_delete_staff_assignment(request.user, assignment):
        messages.error(
            request, "You do not have permission to delete this school assignment."
        )
        return redirect("core:staff_detail", pk=staff.pk)

    if request.method == "POST":
        assignment.delete()
        messages.success(request, "School assignment deleted.")
        return redirect("core:staff_detail", pk=staff.pk)

    context = {
        "active": "staff",
        "staff": staff,
        "assignment": assignment,
    }
    return render(request, "core/staff_assignment_confirm_delete.html", context)


@login_required
def staff_edit(request, pk):
    """
    Edit a school staff member's profile (staff_type) and group memberships.

    Permissions:
    - Django Super Users: full access (all fields including groups)
    - Admins group: full access (all fields including groups)
    - School Admins group: can edit staff_type, but NOT groups
      (must have school access to the staff member)
    """
    staff = get_object_or_404(
        SchoolStaff.objects.select_related("user", "created_by", "last_updated_by"),
        pk=pk,
    )

    # Check edit permission
    if not can_edit_staff(request.user, staff):
        messages.error(request, "You do not have permission to edit this staff member.")
        return redirect("core:staff_detail", pk=pk)

    # Determine if user can edit groups
    can_edit_groups = can_edit_staff_groups(request.user, staff)

    if request.method == "POST":
        form = SchoolStaffEditForm(
            request.POST,
            user=request.user,
            school_staff=staff,
        )
        if form.is_valid():
            # Update SchoolStaff fields
            staff.staff_type = form.cleaned_data["staff_type"]
            staff.last_updated_by = request.user
            staff.save()

            # Update groups only if user has permission
            if can_edit_groups:
                new_groups = form.cleaned_data["groups"]
                # Only update school-level groups, preserve any other groups
                school_groups = ["Admins", "School Admins", "School Staff", "Teachers"]
                # Remove old school-level groups
                staff.user.groups.remove(
                    *staff.user.groups.filter(name__in=school_groups)
                )
                # Add new groups
                staff.user.groups.add(*new_groups)

            messages.success(
                request,
                f"Staff member {staff.user.get_full_name() or staff.user.username} updated successfully.",
            )
            return redirect("core:staff_detail", pk=pk)
    else:
        form = SchoolStaffEditForm(
            user=request.user,
            school_staff=staff,
        )

    context = {
        "staff": staff,
        "form": form,
        "can_edit_groups": can_edit_groups,
        "active": "staff",
    }
    return render(request, "core/staff_edit.html", context)


# ============================================================================
# System User views
# ============================================================================


@login_required
def system_user_list(request):
    """
    List all system users with search, filtering, and sorting capabilities.

    Query parameters:
        q: Search by name
        email: Filter by email
        organization: Filter by organization
        sort: Sort field (name, email, organization)
        dir: Sort direction (asc/desc)
        per_page: Number of results per page
        page: Current page number
    """
    # Only system-level users can access staff UI
    if not is_system_level_user(request.user):
        raise PermissionDenied

    q = (request.GET.get("q") or "").strip()

    # Filters
    email_filter = (request.GET.get("email") or "").strip()
    organization_filter = (request.GET.get("organization") or "").strip()

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

    # Base queryset
    system_users_qs = SystemUser.objects.select_related("user")

    # Search by name
    if q:
        system_users_qs = system_users_qs.filter(
            Q(user__first_name__icontains=q) | Q(user__last_name__icontains=q)
        )

    # Search by email
    if email_filter:
        system_users_qs = system_users_qs.filter(user__email__icontains=email_filter)

    # Filter by organization
    if organization_filter:
        system_users_qs = system_users_qs.filter(organization__icontains=organization_filter)

    # Sorting map
    sort_map = {
        "name": ("user__last_name", "user__first_name"),
        "email": ("user__email", "user__last_name", "user__first_name"),
        "organization": ("organization", "user__last_name", "user__first_name"),
    }

    if sort in sort_map:
        order_fields = sort_map[sort]
        if dir_ == "desc":
            order_fields = tuple(f"-{f}" for f in order_fields)
        system_users_qs = system_users_qs.order_by(*order_fields)
    else:
        # Default ordering by name
        system_users_qs = system_users_qs.order_by("user__last_name", "user__first_name")

    # Pagination
    paginator = Paginator(system_users_qs, per_page)
    page_number = request.GET.get("page") or 1
    page_obj = paginator.get_page(page_number)

    # Check if user can edit any system user (for showing Edit buttons)
    # This is a simple check - user must be superuser, Admins, or System Admins
    user_can_edit = (
        request.user.is_superuser
        or request.user.groups.filter(name__in=["Admins", "System Admins"]).exists()
    )

    return render(
        request,
        "core/system_user_list.html",
        {
            "active": "system_users",
            "page_obj": page_obj,
            "q": q,
            "per_page": per_page,
            "page_size_options": PAGE_SIZE_OPTIONS,
            "page_links": _page_window(page_obj),
            # filters
            "email": email_filter,
            "organization": organization_filter,
            # sorting
            "sort": sort,
            "dir": dir_,
            # permissions
            "user_can_edit": user_can_edit,
        },
    )


@login_required
def system_user_detail(request, pk):
    """
    Display detailed information for a single system user.

    Shows:
    - User account details
    - Organization and position
    - Groups and permissions
    - Audit information
    """
    # Only system-level users can access staff UI
    if not is_system_level_user(request.user):
        raise PermissionDenied

    system_user = get_object_or_404(
        SystemUser.objects.select_related("user", "created_by", "last_updated_by").prefetch_related(
            "user__groups__permissions",
            "user__user_permissions",
        ),
        pk=pk,
    )

    user_obj = system_user.user

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
        "system_user": system_user,
        "active": "system_users",
        "group_permissions": group_permissions,
        "direct_permission_sections": direct_permission_sections,
        "can_edit": can_edit_system_user(request.user, system_user),
    }
    return render(request, "core/system_user_detail.html", context)


@login_required
def system_user_edit(request, pk):
    """
    Edit a system user's organization, position, and group memberships.

    Permissions:
    - Django Super Users: full access (all fields including groups)
    - Admins group: full access (all fields including groups)
    - System Admins group: can edit organization/position, but NOT groups
    - System Staff group: read-only, no edit access
    """
    # Check system-level access first
    if not is_system_level_user(request.user):
        raise PermissionDenied

    system_user = get_object_or_404(
        SystemUser.objects.select_related("user", "created_by", "last_updated_by"),
        pk=pk,
    )

    # Check edit permission
    if not can_edit_system_user(request.user, system_user):
        messages.error(request, "You do not have permission to edit this system user.")
        return redirect("core:system_user_detail", pk=pk)

    # Determine if user can edit groups
    can_edit_groups = can_edit_system_user_groups(request.user, system_user)

    if request.method == "POST":
        form = SystemUserEditForm(
            request.POST,
            user=request.user,
            system_user=system_user,
        )
        if form.is_valid():
            # Update SystemUser fields
            system_user.organization = form.cleaned_data["organization"]
            system_user.position_title = form.cleaned_data["position_title"]
            system_user.last_updated_by = request.user
            system_user.save()

            # Update groups only if user has permission
            if can_edit_groups:
                new_groups = form.cleaned_data["groups"]
                # Only update system-level groups, preserve any other groups
                system_groups = ["Admins", "System Admins", "System Staff"]
                # Remove old system-level groups
                system_user.user.groups.remove(
                    *system_user.user.groups.filter(name__in=system_groups)
                )
                # Add new groups
                system_user.user.groups.add(*new_groups)

            messages.success(
                request,
                f"System user {system_user.user.get_full_name() or system_user.user.username} updated successfully.",
            )
            return redirect("core:system_user_detail", pk=pk)
    else:
        form = SystemUserEditForm(
            user=request.user,
            system_user=system_user,
        )

    context = {
        "system_user": system_user,
        "form": form,
        "can_edit_groups": can_edit_groups,
        "active": "system_users",
    }
    return render(request, "core/system_user_edit.html", context)


# ============================================================================
# Dashboard
# ============================================================================


@login_required
def dashboard(request):
    from django.contrib.auth import get_user_model
    User = get_user_model()

    # Time window for "recent" counts (e.g. last 30 days)
    now = timezone.now()
    start_period = now - timedelta(days=30)

    # --- User KPIs ---
    total_users = User.objects.filter(is_superuser=False).count()
    pending_users_count = User.objects.filter(
        school_staff__isnull=True,
        system_user__isnull=True,
        is_superuser=False,
    ).count()

    # --- SchoolStaff KPIs ---
    total_staff = SchoolStaff.objects.count()
    staff_added_recent = SchoolStaff.objects.filter(created_at__gte=start_period).count()

    # Staff with no assignments (unassigned to any school)
    staff_unassigned = SchoolStaff.objects.filter(assignments__isnull=True).distinct().count()

    # SchoolStaff breakdown by permission group
    school_staff_in_admins = SchoolStaff.objects.filter(
        user__groups__name="Admins"
    ).distinct().count()
    school_staff_in_school_admins = SchoolStaff.objects.filter(
        user__groups__name="School Admins"
    ).distinct().count()
    school_staff_in_school_staff = SchoolStaff.objects.filter(
        user__groups__name="School Staff"
    ).distinct().count()
    school_staff_in_teachers = SchoolStaff.objects.filter(
        user__groups__name="Teachers"
    ).distinct().count()

    # --- SystemUser KPIs ---
    total_system_users = SystemUser.objects.count()

    # SystemUser breakdown by permission group
    system_user_in_admins = SystemUser.objects.filter(
        user__groups__name="Admins"
    ).distinct().count()
    system_user_in_system_admins = SystemUser.objects.filter(
        user__groups__name="System Admins"
    ).distinct().count()
    system_user_in_system_staff = SystemUser.objects.filter(
        user__groups__name="System Staff"
    ).distinct().count()

    # --- Student KPIs ---
    total_students = Student.objects.count()
    students_added_recent = Student.objects.filter(created_at__gte=start_period).count()

    # --- Schools KPIs ---
    active_schools = EmisSchool.objects.filter(active=True).count()

    # Schools with at least one enrolment carrying disability-related data
    # (any of the 20 CFT fields has a recorded value)
    disability_q = (
        Q(cft1_wears_glasses__isnull=False)
        | Q(cft2_difficulty_seeing_with_glasses__isnull=False)
        | Q(cft3_difficulty_seeing__isnull=False)
        | Q(cft4_has_hearing_aids__isnull=False)
        | Q(cft5_difficulty_hearing_with_aids__isnull=False)
        | Q(cft6_difficulty_hearing__isnull=False)
        | Q(cft7_uses_walking_equipment__isnull=False)
        | Q(cft8_difficulty_walking_without_equipment__isnull=False)
        | Q(cft9_difficulty_walking_with_equipment__isnull=False)
        | Q(cft10_difficulty_walking_compare_to_others__isnull=False)
        | Q(cft11_difficulty_picking_up_small_objects__isnull=False)
        | Q(cft12_difficulty_being_understood__isnull=False)
        | Q(cft13_difficulty_learning__isnull=False)
        | Q(cft14_difficulty_remembering__isnull=False)
        | Q(cft15_difficulty_concentrating__isnull=False)
        | Q(cft16_difficulty_accepting_change__isnull=False)
        | Q(cft17_difficulty_controlling_behaviour__isnull=False)
        | Q(cft18_difficulty_making_friends__isnull=False)
        | Q(cft19_anxious_frequency__isnull=False)
        | Q(cft20_depressed_frequency__isnull=False)
    )

    schools_with_disability_data = (
        StudentSchoolEnrolment.objects.filter(disability_q)
        .values("school_id")
        .distinct()
        .count()
    )

    # --- Recent activity (simple unified event log across core models) ---
    events = []

    def add_events_from_queryset(qs, entity_label, detail_url_name=None):
        for obj in qs:
            when = getattr(obj, "last_updated_at", None) or getattr(
                obj, "created_at", None
            )
            created_at = getattr(obj, "created_at", None)
            last_updated_at = getattr(obj, "last_updated_at", None)

            if created_at and last_updated_at and last_updated_at > created_at:
                action = "Updated"
            elif created_at:
                action = "Created"
            else:
                action = "Activity"

            by_user = getattr(obj, "last_updated_by", None) or getattr(
                obj, "created_by", None
            )
            # Display full name, fallback to email, then username
            by_display = None
            if by_user:
                full_name = by_user.get_full_name()
                if full_name:
                    by_display = full_name
                elif by_user.email:
                    by_display = by_user.email
                else:
                    by_display = by_user.username

            url = None
            if detail_url_name and when:
                try:
                    url = reverse(detail_url_name, args=[obj.pk])
                except Exception:
                    url = None

            if when:
                events.append(
                    {
                        "when": when,
                        "entity": entity_label,
                        "action": action,
                        "by": by_display,
                        "url": url,
                    }
                )

    # Pull a few recent records from each core model
    add_events_from_queryset(
        SchoolStaff.objects.order_by("-last_updated_at")[:5],
        "Staff",
        detail_url_name="core:staff_detail",
    )
    add_events_from_queryset(
        Student.objects.order_by("-last_updated_at")[:5],
        "Student",
        detail_url_name="core:student_detail",
    )
    add_events_from_queryset(
        SchoolStaffAssignment.objects.order_by("-last_updated_at")[:5],
        "Staff assignment",
        detail_url_name=None,  # no detail view yet
    )
    add_events_from_queryset(
        StudentSchoolEnrolment.objects.order_by("-last_updated_at")[:5],
        "Student enrolment",
        detail_url_name=None,  # could later deep-link to student detail + anchor
    )

    # Sort all events by time and keep the latest 10
    events = sorted(events, key=lambda e: e["when"], reverse=True)[:10]

    context = {
        "active": "dashboard",
        # User KPIs
        "total_users": total_users,
        "pending_users_count": pending_users_count,
        # SchoolStaff KPIs
        "total_staff": total_staff,
        "staff_added_recent": staff_added_recent,
        "staff_unassigned": staff_unassigned,
        "school_staff_in_admins": school_staff_in_admins,
        "school_staff_in_school_admins": school_staff_in_school_admins,
        "school_staff_in_school_staff": school_staff_in_school_staff,
        "school_staff_in_teachers": school_staff_in_teachers,
        # SystemUser KPIs
        "total_system_users": total_system_users,
        "system_user_in_admins": system_user_in_admins,
        "system_user_in_system_admins": system_user_in_system_admins,
        "system_user_in_system_staff": system_user_in_system_staff,
        # Student KPIs
        "total_students": total_students,
        "students_added_recent": students_added_recent,
        # Schools KPIs
        "active_schools": active_schools,
        "schools_with_disability_data": schools_with_disability_data,
        # Activity
        "recent_events": events,
    }
    return render(request, "dashboard.html", context)


# ============================================================================
# Student Views
# ============================================================================


def _page_links(page_obj, *, radius=1, ends=1):
    current = page_obj.number
    last = page_obj.paginator.num_pages
    if last <= (2 * ends + 2 * radius + 3):
        return list(range(1, last + 1))
    window = set()
    window.update(range(1, ends + 1))
    window.update(range(last - ends + 1, last + 1))
    window.update(range(max(1, current - radius), min(last, current + radius) + 1))
    pages = []
    for p in range(1, last + 1):
        if p in window:
            pages.append(p)
        else:
            if pages and pages[-1] != "…":
                pages.append("…")
    return pages


def _related_enrol_qs(student):
    # Try both British/US spellings for the related_name
    if hasattr(student, "enrolments"):
        return student.enrolments
    if hasattr(student, "enrollments"):
        return student.enrollments
    return None


def _latest_enrolment(student):
    """
    Best-effort fetch of the most recent enrolment for a student.
    Tries to order by common fields if present; falls back to -id.
    """
    qs = _related_enrol_qs(student)
    if not qs:
        return None

    # attempt common date/year fields in priority order
    order_fields = []
    for field in ("-school_year", "-year", "-start_date", "-created_at", "-id"):
        # only keep fields that exist on the model
        try:
            qs.model._meta.get_field(field.lstrip("-"))
            order_fields.append(field)
        except Exception:
            continue
    if not order_fields:
        order_fields = ["-id"]
    return qs.order_by(*order_fields).first()


@login_required
def student_list(request):
    q = (request.GET.get("q") or "").strip()

    # Filters
    school_filter = (
        request.GET.get("school") or ""
    ).strip()  # EmisSchool.emis_school_no
    year_filter = (request.GET.get("year") or "").strip()  # EmisWarehouseYear.code
    level_filter = (request.GET.get("level") or "").strip()  # EmisClassLevel.code

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

    # ---- Latest-enrolment subqueries (order: newest school_year, then created_at, id)
    enrol_qs = StudentSchoolEnrolment.objects.filter(student=OuterRef("pk")).order_by(
        "-school_year__code", "-created_at", "-id"
    )

    latest_school_no = Subquery(enrol_qs.values("school__emis_school_no")[:1])
    latest_school_name = Subquery(enrol_qs.values("school__emis_school_name")[:1])
    latest_year_code = Subquery(enrol_qs.values("school_year__code")[:1])
    latest_year_label = Subquery(enrol_qs.values("school_year__label")[:1])
    latest_level_code = Subquery(enrol_qs.values("class_level__code")[:1])
    latest_level_label = Subquery(enrol_qs.values("class_level__label")[:1])

    qs = Student.objects.annotate(
        latest_school_no=latest_school_no,
        latest_school_name=latest_school_name,
        latest_year_code=latest_year_code,
        latest_year_label=latest_year_label,
        latest_level_code=latest_level_code,
        latest_level_label=latest_level_label,
    ).order_by(
        "last_name", "first_name"
    )  # base ordering; overridden by sort param below

    # Name-only search
    if q:
        qs = qs.filter(Q(first_name__icontains=q) | Q(last_name__icontains=q))

    # Filters on latest enrolment only
    if school_filter:
        qs = qs.filter(latest_school_no=school_filter)
    if year_filter:
        qs = qs.filter(latest_year_code=year_filter)
    if level_filter:
        qs = qs.filter(latest_level_code=level_filter)

    # Sorting map
    sort_map = {
        "name": ("last_name", "first_name"),
        "dob": ("date_of_birth",),
        "school": ("latest_school_name", "latest_school_no"),
        "school_year": ("latest_year_code",),
        "class_level": ("latest_level_code", "latest_level_label"),
    }
    if sort in sort_map:
        order_fields = sort_map[sort]
        if dir_ == "desc":
            order_fields = tuple(f"-{f}" for f in order_fields)
        qs = qs.order_by(*order_fields)

    # Per-school (row-based) filtering based on logged in user's role
    qs = filter_students_for_user(qs, request.user)

    # Pagination
    paginator = Paginator(qs, per_page)
    page_number = request.GET.get("page") or 1
    page_obj = paginator.get_page(page_number)

    # enrol_map built from annotations to keep your template unchanged
    enrol_map = {
        s.id: {
            "class_level_code": getattr(s, "latest_level_code", None),
            "class_level_label": getattr(s, "latest_level_label", None),
            "school_name": getattr(s, "latest_school_name", None),
            "school_no": getattr(s, "latest_school_no", None),
            "school_year": getattr(s, "latest_year_code", None),
        }
        for s in page_obj.object_list
    }

    # Picklists (active only; adjust if you want all)
    schools = EmisSchool.objects.filter(active=True).order_by("emis_school_name")
    years = EmisWarehouseYear.objects.filter(active=True).order_by("-code")
    levels = EmisClassLevel.objects.filter(active=True).order_by("code")

    # Pagination links
    page_links = _page_links(page_obj)

    context = {
        "active": "students",
        "q": q,
        "per_page": per_page,
        "page_size_options": PAGE_SIZE_OPTIONS,
        "page_obj": page_obj,
        "page_links": page_links,
        "enrol_map": enrol_map,
        # filters + lists
        "school": school_filter,
        "year": year_filter,
        "level": level_filter,
        "schools": schools,
        "years": years,
        "levels": levels,
        # sorting
        "sort": sort,
        "dir": dir_,
    }
    return render(request, "core/student_list.html", context)


@login_required
def student_detail(request, pk):
    student = get_object_or_404(
        Student.objects.prefetch_related(
            "enrolments__school",
            "enrolments__class_level",
            "enrolments__school_year",
            "enrolments__created_by",
            "enrolments__last_updated_by",
        ),
        pk=pk,
    )

    # ---- Row-level permission check ----
    if not can_view_student(request.user, student):
        raise PermissionDenied

    # Order enrolments: newest year first, then created_at, then id
    enrolments = student.enrolments.select_related(
        "school", "class_level", "school_year"
    ).order_by("-school_year__code", "-created_at", "-id")

    latest_enrolment = enrolments.first() if enrolments else None

    context = {
        "active": "students",
        "student": student,
        "enrolments": enrolments,
        "latest_enrolment": latest_enrolment,
    }
    return render(request, "core/student_detail.html", context)


@login_required
def student_edit(request, pk):
    student = get_object_or_404(Student, pk=pk)

    # Row-level + role-based check
    if not can_edit_student(request.user, student):
        raise PermissionDenied

    if request.method == "POST":
        form = StudentCoreForm(request.POST, instance=student)
        if form.is_valid():
            obj = form.save(commit=False)
            obj.last_updated_by = request.user
            obj.save()
            messages.success(request, "Student profile updated.")
            return redirect("core:student_detail", pk=student.pk)
    else:
        form = StudentCoreForm(instance=student)

    context = {
        "student": student,
        "form": form,
    }
    return render(request, "core/student_edit.html", context)


@login_required
def student_new(request):

    if not can_create_student(request.user):
        raise PermissionDenied

    if request.method == "POST":
        form = StudentDisabilityIntakeForm(request.POST)
        # ---- limit schools for this user ----
        form.fields["school"].queryset = get_allowed_enrolment_schools(request.user)

        if form.is_valid():
            cd = form.cleaned_data
            cft_data = form.get_cft_cleaned_data()

            try:
                with transaction.atomic():
                    # --- Create Student ---
                    student = Student.objects.create(
                        first_name=cd["first_name"].strip(),
                        last_name=cd["last_name"].strip(),
                        date_of_birth=cd["date_of_birth"],
                        gender=cd.get("gender"),
                        created_by=request.user,
                        last_updated_by=request.user,
                    )

                    # --- Create Enrolment with all 20 CFT fields ---
                    enrol_kwargs = {
                        "student": student,
                        "school": cd["school"],
                        "school_year": cd["school_year"],
                        "class_level": cd["class_level"],
                        "created_by": request.user,
                        "last_updated_by": request.user,
                    }

                    # Inject all cft1..cft20 values
                    enrol_kwargs.update(cft_data)

                    enrolment = StudentSchoolEnrolment.objects.create(**enrol_kwargs)

                    # Build the REAL student-detail URL
                    student_detail_url = request.build_absolute_uri(
                        reverse(
                            "core:student_detail", kwargs={"pk": student.pk}
                        )
                    )

                    # Send email *after* commit succeeds
                    def _send_email():
                        try:
                            send_student_created_email_async(
                                student=student,
                                enrolment=enrolment,
                                created_by=request.user,
                                request=request,
                                student_url=student_detail_url,
                            )
                        except Exception:
                            logger.warning(
                                "_send_email: error sending email for new student %s (created_by=%s)",
                                f"{student.first_name} {student.last_name}",
                                request.user,
                                exc_info=True,
                            )

                    transaction.on_commit(_send_email)

            except IntegrityError:
                messages.error(
                    request,
                    "A similar enrolment already exists for that school and school year.",
                )
                return render(
                    request,
                    "core/student_new.html",
                    {
                        "form": form,
                        "cft_meta": CFT_QUESTION_META,
                    },
                    status=400,
                )

            messages.success(request, "Disability record created.")
            return redirect("core:student_detail", pk=student.pk)

    else:
        form = StudentDisabilityIntakeForm()
        # ---- limit schools for this user ----
        form.fields["school"].queryset = get_allowed_enrolment_schools(request.user)

    # Build a display name from whatever we have in the form
    raw_first = (
        form.data.get("first_name") or form.initial.get("first_name") or ""
    ).strip()
    raw_last = (
        form.data.get("last_name") or form.initial.get("last_name") or ""
    ).strip()

    if raw_first or raw_last:
        display_name = f"{raw_first} {raw_last}".strip()
    else:
        display_name = None  # will fall back to "the child"

    cft_meta = build_cft_meta_for_name(display_name)

    return render(
        request,
        "core/student_new.html",
        {
            "form": form,
            "cft_meta": cft_meta,
        },
    )


def _name_similarity(a: str, b: str) -> float:
    """
    Use rapidfuzz.partial_ratio for robust fuzzy matching and
    normalise to a 0–1 similarity score.
    """
    a = (a or "").strip()
    b = (b or "").strip()
    if not a or not b:
        return 0.0
    # partial_ratio is good for "Jon" vs "Jonathan"
    return fuzz.partial_ratio(a, b) / 100.0


@login_required
def student_matches(request):
    """
    Lightweight JSON endpoint to suggest existing students that might match
    the student being entered.

    - Uses rapidfuzz-based similarity on first and last name.
    - If date_of_birth is provided, it must match exactly.
    """
    first_name_q = (request.GET.get("first_name") or "").strip()
    last_name_q = (request.GET.get("last_name") or "").strip()
    dob_raw = (request.GET.get("date_of_birth") or "").strip()

    qs = Student.objects.all()

    # If DOB is provided, use it as a hard filter (very strong signal)
    date_of_birth = parse_date(dob_raw) if dob_raw else None
    if date_of_birth:
        qs = qs.filter(date_of_birth=date_of_birth)

    # Coarse filter to avoid scanning the whole table:
    # use first character of names (if provided) as a prefix filter.
    if last_name_q:
        qs = qs.filter(last_name__istartswith=last_name_q[0])
    if first_name_q:
        qs = qs.filter(first_name__istartswith=first_name_q[0])

    # Reasonable upper bound before fuzzy scoring
    candidates = list(qs.order_by("last_name", "first_name")[:200])

    results_scored = []

    for s in candidates:
        # Compute similarity for each part (if query provided)
        if last_name_q:
            last_sim = _name_similarity(last_name_q, s.last_name)
        else:
            last_sim = 0.0

        if first_name_q:
            first_sim = _name_similarity(first_name_q, s.first_name)
        else:
            first_sim = 0.0

        # Combine: give more weight to last name
        if first_name_q and last_name_q:
            score = 0.6 * last_sim + 0.4 * first_sim
        elif last_name_q:
            score = last_sim
        elif first_name_q:
            score = first_sim
        else:
            score = 0.0

        results_scored.append((score, s))

    # Filter out very weak matches
    MIN_SCORE = 0.8  # adjust as you like
    results_scored = [item for item in results_scored if item[0] >= MIN_SCORE]

    # Sort by best score first, then by name
    results_scored.sort(
        key=lambda x: (-x[0], x[1].last_name.lower(), x[1].first_name.lower())
    )

    # Limit to top 10 matches
    results_scored = results_scored[:10]

    results = []
    for score, s in results_scored:
        results.append(
            {
                "id": s.id,
                "first_name": s.first_name,
                "last_name": s.last_name,
                "date_of_birth": (
                    s.date_of_birth.isoformat() if s.date_of_birth else None
                ),
                "current_schools": s.current_school_names,
                "similarity": round(score, 2),  # handy for debugging/UX tweaks
            }
        )

    return JsonResponse({"results": results})


@login_required
def student_enrolment_add(request, student_pk):
    student = get_object_or_404(Student, pk=student_pk)

    # Only users who can edit this student may add enrolments
    if not can_edit_student(request.user, student):
        raise PermissionDenied

    if request.method == "POST":
        form = StudentEnrolmentForm(request.POST)
        # ---- limit schools for this user ----
        form.fields["school"].queryset = get_allowed_enrolment_schools(request.user)

        if form.is_valid():
            enrol = form.save(commit=False)
            enrol.student = student
            enrol.created_by = request.user
            enrol.last_updated_by = request.user
            enrol.save()
            messages.success(request, "Student enrolment / disability data added.")
            return redirect("core:student_detail", pk=student.pk)
    else:
        form = StudentEnrolmentForm()
        # ---- limit schools for this user ----
        form.fields["school"].queryset = get_allowed_enrolment_schools(request.user)

    # Use the same friendly label text with the student's name
    display_name = f"{student.first_name} {student.last_name}".strip() or None
    cft_meta = build_cft_meta_for_name(display_name)

    return render(
        request,
        "core/student_enrolment_edit.html",
        {
            "student": student,
            "enrolment": None,
            "form": form,
            "is_create": True,
            "cft_meta": cft_meta,
        },
    )


@login_required
def student_enrolment_edit(request, student_pk, enrolment_pk):
    student = get_object_or_404(Student, pk=student_pk)
    enrolment = get_object_or_404(
        StudentSchoolEnrolment, pk=enrolment_pk, student=student
    )

    # Row-level + role-based check
    if not can_edit_student(request.user, student):
        raise PermissionDenied

    if request.method == "POST":
        form = StudentEnrolmentForm(request.POST, instance=enrolment)
        # ---- limit schools for this user ----
        form.fields["school"].queryset = get_allowed_enrolment_schools(request.user)

        if form.is_valid():
            enrol = form.save(commit=False)
            enrol.last_updated_by = request.user
            enrol.save()
            messages.success(request, "Student enrolment / disability data updated.")
            return redirect("core:student_detail", pk=student.pk)
    else:
        form = StudentEnrolmentForm(instance=enrolment)
        # ---- limit schools for this user ----
        form.fields["school"].queryset = get_allowed_enrolment_schools(request.user)

    # Build a nice display name for the questions
    display_name = f"{student.first_name} {student.last_name}".strip() or None
    cft_meta = build_cft_meta_for_name(display_name)

    return render(
        request,
        "core/student_enrolment_edit.html",
        {
            "student": student,
            "enrolment": enrolment,
            "form": form,
            "is_create": False,
            "cft_meta": cft_meta,
        },
    )


@login_required
def student_enrolment_delete(request, student_pk, enrolment_pk):
    student = get_object_or_404(Student, pk=student_pk)
    enrolment = get_object_or_404(
        StudentSchoolEnrolment, pk=enrolment_pk, student=student
    )

    # Row-level + role-based check
    if not can_delete_student(request.user, student):
        raise PermissionDenied

    if request.method == "POST":
        enrolment.delete()
        messages.success(request, "Student enrolment / disability data deleted.")
        return redirect("core:student_detail", pk=student.pk)

    context = {
        "student": student,
        "enrolment": enrolment,
    }
    return render(
        request,
        "core/student_enrolment_confirm_delete.html",
        context,
    )


# ============================================================================
# Pending Users (User Role Assignment)
# ============================================================================


from django.contrib.auth import get_user_model
from core.forms import AssignSchoolStaffForm, AssignSystemUserForm
from core.permissions import can_manage_pending_users

User = get_user_model()


@login_required
def pending_users_list(request):
    """
    List users who have signed in (via Google OAuth) but don't yet have
    a SchoolStaff or SystemUser profile assigned.

    Accessible to users in the Admins or System Admins groups.
    """
    if not can_manage_pending_users(request.user):
        raise PermissionDenied

    q = (request.GET.get("q") or "").strip()

    # Per-page
    try:
        per_page = int(request.GET.get("per_page", 25))
    except ValueError:
        per_page = 25
    if per_page not in PAGE_SIZE_OPTIONS:
        per_page = 25

    # Users without either profile (exclude superusers - they have full access already)
    pending_users_qs = User.objects.filter(
        school_staff__isnull=True,
        system_user__isnull=True,
        is_superuser=False,
    ).order_by("-date_joined")

    # Search by name or email
    if q:
        pending_users_qs = pending_users_qs.filter(
            Q(first_name__icontains=q)
            | Q(last_name__icontains=q)
            | Q(email__icontains=q)
            | Q(username__icontains=q)
        )

    # Pagination
    paginator = Paginator(pending_users_qs, per_page)
    page_number = request.GET.get("page") or 1
    page_obj = paginator.get_page(page_number)

    return render(
        request,
        "core/pending_users_list.html",
        {
            "active": "pending_users",
            "page_obj": page_obj,
            "q": q,
            "per_page": per_page,
            "page_size_options": PAGE_SIZE_OPTIONS,
            "page_links": _page_window(page_obj),
        },
    )


@login_required
def assign_school_staff(request, user_id):
    """
    Assign a pending user as School Staff.

    Creates a SchoolStaff profile and assigns them to selected groups.
    Accessible to users in the Admins or System Admins groups.
    """
    if not can_manage_pending_users(request.user):
        raise PermissionDenied

    target_user = get_object_or_404(User, pk=user_id)

    # Check if user already has a SchoolStaff profile
    if hasattr(target_user, "school_staff"):
        messages.warning(request, f"{target_user} already has a School Staff profile.")
        return redirect("core:pending_users_list")

    if request.method == "POST":
        form = AssignSchoolStaffForm(request.POST, user=request.user)
        if form.is_valid():
            # Create SchoolStaff profile
            staff = SchoolStaff.objects.create(
                user=target_user,
                staff_type=form.cleaned_data["staff_type"],
                created_by=request.user,
                last_updated_by=request.user,
            )

            # Assign groups
            groups = form.cleaned_data["groups"]
            target_user.groups.add(*groups)

            messages.success(
                request,
                f"{target_user.get_full_name() or target_user.username} has been assigned as School Staff.",
            )
            return redirect("core:staff_detail", pk=staff.pk)
    else:
        form = AssignSchoolStaffForm(user=request.user)

    return render(
        request,
        "core/assign_school_staff.html",
        {
            "active": "pending_users",
            "target_user": target_user,
            "form": form,
        },
    )


@login_required
def assign_system_user(request, user_id):
    """
    Assign a pending user as a System User.

    Creates a SystemUser profile and assigns them to selected groups.
    Accessible to users in the Admins or System Admins groups.
    """
    if not can_manage_pending_users(request.user):
        raise PermissionDenied

    target_user = get_object_or_404(User, pk=user_id)

    # Check if user already has a SystemUser profile
    if hasattr(target_user, "system_user"):
        messages.warning(request, f"{target_user} already has a System User profile.")
        return redirect("core:pending_users_list")

    if request.method == "POST":
        form = AssignSystemUserForm(request.POST, user=request.user)
        if form.is_valid():
            # Create SystemUser profile
            system_user = SystemUser.objects.create(
                user=target_user,
                organization=form.cleaned_data.get("organization", ""),
                position_title=form.cleaned_data.get("position_title", ""),
                created_by=request.user,
                last_updated_by=request.user,
            )

            # Assign groups
            groups = form.cleaned_data["groups"]
            target_user.groups.add(*groups)

            messages.success(
                request,
                f"{target_user.get_full_name() or target_user.username} has been assigned as a System User.",
            )
            return redirect("core:system_user_detail", pk=system_user.pk)
    else:
        form = AssignSystemUserForm(user=request.user)

    return render(
        request,
        "core/assign_system_user.html",
        {
            "active": "pending_users",
            "target_user": target_user,
            "form": form,
        },
    )


@login_required
def delete_pending_user(request, user_id):
    """
    Delete a pending user who has not been assigned a role.

    Accessible to users in the Admins or System Admins groups.
    Only users without SchoolStaff or SystemUser profiles can be deleted.
    """
    if not can_manage_pending_users(request.user):
        raise PermissionDenied

    target_user = get_object_or_404(User, pk=user_id)

    # Safety check: only allow deletion of users without profiles
    has_school_staff = hasattr(target_user, "school_staff") and target_user.school_staff is not None
    has_system_user = hasattr(target_user, "system_user") and target_user.system_user is not None

    if has_school_staff or has_system_user:
        messages.error(
            request,
            f"{target_user} already has a role assigned and cannot be deleted from here. "
            "Use the Django admin to manage this user.",
        )
        return redirect("core:pending_users_list")

    # Prevent deleting yourself
    if target_user == request.user:
        messages.error(request, "You cannot delete your own account.")
        return redirect("core:pending_users_list")

    # Prevent deleting superusers
    if target_user.is_superuser:
        messages.error(request, "Superusers cannot be deleted from here. Use the Django admin.")
        return redirect("core:pending_users_list")

    if request.method == "POST":
        username = target_user.username
        full_name = target_user.get_full_name() or username
        target_user.delete()
        messages.success(request, f"User '{full_name}' has been deleted.")
        return redirect("core:pending_users_list")

    return render(
        request,
        "core/delete_pending_user.html",
        {
            "active": "pending_users",
            "target_user": target_user,
        },
    )
