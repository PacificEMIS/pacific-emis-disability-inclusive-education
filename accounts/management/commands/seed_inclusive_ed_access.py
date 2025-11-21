from django.core.management.base import BaseCommand
from django.contrib.auth.models import Group, Permission
from django.contrib.contenttypes.models import ContentType


class Command(BaseCommand):
    help = "Create default group with access to Disability-Inclusive Education app."

    def handle(self, *args, **options):
        # Permission codename must match your inclusive_ed Meta.permissions
        app_label = "inclusive_ed"
        codename = "access_inclusive_ed"

        try:
            perm = Permission.objects.get(
                content_type__app_label=app_label, codename=codename
            )
        except Permission.DoesNotExist:
            self.stderr.write(
                self.style.ERROR(
                    f"Permission {app_label}.{codename} not found. Did you run migrations?"
                )
            )
            return

        group, _ = Group.objects.get_or_create(name="InclusiveEd – Staff")
        group.permissions.add(perm)
        self.stdout.write(
            self.style.SUCCESS(
                "Group seeded: InclusiveEd – Staff (with access permission)"
            )
        )
