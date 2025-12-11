"""
Signals for account-related events.

Handles user signup events, specifically for Google OAuth sign-ins.
"""
from django.dispatch import receiver
from allauth.account.signals import user_signed_up
from django.contrib.auth import get_user_model

from core.emails import send_new_pending_user_email_async

User = get_user_model()


@receiver(user_signed_up)
def notify_admins_on_signup(request, user, **kwargs):
    """
    When a new user signs up via Google OAuth, notify Admins so they can
    assign the user as School Staff or System User.

    The user is NOT automatically assigned a profile; they remain as a
    'pending user' until an Admin assigns them a role.
    """
    # Build the pending users list URL for the email
    from django.urls import reverse

    pending_users_url = None
    if request:
        pending_users_url = request.build_absolute_uri(
            reverse("core:pending_users_list")
        )

    # Send email notification to Admins (async to not block the request)
    send_new_pending_user_email_async(
        new_user=user,
        pending_users_url=pending_users_url,
    )
