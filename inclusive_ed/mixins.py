# inclusive_ed/mixins.py
from django.contrib.auth.mixins import PermissionRequiredMixin


class InclusiveEdAccessRequired(PermissionRequiredMixin):
    permission_required = "inclusive_ed.access_inclusive_ed"
    raise_exception = False  # causes redirect to LOGIN_URL if not authed
