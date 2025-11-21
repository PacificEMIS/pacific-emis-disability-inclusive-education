from django import forms
from django.forms import ModelForm

from accounts.models import StaffSchoolMembership


class StaffSchoolMembershipForm(ModelForm):
    class Meta:
        model = StaffSchoolMembership
        fields = ["school", "job_title", "login_role", "start_date", "end_date"]
        widgets = {
            "school": forms.Select(attrs={"class": "form-select form-select-sm"}),
            "job_title": forms.Select(attrs={"class": "form-select form-select-sm"}),
            "login_role": forms.Select(attrs={"class": "form-select form-select-sm"}),
            "start_date": forms.DateInput(
                attrs={"type": "date", "class": "form-control form-control-sm"}
            ),
            "end_date": forms.DateInput(
                attrs={"type": "date", "class": "form-control form-control-sm"}
            ),
        }
