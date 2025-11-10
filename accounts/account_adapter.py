from allauth.account.adapter import DefaultAccountAdapter
from django.conf import settings
from django.core.exceptions import PermissionDenied

class DomainRestrictedAdapter(DefaultAccountAdapter):
    def is_open_for_signup(self, request):
        return True

    def save_user(self, request, user, form, commit=True):
        user = super().save_user(request, user, form, commit=False)
        allowed = getattr(settings, "ALLOWED_SIGNUP_DOMAINS", None)
        if allowed:
            email = (user.email or "").lower()
            if not any(email.endswith("@" + d.lower()) for d in allowed):
                raise PermissionDenied("This email domain is not allowed.")
        if commit:
            user.save()
        return user
