from django import forms

from integrations.models import EmisSchool, EmisWarehouseYear, EmisClassLevel
from inclusive_ed.models import Student
from inclusive_ed.cft_meta import CFT_QUESTION_META


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
