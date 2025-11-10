import random
import string
from datetime import date, timedelta
from typing import List, Tuple

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from inclusive_ed.models import Student, StudentSchoolEnrolment
from integrations.models import EmisSchool, EmisWarehouseYear, EmisClassLevel


FIRST_NAMES = [
    "Ari", "Ben", "Cita", "Dani", "Eli", "Fina", "Gabe", "Hana", "Ika",
    "Jori", "Keni", "Lani", "Mika", "Niko", "Ona", "Pasi", "Rina", "Sami",
    "Tala", "Vika", "Wena", "Yani", "Zora"
]
LAST_NAMES = [
    "Abel", "Beni", "Cabral", "Dano", "Emani", "Faro", "Gonzales", "Hare",
    "Isamu", "Jorin", "Katoa", "Loto", "Malo", "Nase", "Oto", "Paea",
    "Ratu", "Sione", "Taito", "Ula", "Vakalahi", "Waqa", "Yano", "Zed"
]

# Class level → official age (years)
OFFICIAL_AGE = {
    # KPS*
    "P1": 6, "P2": 7, "P3": 8, "P4": 9, "P5": 10, "P6": 11,
    # KJSS*
    "JS1": 12, "JS2": 13, "JS3": 14,
    # KSSS*
    "SS1": 15, "SS2": 16, "SS3": 17, "SS4": 18,
}

# For each school code pattern, allowed class levels
LEVELS_BY_PATTERN = {
    "KPS": ["P1", "P2", "P3", "P4", "P5", "P6"],
    "KJSS": ["JS1", "JS2", "JS3"],
    "KSSS": ["SS1", "SS2", "SS3", "SS4"],
}

def pick_name() -> Tuple[str, str]:
    return random.choice(FIRST_NAMES), random.choice(LAST_NAMES)

def random_bool(p_true: float = 0.2) -> bool:
    return random.random() < p_true

def random_freq_or_none() -> int | None:
    # Roughly 25% None, else 0–4
    return None if random.random() < 0.25 else random.randint(0, 4)

def dob_for_level(level_code: str, school_year_code: str) -> date:
    """
    Make DOB close to the official age for the given class level in the target school_year.
    We assume school_year_code like '2025'. We pick DOB mostly within ±1 year of the official age.
    """
    target_year = int(school_year_code)
    base_age = OFFICIAL_AGE[level_code]  # in years
    # Choose age as official age or ±1 with some probability
    age = base_age + random.choice([-1, 0, 0, 0, 1])  # skew towards exact age
    # Birthday somewhere within the calendar year (make it natural)
    birth_year = target_year - age
    # Random day within the year
    start = date(birth_year, 1, 1)
    end = date(birth_year, 12, 31)
    delta_days = (end - start).days
    return start + timedelta(days=random.randint(0, delta_days))

def pick_size_bucket() -> int:
    """
    Return a student count for a school:
      - small: 2–4 (20%)
      - medium: 5–10 (50%)
      - large: 11–30 (30%)
    """
    r = random.random()
    if r < 0.2:
        return random.randint(2, 4)
    elif r < 0.7:
        return random.randint(5, 10)
    else:
        return random.randint(11, 30)

class Command(BaseCommand):
    help = "Seed sample Inclusive Ed data (Students + single Enrolment each) for school_year=2025."

    def add_arguments(self, parser):
        parser.add_argument(
            "--year",
            default="2025",
            help="Warehouse year code to use (default: 2025).",
        )
        parser.add_argument(
            "--seed",
            type=int,
            default=None,
            help="Random seed for reproducibility.",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Compute and print plan without writing to the database.",
        )

    def handle(self, *args, **opts):
        year_code = opts["year"]
        seed = opts["seed"]
        dry_run = opts["dry_run"]

        if seed is not None:
            random.seed(seed)

        try:
            wy = EmisWarehouseYear.objects.get(code=year_code)
        except EmisWarehouseYear.DoesNotExist:
            raise CommandError(f"EmisWarehouseYear with code='{year_code}' not found.")

        # Fetch schools by pattern, skip KECE*
        def schools(prefix: str) -> List[EmisSchool]:
            qs = EmisSchool.objects.filter(emis_school_no__startswith=prefix).exclude(
                emis_school_no__startswith="KECE"
            )
            return list(qs.order_by("emis_school_no"))

        kps_schools = schools("KPS")
        kjss_schools = schools("KJSS")
        ksss_schools = schools("KSSS")

        # Preload class levels
        needed_levels = set(l for grp in LEVELS_BY_PATTERN.values() for l in grp)
        level_map = {
            cl.code: cl
            for cl in EmisClassLevel.objects.filter(code__in=needed_levels)
        }
        missing = needed_levels - set(level_map.keys())
        if missing:
            raise CommandError(f"Missing EmisClassLevel codes: {sorted(missing)}")

        # Plan the work (how many students per school)
        plan = []
        for prefix, schools_list in [
            ("KPS", kps_schools),
            ("KJSS", kjss_schools),
            ("KSSS", ksss_schools),
        ]:
            levels = LEVELS_BY_PATTERN[prefix]
            for sch in schools_list:
                n = pick_size_bucket()
                plan.append((sch, levels, n))

        if dry_run:
            total = sum(n for _, _, n in plan)
            self.stdout.write(self.style.WARNING("--- DRY RUN ---"))
            self.stdout.write(f"Target year: {year_code}")
            self.stdout.write(f"Schools: KPS={len(kps_schools)}  KJSS={len(kjss_schools)}  KSSS={len(ksss_schools)}")
            self.stdout.write(f"Total new students planned: {total}")
            self.stdout.write("Sample (first 10 rows):")
            for sch, levels, n in plan[:10]:
                self.stdout.write(f"  {sch.emis_school_no} → {n} students across levels {levels}")
            return

        created_students = 0
        created_enrols = 0

        with transaction.atomic():
            for sch, levels, n in plan:
                for _ in range(n):
                    # Choose a level valid for the school pattern
                    lvl_code = random.choice(levels)
                    lvl = level_map[lvl_code]

                    # Build student with name + age-appropriate DOB
                    first, last = pick_name()
                    # Ensure duplicate names still acceptable; if you want stricter uniqueness, add a suffix
                    if random.random() < 0.1:
                        # 10% chance to append a letter to reduce identical collisions visually
                        last += " " + random.choice(string.ascii_uppercase)

                    student = Student.objects.create(
                        first_name=first,
                        last_name=last,
                        date_of_birth=dob_for_level(lvl_code, year_code),
                    )
                    created_students += 1

                    enrol = StudentSchoolEnrolment.objects.create(
                        student=student,
                        school=sch,
                        school_year=wy,
                        class_level=lvl,
                        # disability flags, randomized
                        seeing_flag=random_bool(),
                        hearing_flag=random_bool(),
                        mobility_flag=random_bool(),
                        fine_motor_flag=random_bool(),
                        speech_flag=random_bool(),
                        learning_flag=random_bool(),
                        memory_flag=random_bool(),
                        attention_flag=random_bool(),
                        behaviour_flag=random_bool(),
                        social_flag=random_bool(),
                        anxiety_freq=random_freq_or_none(),
                        depression_freq=random_freq_or_none(),
                    )
                    created_enrols += 1

        self.stdout.write(self.style.SUCCESS(
            f"Done. Created {created_students} students and {created_enrols} enrolments for year {year_code}."
        ))
