from django.core.management.base import BaseCommand
from django.db import transaction
from integrations.models import EmisSchool, EmisClassLevel
from integrations.emis_client import EmisClient

class Command(BaseCommand):
    help = "Fetch /api/lookups/collection/core and update local schools & class levels"

    def handle(self, *args, **options):
        client = EmisClient()
        payload = client.get_core_lookups()

        schools = payload.get("schoolCodes", [])
        levels = payload.get("levels", [])
        added_sch = updated_sch = added_lvl = updated_lvl = 0

        with transaction.atomic():
            # Schools
            for item in schools:
                code, name = item.get("C"), item.get("N")
                if not code:
                    continue
                obj, created = EmisSchool.objects.update_or_create(
                    emis_school_no=code,
                    defaults={"emis_school_name": name or "", "active": True},
                )
                added_sch += int(created)
                updated_sch += int(not created)

            # Class Levels
            for item in levels:
                code, label = item.get("C"), item.get("N")
                if not code:
                    continue
                obj, created = EmisClassLevel.objects.update_or_create(
                    code=str(code),
                    defaults={"label": label or str(code), "active": True},
                )
                added_lvl += int(created)
                updated_lvl += int(not created)

        self.stdout.write(self.style.SUCCESS(
            f"Schools +{added_sch}/{updated_sch}, Levels +{added_lvl}/{updated_lvl}"
        ))
