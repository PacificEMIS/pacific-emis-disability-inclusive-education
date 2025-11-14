import random
import string
from datetime import date, timedelta
from typing import List, Tuple

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from inclusive_ed.models import Student, StudentSchoolEnrolment
from integrations.models import EmisSchool, EmisWarehouseYear, EmisClassLevel

# Expanded pools to reduce duplicate names
FIRST_NAMES = [
    "Ari", "Ben", "Cita", "Dani", "Eli", "Fina", "Gabe", "Hana", "Ika",
    "Jori", "Keni", "Lani", "Mika", "Niko", "Ona", "Pasi", "Rina", "Sami",
    "Tala", "Vika", "Wena", "Yani", "Zora",
    "Alani", "Beniata", "Corin", "Dela", "Emani", "Fatu", "Gina", "Hiko",
    "Inia", "Jona", "Keani", "Loma", "Malo", "Naea", "Olia", "Peni",
    "Ratu", "Sione", "Tasi", "Ula", "Vani", "Waqa", "Yara", "Zeni",
]

LAST_NAMES = [
    "Abel", "Beni", "Cabral", "Dano", "Emani", "Faro", "Gonzales", "Hare",
    "Isamu", "Jorin", "Katoa", "Loto", "Malo", "Nase", "Oto", "Paea",
    "Ratu", "Sione", "Taito", "Ula", "Vakalahi", "Waqa", "Yano", "Zed",
    "Akau", "Bale", "Cama", "Delai", "Eroni", "Fale", "Galo", "Hani",
    "Isoa", "Jope", "Koro", "Langi", "Mata", "Nuku", "Osea", "Pule",
    "Raea", "Saka", "Taito", "Uati", "Vera", "Wani", "Yale", "Zola",
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


def random_yes_no_or_none(p_yes: float = 0.15, p_none: float = 0.4) -> int | None:
    """
    Return 1 (Yes), 2 (No) or None.

    Default: about 40% None (not recorded), 15% Yes, 45% No.
    """
    r = random.random()
    if r < p_none:
        return None
    r2 = random.random()
    if r2 < p_yes / (1 - p_none):
        return 1  # Yes
    return 2      # No


def random_difficulty_or_none(p_none: float = 0.5) -> int | None:
    """
    Return a difficulty level: 1–4 or None.

    Skewed towards 'No difficulty' and 'Some difficulty'.
    """
    if random.random() < p_none:
        return None

    # Weighted choice: 1 (50%), 2 (30%), 3 (15%), 4 (5%)
    r = random.random()
    if r < 0.5:
        return 1
    elif r < 0.8:
        return 2
    elif r < 0.95:
        return 3
    else:
        return 4


def random_emotional_freq_or_none(p_none: float = 0.5) -> int | None:
    """
    Return an emotional frequency: 1–5 or None.

    Skewed so that 'Never' and 'A few times a year' are more common.
    """
    if random.random() < p_none:
        return None

    # 1: Daily, 2: Weekly, 3: Monthly, 4: Few times a year, 5: Never
    r = random.random()
    if r < 0.05:
        return 1  # Daily
    elif r < 0.15:
        return 2  # Weekly
    elif r < 0.30:
        return 3  # Monthly
    elif r < 0.55:
        return 4  # A few times a year
    else:
        return 5  # Never


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
    help = "Seed sample Inclusive Ed data (Students + single Enrolment each) for a given school_year."

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
            self.stdout.write(
                f"Schools: KPS={len(kps_schools)}  KJSS={len(kjss_schools)}  KSSS={len(ksss_schools)}"
            )
            self.stdout.write(f"Total new students planned: {total}")
            self.stdout.write("Sample (first 10 rows):")
            for sch, levels, n in plan[:10]:
                self.stdout.write(
                    f"  {sch.emis_school_no} → {n} students across levels {levels}"
                )
            return

        created_students = 0
        created_enrols = 0

        # Track name combinations to reduce duplicates across all schools
        names_used: set[tuple[str, str]] = set()

        with transaction.atomic():
            for sch, levels, n in plan:
                for _ in range(n):
                    # Choose a level valid for the school pattern
                    lvl_code = random.choice(levels)
                    lvl = level_map[lvl_code]

                    # Build student with name + age-appropriate DOB
                    # Try a few times to get a name combo not already used
                    for _tries in range(5):
                        first, last = pick_name()
                        if (first, last) not in names_used:
                            break
                    names_used.add((first, last))

                    # Occasionally add a letter to last name to visually break ties
                    if random.random() < 0.05:
                        last = f"{last} {random.choice(string.ascii_uppercase)}"

                    student = Student.objects.create(
                        first_name=first,
                        last_name=last,
                        date_of_birth=dob_for_level(lvl_code, year_code),
                    )
                    created_students += 1

                    # CFT 1–20: randomized but with realistic distributions
                    StudentSchoolEnrolment.objects.create(
                        student=student,
                        school=sch,
                        school_year=wy,
                        class_level=lvl,
                        cft1_wears_glasses=random_yes_no_or_none(),
                        cft2_difficulty_seeing_with_glasses=random_difficulty_or_none(),
                        cft3_difficulty_seeing=random_difficulty_or_none(),
                        cft4_has_hearing_aids=random_yes_no_or_none(),
                        cft5_difficulty_hearing_with_aids=random_difficulty_or_none(),
                        cft6_difficulty_hearing=random_difficulty_or_none(),
                        cft7_uses_walking_equipment=random_yes_no_or_none(),
                        cft8_difficulty_walking_without_equipment=random_difficulty_or_none(),
                        cft9_difficulty_walking_with_equipment=random_difficulty_or_none(),
                        cft10_difficulty_walking_compare_to_others=random_difficulty_or_none(),
                        cft11_difficulty_picking_up_small_objects=random_difficulty_or_none(),
                        cft12_difficulty_being_understood=random_difficulty_or_none(),
                        cft13_difficulty_learning=random_difficulty_or_none(),
                        cft14_difficulty_remembering=random_difficulty_or_none(),
                        cft15_difficulty_concentrating=random_difficulty_or_none(),
                        cft16_difficulty_accepting_change=random_difficulty_or_none(),
                        cft17_difficulty_controlling_behaviour=random_difficulty_or_none(),
                        cft18_difficulty_making_friends=random_difficulty_or_none(),
                        cft19_anxious_frequency=random_emotional_freq_or_none(),
                        cft20_depressed_frequency=random_emotional_freq_or_none(),
                    )
                    created_enrols += 1

        self.stdout.write(
            self.style.SUCCESS(
                f"Done. Created {created_students} students and {created_enrols} enrolments for year {year_code}."
            )
        )
