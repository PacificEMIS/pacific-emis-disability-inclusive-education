from django import forms
from django.contrib.auth.models import Group
from django.forms import ModelForm

from core.models import SchoolStaff, SchoolStaffAssignment, Student, StudentSchoolEnrolment, SystemUser
from core.permissions import is_admin, is_admins_group, is_school_admin, get_user_schools, GROUP_SYSTEM_ADMINS, _in_group, can_assign_admins_group
from integrations.models import EmisSchool, EmisWarehouseYear, EmisClassLevel
from core.cft_meta import CFT_QUESTION_META


class SchoolStaffAssignmentForm(ModelForm):
    class Meta:
        model = SchoolStaffAssignment
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
            user: The user creating/editing the assignment (for permission filtering)
        """
        super().__init__(*args, **kwargs)

        # Restrict school choices based on user permissions
        if user and user.is_authenticated:
            if user.is_superuser or is_admin(user):
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


class SchoolStaffEditForm(forms.Form):
    """
    Form to edit an existing School Staff member.

    - Django Super Users and Admins group: can edit all fields including all groups
    - School Admins group: can edit staff_type and groups, but cannot assign Admins group
    """

    staff_type = forms.ChoiceField(
        label="Staff type",
        choices=SchoolStaff.STAFF_TYPE_CHOICES,
        widget=forms.Select(attrs={"class": "form-select form-select-sm"}),
        help_text="Whether this staff member is teaching or non-teaching.",
    )

    groups = forms.ModelMultipleChoiceField(
        label="Groups",
        queryset=Group.objects.all().order_by("name"),
        required=True,
        widget=forms.CheckboxSelectMultiple(attrs={"class": "form-check-input"}),
        help_text="Select at least one group to assign permissions.",
    )

    def __init__(self, *args, user=None, school_staff=None, **kwargs):
        """
        Initialize form with user context to control group field visibility.

        Args:
            user: The user editing the school staff (for permission filtering)
            school_staff: The SchoolStaff being edited (for initial values)
        """
        super().__init__(*args, **kwargs)

        # Determine available groups based on user permissions
        # Superusers and Admins can assign any school-level group including Admins
        # System Admins and School Admins can assign school-level groups except Admins
        self.can_assign_admins = False
        if user:
            self.can_assign_admins = user.is_superuser or is_admins_group(user)

        if self.can_assign_admins:
            school_groups = ["Admins", "School Admins", "School Staff", "Teachers"]
        else:
            # System Admins and School Admins cannot assign the Admins group
            school_groups = ["School Admins", "School Staff", "Teachers"]

        self.fields["groups"].queryset = Group.objects.filter(
            name__in=school_groups
        ).order_by("name")

        # Set initial values from the school_staff being edited
        if school_staff:
            self.initial["staff_type"] = school_staff.staff_type
            # Only show groups that are in the available queryset
            self.initial["groups"] = school_staff.user.groups.filter(
                name__in=school_groups
            )

        # Determine if user can edit groups at all
        self.can_edit_groups = False
        if user:
            # Superusers, Admins, System Admins, and School Admins can edit group memberships
            self.can_edit_groups = (
                user.is_superuser
                or is_admins_group(user)
                or _in_group(user, GROUP_SYSTEM_ADMINS)
                or is_school_admin(user)
            )

        # If user cannot edit groups, disable the field
        if not self.can_edit_groups:
            self.fields["groups"].disabled = True
            self.fields["groups"].help_text = (
                "You do not have permission to change group memberships."
            )
        elif not self.can_assign_admins:
            self.fields["groups"].help_text = (
                "Select at least one group. Note: Only full Admins can assign the Admins group."
            )


# ============================================================================
# Student Forms
# ============================================================================


class StudentCoreForm(forms.ModelForm):
    """
    Minimal editable fields for a Student profile.
    Used on the student_edit view.
    """

    class Meta:
        model = Student
        fields = ["first_name", "last_name", "date_of_birth", "gender"]
        widgets = {
            "first_name": forms.TextInput(
                attrs={"class": "form-control form-control-sm"}
            ),
            "last_name": forms.TextInput(
                attrs={"class": "form-control form-control-sm"}
            ),
            "date_of_birth": forms.DateInput(
                attrs={"type": "date", "class": "form-control form-control-sm"}
            ),
            "gender": forms.Select(attrs={"class": "form-select form-select-sm"}),
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
    gender = forms.TypedChoiceField(
        label="Gender",
        choices=[("", "— Select —")] + list(Student.Gender.choices),
        required=False,
        coerce=int,
        empty_value=None,
        widget=forms.Select(attrs={"class": "form-select form-select-sm"}),
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
            current_year = EmisWarehouseYear.objects.all().order_by("-code").first()
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
            "school",
            "school_year",
            "class_level",
            "start_date",
            "end_date",
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
            "school": forms.Select(attrs={"class": "form-select form-select-sm"}),
            "school_year": forms.Select(attrs={"class": "form-select form-select-sm"}),
            "class_level": forms.Select(attrs={"class": "form-select form-select-sm"}),
            "start_date": forms.DateInput(
                attrs={"type": "date", "class": "form-control form-control-sm"}
            ),
            "end_date": forms.DateInput(
                attrs={"type": "date", "class": "form-control form-control-sm"}
            ),
            # CFT fields will be handled in __init__
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        # Ensure all CFT dropdowns use Bootstrap select styling
        for name, field in self.fields.items():
            if name.startswith("cft"):
                existing = field.widget.attrs.get("class", "")
                field.widget.attrs["class"] = (
                    existing + " form-select form-select-sm"
                ).strip()


# ============================================================================
# User Role Assignment Forms (for Pending Users)
# ============================================================================


class AssignSchoolStaffForm(forms.Form):
    """
    Form to assign a pending user as School Staff.

    Creates a SchoolStaff profile and assigns them to groups.

    - Django Super Users and Admins group: can assign any school-level group including Admins
    - System Admins group: can assign school-level groups except Admins
    """

    staff_type = forms.ChoiceField(
        label="Staff type",
        choices=SchoolStaff.STAFF_TYPE_CHOICES,
        initial=SchoolStaff.NON_TEACHING_STAFF,
        widget=forms.Select(attrs={"class": "form-select form-select-sm"}),
    )

    groups = forms.ModelMultipleChoiceField(
        label="Groups",
        queryset=Group.objects.all().order_by("name"),
        required=True,
        widget=forms.CheckboxSelectMultiple(attrs={"class": "form-check-input"}),
        help_text="Select at least one group to assign permissions.",
    )

    def __init__(self, *args, user=None, **kwargs):
        super().__init__(*args, **kwargs)

        # Determine available groups based on user permissions
        # Superusers and Admins can assign any school-level group including Admins
        # System Admins can assign school-level groups except Admins
        self.can_assign_admins = can_assign_admins_group(user) if user else False

        if self.can_assign_admins:
            school_groups = ["Admins", "School Admins", "School Staff", "Teachers"]
        else:
            # System Admins cannot assign the Admins group
            school_groups = ["School Admins", "School Staff", "Teachers"]

        self.fields["groups"].queryset = Group.objects.filter(
            name__in=school_groups
        ).order_by("name")

        if not self.can_assign_admins:
            self.fields["groups"].help_text = (
                "Select at least one group. Note: Only full Admins can assign the Admins group."
            )


class AssignSystemUserForm(forms.Form):
    """
    Form to assign a pending user as a System User.

    Creates a SystemUser profile and assigns them to groups.

    - Django Super Users and Admins group: can assign any system-level group including Admins
    - System Admins group: can assign system-level groups except Admins
    """

    organization = forms.CharField(
        label="Organization",
        max_length=255,
        required=False,
        widget=forms.TextInput(
            attrs={
                "class": "form-control form-control-sm",
                "placeholder": "e.g., Ministry of Education",
            }
        ),
        help_text="Organization or department name.",
    )

    position_title = forms.CharField(
        label="Position title",
        max_length=255,
        required=False,
        widget=forms.TextInput(
            attrs={
                "class": "form-control form-control-sm",
                "placeholder": "e.g., Data Analyst",
            }
        ),
        help_text="Job title or position within the organization.",
    )

    groups = forms.ModelMultipleChoiceField(
        label="Groups",
        queryset=Group.objects.all().order_by("name"),
        required=True,
        widget=forms.CheckboxSelectMultiple(attrs={"class": "form-check-input"}),
        help_text="Select at least one group to assign permissions.",
    )

    def __init__(self, *args, user=None, **kwargs):
        super().__init__(*args, **kwargs)

        # Determine available groups based on user permissions
        # Superusers and Admins can assign any system-level group including Admins
        # System Admins can assign system-level groups except Admins
        self.can_assign_admins = can_assign_admins_group(user) if user else False

        if self.can_assign_admins:
            system_groups = ["Admins", "System Admins", "System Staff"]
        else:
            # System Admins cannot assign the Admins group
            system_groups = ["System Admins", "System Staff"]

        self.fields["groups"].queryset = Group.objects.filter(
            name__in=system_groups
        ).order_by("name")

        if not self.can_assign_admins:
            self.fields["groups"].help_text = (
                "Select at least one group. Note: Only full Admins can assign the Admins group."
            )


class SystemUserEditForm(forms.Form):
    """
    Form to edit an existing System User.

    - Django Super Users and Admins group: can edit all fields including all groups
    - System Admins group: can edit organization/position and groups, but cannot assign Admins group
    """

    organization = forms.CharField(
        label="Organization",
        max_length=255,
        required=False,
        widget=forms.TextInput(
            attrs={
                "class": "form-control form-control-sm",
                "placeholder": "e.g., Ministry of Education",
            }
        ),
        help_text="Organization or department name.",
    )

    position_title = forms.CharField(
        label="Position title",
        max_length=255,
        required=False,
        widget=forms.TextInput(
            attrs={
                "class": "form-control form-control-sm",
                "placeholder": "e.g., Data Analyst",
            }
        ),
        help_text="Job title or position within the organization.",
    )

    groups = forms.ModelMultipleChoiceField(
        label="Groups",
        queryset=Group.objects.all().order_by("name"),
        required=True,
        widget=forms.CheckboxSelectMultiple(attrs={"class": "form-check-input"}),
        help_text="Select at least one group to assign permissions.",
    )

    def __init__(self, *args, user=None, system_user=None, **kwargs):
        """
        Initialize form with user context to control group field visibility.

        Args:
            user: The user editing the system user (for permission filtering)
            system_user: The SystemUser being edited (for initial values)
        """
        super().__init__(*args, **kwargs)

        # Determine available groups based on user permissions
        # Superusers and Admins can assign any system-level group including Admins
        # System Admins can assign system-level groups except Admins
        self.can_assign_admins = False
        if user:
            self.can_assign_admins = user.is_superuser or is_admins_group(user)

        if self.can_assign_admins:
            system_groups = ["Admins", "System Admins", "System Staff"]
        else:
            # System Admins cannot assign the Admins group
            system_groups = ["System Admins", "System Staff"]

        self.fields["groups"].queryset = Group.objects.filter(
            name__in=system_groups
        ).order_by("name")

        # Set initial values from the system_user being edited
        if system_user:
            self.initial["organization"] = system_user.organization or ""
            self.initial["position_title"] = system_user.position_title or ""
            # Only show groups that are in the available queryset
            self.initial["groups"] = system_user.user.groups.filter(
                name__in=system_groups
            )

        # Determine if user can edit groups at all
        self.can_edit_groups = False
        if user:
            # Superusers, Admins, and System Admins can edit group memberships
            self.can_edit_groups = (
                user.is_superuser
                or is_admins_group(user)
                or _in_group(user, GROUP_SYSTEM_ADMINS)
            )

        # If user cannot edit groups, disable the field
        if not self.can_edit_groups:
            self.fields["groups"].disabled = True
            self.fields["groups"].help_text = (
                "You do not have permission to change group memberships."
            )
        elif not self.can_assign_admins:
            self.fields["groups"].help_text = (
                "Select at least one group. Note: Only full Admins can assign the Admins group."
            )
