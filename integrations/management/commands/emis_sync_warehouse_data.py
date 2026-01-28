"""
Management command to sync enrollment data from EMIS warehouse OData.

Fetches enrollment data, aggregates it, and stores on filesystem for fast dashboard access.

Usage:
    python manage.py sync_enrollment_data
    python manage.py sync_enrollment_data --force  # Force refresh even if recent
"""
import json
import pickle
from pathlib import Path
from datetime import datetime

from django.core.management.base import BaseCommand
from django.conf import settings

from integrations.odata_client import ODataClient


class Command(BaseCommand):
    help = 'Sync enrollment data from EMIS warehouse OData and cache aggregated results'

    def add_arguments(self, parser):
        parser.add_argument(
            '--force',
            action='store_true',
            help='Force refresh even if cache is recent',
        )
        parser.add_argument(
            '--format',
            type=str,
            default='pickle',
            choices=['pickle', 'json'],
            help='Storage format (pickle is faster, json is human-readable)',
        )

    def handle(self, *args, **options):
        force = options['force']
        storage_format = options['format']

        self.stdout.write(self.style.SUCCESS('=' * 80))
        self.stdout.write(self.style.SUCCESS('ENROLLMENT DATA SYNC'))
        self.stdout.write(self.style.SUCCESS('=' * 80))

        # Setup data directory
        data_dir = Path(settings.BASE_DIR) / "data"
        data_dir.mkdir(exist_ok=True)

        cache_file = data_dir / f"enrollment_aggregated.{storage_format}"
        metadata_file = data_dir / "enrollment_metadata.json"

        # Check if refresh needed
        if not force and cache_file.exists() and metadata_file.exists():
            try:
                with open(metadata_file, 'r') as f:
                    metadata = json.load(f)
                last_sync = datetime.fromisoformat(metadata['last_sync'])
                age_hours = (datetime.now() - last_sync).total_seconds() / 3600

                self.stdout.write(f'\nCache file exists: {cache_file}')
                self.stdout.write(f'Last sync: {last_sync} ({age_hours:.1f} hours ago)')
                self.stdout.write(f'Records: {metadata.get("record_count", "unknown")}')

                if age_hours < 24:
                    self.stdout.write(self.style.WARNING('\n⚠️  Cache is less than 24 hours old'))
                    self.stdout.write('Use --force to refresh anyway')
                    return
            except Exception as e:
                self.stdout.write(self.style.WARNING(f'Could not read metadata: {e}'))

        self.stdout.write('\n' + self.style.HTTP_INFO('1. FETCHING DATA FROM ODATA'))
        self.stdout.write('-' * 80)

        try:
            odata_client = ODataClient()
            self.stdout.write(f'Fetching from: {settings.EMIS["ODATA_URL"]}/EnrolSchool')
            self.stdout.write('This may take 30-60 seconds for ~120k records...\n')

            # Fetch all enrollment data from OData warehouse
            enrollment_data = odata_client.get_enrolment_by_school(
                filters=None,
                select=None
            )

            self.stdout.write(self.style.SUCCESS(f'✓ Fetched {len(enrollment_data):,} records'))

        except Exception as e:
            self.stdout.write(self.style.ERROR(f'\n❌ Failed to fetch data: {e}'))
            raise

        self.stdout.write('\n' + self.style.HTTP_INFO('2. AGGREGATING DATA'))
        self.stdout.write('-' * 80)
        self.stdout.write('Aggregating by (SurveyYear, SchoolNo, SchoolName, GenderCode) → Sum(Enrol)\n')

        # Aggregate enrollment data
        # Key: (SurveyYear, SchoolNo, SchoolName, GenderCode) → Value: total enrollment
        aggregated = {}

        for record in enrollment_data:
            survey_year = record.get('SurveyYear')
            school_no = record.get('SchoolNo')
            school_name = record.get('SchoolName')
            gender_code = record.get('GenderCode')
            enrol = record.get('Enrol') or 0

            if survey_year and school_no:
                key = (
                    int(survey_year),
                    str(school_no),
                    str(school_name) if school_name else '',
                    str(gender_code) if gender_code else 'U'  # Unknown
                )
                aggregated[key] = aggregated.get(key, 0) + enrol

        self.stdout.write(self.style.SUCCESS(f'✓ Aggregated to {len(aggregated):,} unique combinations'))

        # Convert to list of dicts for easier access
        enrollment_records = [
            {
                'SurveyYear': key[0],
                'SchoolNo': key[1],
                'SchoolName': key[2],
                'GenderCode': key[3],
                'Enrol': value
            }
            for key, value in aggregated.items()
        ]

        self.stdout.write('\n' + self.style.HTTP_INFO('3. SAVING TO FILESYSTEM'))
        self.stdout.write('-' * 80)

        try:
            # Save aggregated data
            if storage_format == 'pickle':
                with open(cache_file, 'wb') as f:
                    pickle.dump(enrollment_records, f)
                self.stdout.write(f'✓ Saved {len(enrollment_records):,} records to {cache_file.name} (pickle)')
            else:  # json
                with open(cache_file, 'w', encoding='utf-8') as f:
                    json.dump(enrollment_records, f)
                self.stdout.write(f'✓ Saved {len(enrollment_records):,} records to {cache_file.name} (json)')

            # Save metadata
            metadata = {
                'last_sync': datetime.now().isoformat(),
                'record_count': len(enrollment_records),
                'source_record_count': len(enrollment_data),
                'format': storage_format,
                'endpoint': f'{settings.EMIS["ODATA_URL"]}/EnrolSchool',
            }

            with open(metadata_file, 'w') as f:
                json.dump(metadata, f, indent=2)
            self.stdout.write(f'✓ Saved metadata to {metadata_file.name}')

            # Calculate file size
            file_size_mb = cache_file.stat().st_size / (1024 * 1024)
            self.stdout.write(f'✓ File size: {file_size_mb:.2f} MB')

        except Exception as e:
            self.stdout.write(self.style.ERROR(f'\n❌ Failed to save data: {e}'))
            raise

        self.stdout.write('\n' + self.style.HTTP_INFO('4. SUMMARY'))
        self.stdout.write('-' * 80)
        self.stdout.write(f'Source records: {len(enrollment_data):,}')
        self.stdout.write(f'Aggregated records: {len(enrollment_records):,}')
        self.stdout.write(f'Storage format: {storage_format}')
        self.stdout.write(f'File: {cache_file}')

        # Show sample data
        if enrollment_records:
            self.stdout.write('\nSample records:')
            for rec in enrollment_records[:3]:
                self.stdout.write(f'  {rec}')

        # Show years and schools
        years = sorted(set(r['SurveyYear'] for r in enrollment_records))
        schools = len(set(r['SchoolNo'] for r in enrollment_records))
        self.stdout.write(f'\nYears: {years}')
        self.stdout.write(f'Schools: {schools}')

        self.stdout.write('\n' + self.style.SUCCESS('=' * 80))
        self.stdout.write(self.style.SUCCESS('✓ ENROLLMENT DATA SYNC COMPLETE'))
        self.stdout.write(self.style.SUCCESS('=' * 80))
        self.stdout.write('\nNext steps:')
        self.stdout.write('  - Dashboard will now load enrollment data instantly from cache')
        self.stdout.write('  - Run this command periodically (e.g., daily via cron) to keep data fresh')
        self.stdout.write('  - Use --force to refresh even if cache is recent')
