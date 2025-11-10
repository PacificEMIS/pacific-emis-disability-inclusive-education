from django.dispatch import receiver
from allauth.account.signals import user_signed_up
from django.contrib.auth.signals import user_logged_in
from django.contrib.auth import get_user_model
from accounts.models import Staff

User = get_user_model()

@receiver(user_signed_up)
def create_staff_on_signup(request, user, **kwargs):
    Staff.objects.get_or_create(user=user)

# Optional: backfill for existing users who log in
@receiver(user_logged_in)
def ensure_staff_on_login(sender, request, user, **kwargs):
    Staff.objects.get_or_create(user=user)
