from django import forms
from django.forms import ModelForm

from accounts.models import StaffSchoolMembership
from integrations.models import EmisSchool
from inclusive_ed.permissions import is_inclusive_admin, get_user_schools


class StaffSchoolMembershipForm(ModelForm):
    class Meta:
        model = StaffSchoolMembership
        fields = ["school", "job_title", "start_date", "end_date"]
        widgets = {
            "school": forms.Select(attrs={"class": "form-select form-select-sm"}),
            "job_title": forms.Select(attrs={"class": "form-select form-select-sm"}),
            "start_date": forms.DateInput(
                attrs={"type": "date", "class": "form-control form-control-sm"}
            ),
            "end_date": forms.DateInput(
                attrs={"type": "date", "class": "form-control form-control-sm"}
            ),
        }

    def __init__(self, *args, user=None, **kwargs):
        """
        Initialize form with user context to restrict school choices.

        Args:
            user: The user creating/editing the membership (for permission filtering)
        """
        super().__init__(*args, **kwargs)

        # Restrict school choices based on user permissions
        if user and user.is_authenticated:
            if user.is_superuser or is_inclusive_admin(user):
                # System admins see all active schools
                self.fields["school"].queryset = EmisSchool.objects.filter(
                    active=True
                ).order_by("emis_school_name")
            else:
                # School admins see only their active schools
                user_schools = get_user_schools(user)
                self.fields["school"].queryset = user_schools.order_by(
                    "emis_school_name"
                )
        else:
            # No user context - restrict to nothing
            self.fields["school"].queryset = EmisSchool.objects.none()
