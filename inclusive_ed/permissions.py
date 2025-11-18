def can_manage_inclusive_ed(user):
    """
    Return True if the user is:
      - a superuser, OR
      - a member of the group "InclusiveEd - Staff".
    """
    if not user.is_authenticated:
        return False

    if user.is_superuser:
        return True

    return user.groups.filter(name="InclusiveEd - Admins").exists()