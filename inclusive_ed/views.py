from django.contrib.auth.decorators import login_required
from django.shortcuts import render, redirect
from django.utils.timezone import now
from django.core.paginator import Paginator
from django.db.models import Q

from integrations.models import EmisClassLevel, EmisSchool
from inclusive_ed.models import Student

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

    try:
        per_page = int(request.GET.get("per_page", 25))
    except ValueError:
        per_page = 25
    if per_page not in PAGE_SIZE_OPTIONS:
        per_page = 25

    qs = Student.objects.all().order_by("last_name", "first_name")

    if q:
        qs = qs.filter(
            Q(first_name__icontains=q)
            | Q(last_name__icontains=q)
            | Q(class_level_code__icontains=q)
            | Q(emis_school_no__icontains=q)
        )

    paginator = Paginator(qs, per_page)
    page_number = request.GET.get("page") or 1
    page_obj = paginator.get_page(page_number)

    # Build a lightweight map of latest enrolment per student on the current page
    enrol_map = {}
    for s in page_obj.object_list:
        enrol = _latest_enrolment(s)
        if enrol:
            # Class level (supports FK or code field)
            class_level_label = None
            class_level_code = None
            if hasattr(enrol, "class_level") and getattr(enrol, "class_level"):
                # FK with label/code
                cl = getattr(enrol, "class_level")
                class_level_label = getattr(cl, "label", None)
                class_level_code = getattr(cl, "code", None)
            # fallback: code directly on enrolment
            if not class_level_code:
                class_level_code = getattr(enrol, "class_level_code", None)

            # School
            school_obj = getattr(enrol, "school", None)
            school_name = getattr(school_obj, "emis_school_name", None) if school_obj else None
            school_no = getattr(school_obj, "emis_school_no", None) if school_obj else None

            # School year (support common field names)
            school_year = None
            for fld in ("school_year", "year"):
                if hasattr(enrol, fld):
                    school_year = getattr(enrol, fld)
                    break

            enrol_map[s.id] = {
                "class_level_code": class_level_code,
                "class_level_label": class_level_label,
                "school_name": school_name,
                "school_no": school_no,
                "school_year": school_year,
            }

    context = {
        "active": "students",
        "now": now(),
        "q": q,
        "per_page": per_page,
        "page_size_options": PAGE_SIZE_OPTIONS,
        "page_obj": page_obj,
        "page_links": _page_links(page_obj),
        "enrol_map": enrol_map,
    }
    return render(request, "app/student_list.html", context)

@login_required
def dashboard(request):
    return render(request, "app/dashboard.html", {"active": "dashboard", "now": now()})

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