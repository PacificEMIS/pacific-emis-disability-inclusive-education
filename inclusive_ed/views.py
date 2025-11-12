from django.contrib.auth.decorators import login_required
from django.db.models import Q, OuterRef, Subquery, F
from django.shortcuts import render, redirect
from django.core.paginator import Paginator
from django.db.models import Q

from integrations.models import EmisClassLevel, EmisSchool, EmisWarehouseYear
from inclusive_ed.models import Student, StudentSchoolEnrolment

from django.contrib import messages
from django.utils.dateparse import parse_date

PAGE_SIZE_OPTIONS = [10, 25, 50, 100]

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
    return render(request, "app/student_list.html", context)

@login_required
def dashboard(request):
    return render(request, "app/dashboard.html", {"active": "dashboard"})

# example Class-Based View using mixin
#class DashboardView(InclusiveEdAccessRequired, TemplateView):
#    template_name = "inclusive_ed/dashboard.html"


@login_required
def new_student(request):
    assignments = (EmisSchool.objects
                   .filter(active=True)
                   .only("emis_school_no", "emis_school_name")
                   .order_by("emis_school_name"))

    class_levels = EmisClassLevel.objects.filter(active=True).order_by("code")

    if request.method == "POST":
        data = request.POST
        first_name = (data.get("first_name") or "").strip()
        last_name = (data.get("last_name") or "").strip()
        dob_raw = data.get("date_of_birth") or ""
        class_level_code = data.get("class_level_code") or ""
        school_no = (data.get("emis_school_no") or "").strip()

        errs = []
        if not first_name: errs.append("First name is required.")
        if not last_name: errs.append("Last name is required.")
        if not dob_raw: errs.append("Date of birth is required.")
        if not class_level_code: errs.append("Class level is required.")
        if not school_no: errs.append("School is required.")

        date_of_birth = parse_date(dob_raw) if dob_raw else None
        if dob_raw and not date_of_birth:
            errs.append("Date of birth is invalid (use YYYY-MM-DD).")

        if errs:
            for e in errs: messages.error(request, e)
            return render(request, "app/new_student.html",
                          {"class_levels": class_levels, "assignments": assignments}, status=400)

        Student.objects.create(
            first_name=first_name,
            last_name=last_name,
            date_of_birth=date_of_birth,
            class_level_code=class_level_code,
            emis_school_no=school_no,  # if IntegerField, cast to int
            created_by=request.user,
        )
        messages.success(request, "Student created.")
        return redirect("inclusive_ed:dashboard")

    return render(request, "app/new_student.html",
                  {"class_levels": class_levels, "assignments": assignments})