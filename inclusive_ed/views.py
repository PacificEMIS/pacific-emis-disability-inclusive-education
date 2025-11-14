from datetime import timedelta

from django.utils import timezone
from django.utils.dateparse import parse_date
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db import IntegrityError, transaction
from django.db.models import Q, OuterRef, Subquery, F
from django.http import JsonResponse
from django.shortcuts import render, redirect, get_object_or_404
from django.core.paginator import Paginator
from django.urls import reverse

from rapidfuzz import fuzz

from accounts.models import Staff, StaffSchoolMembership
from inclusive_ed.models import Student, StudentSchoolEnrolment
from inclusive_ed.forms import StudentDisabilityIntakeForm
from inclusive_ed.cft_meta import CFT_QUESTION_META
from integrations.models import EmisClassLevel, EmisSchool, EmisWarehouseYear

PAGE_SIZE_OPTIONS = [10, 25, 50, 100]

@login_required
def dashboard(request):
    # Time window for "recent" counts (e.g. last 30 days)
    now = timezone.now()
    start_period = now - timedelta(days=30)

    # --- Staff KPIs ---
    total_staff = Staff.objects.count()
    staff_added_recent = Staff.objects.filter(created_at__gte=start_period).count()

    # Staff with no memberships (unassigned to any school)
    staff_unassigned = Staff.objects.filter(memberships__isnull=True).distinct().count()

    # Staff by InclusiveEd groups
    staff_admin_count = (
        Staff.objects.filter(user__groups__name="InclusiveEd - Admins").distinct().count()
    )
    staff_staff_count = (
        Staff.objects.filter(user__groups__name="InclusiveEd - Staff").distinct().count()
    )
    staff_teacher_count = (
        Staff.objects.filter(user__groups__name="InclusiveEd - Teachers").distinct().count()
    )

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
            when = getattr(obj, "last_updated_at", None) or getattr(obj, "created_at", None)
            created_at = getattr(obj, "created_at", None)
            last_updated_at = getattr(obj, "last_updated_at", None)

            if created_at and last_updated_at and last_updated_at > created_at:
                action = "Updated"
            elif created_at:
                action = "Created"
            else:
                action = "Activity"

            by_user = getattr(obj, "last_updated_by", None) or getattr(obj, "created_by", None)
            by_username = getattr(by_user, "username", None) if by_user else None

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
                        "by": by_username,
                        "url": url,
                    }
                )

    # Pull a few recent records from each core model
    add_events_from_queryset(
        Staff.objects.order_by("-last_updated_at")[:5],
        "Staff",
        detail_url_name="accounts:staff_detail",
    )
    add_events_from_queryset(
        Student.objects.order_by("-last_updated_at")[:5],
        "Student",
        detail_url_name="inclusive_ed:student_detail",
    )
    add_events_from_queryset(
        StaffSchoolMembership.objects.order_by("-last_updated_at")[:5],
        "Staff membership",
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

        # Staff KPIs
        "total_staff": total_staff,
        "staff_added_recent": staff_added_recent,
        "staff_unassigned": staff_unassigned,
        "staff_admin_count": staff_admin_count,
        "staff_staff_count": staff_staff_count,
        "staff_teacher_count": staff_teacher_count,

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

# example Class-Based View using mixin
#class DashboardView(InclusiveEdAccessRequired, TemplateView):
#    template_name = "dashboard.html"

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
    school_filter = (request.GET.get("school") or "").strip()      # EmisSchool.emis_school_no
    year_filter   = (request.GET.get("year") or "").strip()        # EmisWarehouseYear.code
    level_filter  = (request.GET.get("level") or "").strip()       # EmisClassLevel.code

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
    enrol_qs = (
        StudentSchoolEnrolment.objects
        .filter(student=OuterRef("pk"))
        .order_by("-school_year__code", "-created_at", "-id")
    )

    latest_school_no    = Subquery(enrol_qs.values("school__emis_school_no")[:1])
    latest_school_name  = Subquery(enrol_qs.values("school__emis_school_name")[:1])
    latest_year_code    = Subquery(enrol_qs.values("school_year__code")[:1])
    latest_year_label   = Subquery(enrol_qs.values("school_year__label")[:1])
    latest_level_code   = Subquery(enrol_qs.values("class_level__code")[:1])
    latest_level_label  = Subquery(enrol_qs.values("class_level__label")[:1])

    qs = (
        Student.objects
        .annotate(
            latest_school_no=latest_school_no,
            latest_school_name=latest_school_name,
            latest_year_code=latest_year_code,
            latest_year_label=latest_year_label,
            latest_level_code=latest_level_code,
            latest_level_label=latest_level_label,
        )
        .order_by("last_name", "first_name")  # base ordering; overridden by sort param below
    )

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
        "name":        ("last_name", "first_name"),
        "dob":         ("date_of_birth",),
        "school":      ("latest_school_name", "latest_school_no"),
        "school_year": ("latest_year_code",),
        "class_level": ("latest_level_code", "latest_level_label"),
    }
    if sort in sort_map:
        order_fields = sort_map[sort]
        if dir_ == "desc":
            order_fields = tuple(f"-{f}" for f in order_fields)
        qs = qs.order_by(*order_fields)

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
    schools = EmisSchool.objects.filter(active=True).order_by("emis_school_no")
    years   = EmisWarehouseYear.objects.filter(active=True).order_by("-code")
    levels  = EmisClassLevel.objects.filter(active=True).order_by("code")

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
    return render(request, "inclusive_ed/student_list.html", context)

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

    # Order enrolments: newest year first, then created_at, then id
    enrolments = (
        student.enrolments
        .select_related("school", "class_level", "school_year")
        .order_by("-school_year__code", "-created_at", "-id")
    )

    latest_enrolment = enrolments.first() if enrolments else None

    context = {
        "active": "students",
        "student": student,
        "enrolments": enrolments,
        "latest_enrolment": latest_enrolment,
    }
    return render(request, "inclusive_ed/student_detail.html", context)

@login_required
def student_new(request):
    if request.method == "POST":
        form = StudentDisabilityIntakeForm(request.POST)
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

                    StudentSchoolEnrolment.objects.create(**enrol_kwargs)

            except IntegrityError:
                messages.error(
                    request,
                    "A similar enrolment already exists for that school and school year.",
                )
                return render(
                    request,
                    "inclusive_ed/student_new.html",
                    {
                        "form": form,
                        "cft_meta": CFT_QUESTION_META,
                    },
                    status=400,
                )

            messages.success(request, "Disability record created.")
            return redirect("inclusive_ed:student_detail", pk=student.pk)

    else:
        form = StudentDisabilityIntakeForm()

    return render(
        request,
        "inclusive_ed/student_new.html",
        {
            "form": form,
            "cft_meta": CFT_QUESTION_META,
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
                "date_of_birth": s.date_of_birth.isoformat()
                if s.date_of_birth
                else None,
                "current_schools": s.current_school_names,
                "similarity": round(score, 2),  # handy for debugging/UX tweaks
            }
        )

    return JsonResponse({"results": results})
