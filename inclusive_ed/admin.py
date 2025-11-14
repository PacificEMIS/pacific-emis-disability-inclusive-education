from django.contrib import admin
from inclusive_ed.models import Student, StudentSchoolEnrolment

from accounts.mixins import CreatedUpdatedAuditMixin

# Inline to edit a student's school/year enrolments (with 20 CFT disability fields)
class StudentSchoolEnrolmentInline(admin.TabularInline):
    model = StudentSchoolEnrolment
    extra = 1
    show_change_link = True
    autocomplete_fields = ("school", "school_year", "class_level")

    fields = (
        "school", "school_year", "class_level",
        "start_date", "end_date",

        # CFT 1–20 fields
        "cft1_wears_glasses",
        "cft2_difficulty_seeing_with_glasses",
        "cft3_difficulty_seeing",
        "cft4_has_hearing_aids",
        "cft5_difficulty_hearing_with_aids",
        "cft6_difficulty_hearing",
        "cft7_uses_walking_equipment",
        "cft8_difficulty_walking_without_equipment",
        "cft9_difficulty_walking_with_equipment",
        "cft10_difficulty_walking_compare_to_others",
        "cft11_difficulty_picking_up_small_objects",
        "cft12_difficulty_being_understood",
        "cft13_difficulty_learning",
        "cft14_difficulty_remembering",
        "cft15_difficulty_concentrating",
        "cft16_difficulty_accepting_change",
        "cft17_difficulty_controlling_behaviour",
        "cft18_difficulty_making_friends",
        "cft19_anxious_frequency",
        "cft20_depressed_frequency",

        # audit
        "created_at", "created_by", "last_updated_at", "last_updated_by",
    )

    readonly_fields = (
        "created_at", "created_by",
        "last_updated_at", "last_updated_by",
    )

@admin.register(Student)
class StudentAdmin(CreatedUpdatedAuditMixin, admin.ModelAdmin):
    ordering = ("last_name", "first_name")
    search_fields = ("first_name", "last_name")
    # Filter by related enrolment fields
    list_filter = (
        ("enrolments__school", admin.RelatedOnlyFieldListFilter),
        ("enrolments__school_year", admin.RelatedOnlyFieldListFilter),
        ("enrolments__class_level", admin.RelatedOnlyFieldListFilter),
    )
    readonly_fields = ("created_at", "created_by", "last_updated_at", "last_updated_by")
    inlines = [StudentSchoolEnrolmentInline]

    list_display = (
        "first_name",
        "last_name",
        "date_of_birth",
        "current_school_names",
        "active_enrolments_count",
        "created_by",
        "created_at",
    )

    def current_school_names(self, obj):
        # Uses the @property current_enrolments you added on Student
        names = [e.school.emis_school_name for e in obj.current_enrolments]
        return ", ".join(names) if names else "—"
    current_school_names.short_description = "Current schools"

    def active_enrolments_count(self, obj):
        return obj.current_enrolments.count()
    active_enrolments_count.short_description = "Active enrolments"


# @admin.register(StudentSchoolEnrolment)
# class StudentSchoolEnrolmentAdmin(CreatedUpdatedAuditMixin, admin.ModelAdmin):
#     ordering = ("school_year__code", "school__emis_school_no", "student__last_name")
#     search_fields = (
#         "student__first_name",
#         "student__last_name",
#         "school__emis_school_name",
#         "school__emis_school_no",
#     )
#     list_filter = (
#         ("school", admin.RelatedOnlyFieldListFilter),
#         ("school_year", admin.RelatedOnlyFieldListFilter),
#         ("class_level", admin.RelatedOnlyFieldListFilter),
#         "end_date",  # quick filter for active vs ended (isnull vs not)
#     )
#     autocomplete_fields = ("student", "school", "school_year", "class_level")
#     readonly_fields = ("created_at", "updated_at")

#     list_display = (
#         "student",
#         "school",
#         "school_year",
#         "class_level",
#         "start_date",
#         "end_date",
#         "is_active_display",
#         "created_at",
#     )

#     def is_active_display(self, obj):
#         return obj.is_active
#     is_active_display.boolean = True
#     is_active_display.short_description = "Active"
