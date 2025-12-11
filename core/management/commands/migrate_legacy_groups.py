"""
Management command to migrate users from legacy "InclusiveEd - *" groups to the new
standardized group names, then delete the legacy groups.

Legacy groups:
  - InclusiveEd - Admins -> Admins
  - InclusiveEd - School Admins -> School Admins
  - InclusiveEd - School Staff -> School Staff
  - InclusiveEd - Teachers -> Teachers
  - InclusiveEd - System Admins -> System Admins
  - InclusiveEd - System Staff -> System Staff

Usage:
  python manage.py migrate_legacy_groups         # Preview what will happen
  python manage.py migrate_legacy_groups --commit  # Actually perform the migration
"""

from django.core.management.base import BaseCommand
from django.contrib.auth.models import Group, User


class Command(BaseCommand):
    help = "Migrate users from legacy 'InclusiveEd - *' groups to new group names and delete legacy groups."

    # Mapping of legacy group names to new group names
    LEGACY_TO_NEW = {
        "InclusiveEd - Admins": "Admins",
        "InclusiveEd - School Admins": "School Admins",
        "InclusiveEd - School Staff": "School Staff",
        "InclusiveEd - Teachers": "Teachers",
        "InclusiveEd - System Admins": "System Admins",
        "InclusiveEd - System Staff": "System Staff",
    }

    def add_arguments(self, parser):
        parser.add_argument(
            "--commit",
            action="store_true",
            help="Actually perform the migration. Without this flag, only shows what would be done.",
        )

    def handle(self, *args, **options):
        commit = options.get("commit", False)

        if not commit:
            self.stdout.write(
                self.style.WARNING(
                    "\n=== DRY RUN MODE ===\n"
                    "No changes will be made. Use --commit to apply changes.\n"
                )
            )

        users_migrated = 0
        groups_deleted = 0

        for legacy_name, new_name in self.LEGACY_TO_NEW.items():
            # Check if legacy group exists
            try:
                legacy_group = Group.objects.get(name=legacy_name)
            except Group.DoesNotExist:
                self.stdout.write(f"  Legacy group '{legacy_name}' does not exist, skipping.")
                continue

            # Get or create the new group
            new_group, created = Group.objects.get_or_create(name=new_name)
            if created:
                self.stdout.write(
                    self.style.SUCCESS(f"  Created new group: {new_name}")
                )
            else:
                self.stdout.write(f"  New group '{new_name}' already exists.")

            # Get users in the legacy group
            users_in_legacy = legacy_group.user_set.all()
            user_count = users_in_legacy.count()

            if user_count > 0:
                self.stdout.write(
                    f"  Found {user_count} user(s) in '{legacy_name}':"
                )
                for user in users_in_legacy:
                    self.stdout.write(
                        f"    - {user.username} ({user.email or 'no email'})"
                    )

                if commit:
                    # Add users to new group
                    for user in users_in_legacy:
                        if not user.groups.filter(pk=new_group.pk).exists():
                            user.groups.add(new_group)
                            self.stdout.write(
                                self.style.SUCCESS(
                                    f"      Added {user.username} to '{new_name}'"
                                )
                            )
                        else:
                            self.stdout.write(
                                f"      {user.username} already in '{new_name}'"
                            )
                        # Remove from legacy group
                        user.groups.remove(legacy_group)
                        self.stdout.write(
                            self.style.SUCCESS(
                                f"      Removed {user.username} from '{legacy_name}'"
                            )
                        )
                    users_migrated += user_count
            else:
                self.stdout.write(f"  No users in '{legacy_name}'.")

            # Delete the legacy group
            if commit:
                legacy_group.delete()
                groups_deleted += 1
                self.stdout.write(
                    self.style.SUCCESS(f"  Deleted legacy group: {legacy_name}")
                )
            else:
                self.stdout.write(
                    self.style.WARNING(f"  Would delete legacy group: {legacy_name}")
                )

        self.stdout.write("")
        if commit:
            self.stdout.write(
                self.style.SUCCESS(
                    f"Migration complete: {users_migrated} user(s) migrated, "
                    f"{groups_deleted} legacy group(s) deleted."
                )
            )
        else:
            self.stdout.write(
                self.style.WARNING(
                    "Dry run complete. Use --commit to apply these changes."
                )
            )

        # List any remaining groups that might need attention
        self.stdout.write("\nCurrent groups in database:")
        for group in Group.objects.all().order_by("name"):
            user_count = group.user_set.count()
            self.stdout.write(f"  - {group.name} ({user_count} users)")
