from accounts.models import Staff


def staff_context(request):
    """
    Adds staff_pk_for_request_user for linking to the user's own staff page.
    Returns None if no Staff record exists for this user.
    """
    user = request.user
    if user.is_authenticated:
        try:
            staff = Staff.objects.only("pk").get(user=user)
            return {"staff_pk_for_request_user": staff.pk}
        except Staff.DoesNotExist:
            pass
    return {"staff_pk_for_request_user": None}
