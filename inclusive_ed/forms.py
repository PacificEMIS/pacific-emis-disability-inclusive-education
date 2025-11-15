from django import forms

from integrations.models import EmisSchool, EmisWarehouseYear, EmisClassLevel
from inclusive_ed.models import Student, StudentSchoolEnrolment
from inclusive_ed.cft_meta import CFT_QUESTION_META

class StudentCoreForm(forms.ModelForm):
    """
    Minimal editable fields for a Student profile.
    Used on the student_edit view.
    """
    class Meta:
        model = Student
        fields = ["first_name", "last_name", "date_of_birth"]
        widgets = {
            "first_name": forms.TextInput(attrs={"class": "form-control form-control-sm"}),
            "last_name": forms.TextInput(attrs={"class": "form-control form-control-sm"}),
            "date_of_birth": forms.DateInput(
                attrs={"type": "date", "class": "form-control form-control-sm"}
            ),
        }

class StudentDisabilityIntakeForm(forms.Form):
    """
    Combined form for:
    - minimal Student core
    - one StudentSchoolEnrolment (school, year, class level)
    - all 20 CFT disability questions
    """

    # --- Student core ---
    first_name = forms.CharField(
        max_length=100,
        label="First name",
        widget=forms.TextInput(attrs={"class": "form-control form-control-sm"}),
    )
    last_name = forms.CharField(
        max_length=100,
        label="Last name",
        widget=forms.TextInput(attrs={"class": "form-control form-control-sm"}),
    )
    date_of_birth = forms.DateField(
        label="Date of birth",
        widget=forms.DateInput(
            attrs={"type": "date", "class": "form-control form-control-sm"}
        ),
    )

    # --- Enrolment core ---
    school = forms.ModelChoiceField(
        label="School",
        queryset=EmisSchool.objects.filter(active=True).order_by("emis_school_name"),
        widget=forms.Select(attrs={"class": "form-select form-select-sm"}),
    )
    school_year = forms.ModelChoiceField(
        label="School year",
        queryset=EmisWarehouseYear.objects.all().order_by("-code"),
        widget=forms.Select(attrs={"class": "form-select form-select-sm"}),
    )
    class_level = forms.ModelChoiceField(
        label="Class level",
        queryset=EmisClassLevel.objects.filter(active=True).order_by("code"),
        widget=forms.Select(attrs={"class": "form-select form-select-sm"}),
    )

    def __init__(self, *args, **kwargs):
        """
        Dynamically add one field per CFT question using CFT_QUESTION_META.

        We keep the full verbose question in metadata (for templates), and
        use the CFT code itself as the form field label for brevity.
        """
        super().__init__(*args, **kwargs)

        # Default school_year to latest by code
        if not self.initial.get("school_year"):
            current_year = (
                EmisWarehouseYear.objects.all().order_by("-code").first()
            )
            if current_year:
                self.initial["school_year"] = current_year
                self.fields["school_year"].initial = current_year

        # Dynamically create CFT fields
        for field_name, code, label, choices in CFT_QUESTION_META:
            self.fields[field_name] = forms.TypedChoiceField(
                label=code,  # e.g. "CFT1" – full question used in template via meta
                choices=[("", "— Select —")] + list(choices),
                required=False,
                coerce=int,
                empty_value=None,
                widget=forms.Select(attrs={"class": "form-select form-select-sm"}),
            )

    def get_cft_cleaned_data(self):
        """
        Return a dict {field_name: value} for all CFT fields
        (only non-None values).
        """
        data = {}
        for field_name, code, label, choices in CFT_QUESTION_META:
            val = self.cleaned_data.get(field_name)
            if val is not None:
                data[field_name] = val
        return data

class StudentEnrolmentForm(forms.ModelForm):
    """
    Used for:
      - Add enrolment/disability data for an existing student
      - Edit an existing StudentSchoolEnrolment

    The 'student' and audit fields are managed in the view.
    """

    class Meta:
        model = StudentSchoolEnrolment
        fields = [
            "school", "school_year", "class_level",
            "start_date", "end_date",
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
        ]
        widgets = {
            "start_date": forms.DateInput(attrs={"type": "date"}),
            "end_date": forms.DateInput(attrs={"type": "date"}),
        }