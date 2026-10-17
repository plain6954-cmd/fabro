import csv
import json
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from management.models import (
    Brand, Model, SubModel, YearRange, MasterSetting,
    format_pattern_serial, get_country_letter,
    Complaint, PatternDesignFolder, PatternDesignImage, VehicleDriveLink, PatternEditLog
)


def clean(value):
    return (value or '').strip()


def parse_number(value, label, row_number):
    val = clean(value)
    if not val:
        return None
    try:
        return int(float(val))
    except (ValueError, TypeError) as exc:
        raise CommandError(f'Row {row_number}: invalid {label} value {value!r}.') from exc


class Command(BaseCommand):
    help = (
        'Safely replace Pattern Master catalog records from the October 17 CSV '
        'while preserving existing relationships, approvals, and workflows.'
    )

    CONFIRMATION_TOKEN = 'REPLACE-PATTERNS-OCT17'

    def add_arguments(self, parser):
        parser.add_argument('csv_path', type=Path, help='Path to source CSV file.')
        parser.add_argument(
            '--apply', action='store_true',
            help='Commit changes to the database. Without this flag, runs in dry-run mode.',
        )
        parser.add_argument(
            '--backup-file', type=Path, default=Path('backup_yearrange_pre_migration.json'),
            help='Path to verified JSON backup file of existing YearRange records.',
        )
        parser.add_argument(
            '--confirm-token', type=str, default='',
            help=f'Confirmation token required when running with --apply ({self.CONFIRMATION_TOKEN}).',
        )

    def handle(self, *args, **options):
        csv_path = options['csv_path']
        is_apply = options['apply']
        backup_file = options['backup_file']
        confirm_token = options['confirm_token']

        self.stdout.write(self.style.NOTICE(f'=== FABRO Pattern Master CSV Import & Replacement ==='))
        self.stdout.write(f'Source CSV: {csv_path}')
        self.stdout.write(f'Mode: {"APPLY (PRODUCTION WRITE)" if is_apply else "DRY-RUN (NO CHANGES SAVED)"}')

        # 1. Verification of inputs
        if not csv_path.is_file():
            raise CommandError(f'CSV file does not exist: {csv_path}')

        if not backup_file.is_file():
            raise CommandError(
                f'Restorable backup file does not exist: {backup_file}. '
                f'Create a backup using "python manage.py dumpdata management.YearRange --indent 2 -o {backup_file}" first.'
            )

        self._verify_backup(backup_file)

        if is_apply and confirm_token != self.CONFIRMATION_TOKEN:
            raise CommandError(
                f'Execution blocked: --apply requires --confirm-token {self.CONFIRMATION_TOKEN}'
            )

        # 2. Master settings verification
        gcc_country = MasterSetting.objects.filter(category='Country', name__iexact='GCC').first()
        ksa_country = MasterSetting.objects.filter(category='Country', name__iexact='KSA').first()
        if not gcc_country:
            raise CommandError("MasterSetting for Country 'GCC' not found in database.")
        if not ksa_country:
            raise CommandError("MasterSetting for Country 'KSA' not found in database.")

        # Prefix is determined according to Measurement Country (KSA)
        expected_prefix = get_country_letter(ksa_country)
        self.stdout.write(f'Measurement Country: {ksa_country.name} (Prefix: {expected_prefix})')
        if expected_prefix != 'S':
            raise CommandError(f'Expected prefix for KSA is S, but got {expected_prefix!r}. Aborting.')

        # 3. Read and validate CSV
        rows = self._read_and_validate_csv(csv_path, expected_prefix)
        self.stdout.write(self.style.SUCCESS(f'Validated {len(rows)} records from CSV.'))

        # 4. Dependency analysis and execution inside atomic transaction
        with transaction.atomic():
            dep_report = self._audit_dependencies()
            self._print_dependency_report(dep_report)

            self.stdout.write('Staging brand, model, and variant records...')
            self._stage_catalogs(rows)

            self.stdout.write('Performing safe update and remapping...')
            created_count, updated_count, deleted_count = self._execute_safe_replacement(
                rows, gcc_country, ksa_country
            )

            self.stdout.write('Verifying imported records against source CSV...')
            self._verify_import(rows, gcc_country, ksa_country)

            final_count = YearRange.objects.count()
            self.stdout.write(f'Final Pattern Master record count: {final_count}')
            if final_count != 221:
                raise CommandError(f'Expected exactly 221 Pattern Master records, but got {final_count}!')

            if not is_apply:
                transaction.set_rollback(True)
                self.stdout.write(self.style.WARNING(
                    '\n[DRY RUN COMPLETE] All validations and verifications passed. Database rolled back cleanly.'
                ))
            else:
                self.stdout.write(self.style.SUCCESS(
                    f'\n[APPLY SUCCESSFUL] {created_count} created, {updated_count} updated, '
                    f'{deleted_count} obsolete records safely removed. Exactly 221 records active.'
                ))

    def _verify_backup(self, backup_file):
        try:
            with backup_file.open('r', encoding='utf-8') as f:
                data = json.load(f)
            if not isinstance(data, list) or len(data) == 0:
                raise CommandError(f'Backup file {backup_file} is empty or invalid format.')
            self.stdout.write(self.style.SUCCESS(f'Verified backup file {backup_file}: {len(data)} records.'))
        except Exception as e:
            raise CommandError(f'Failed to verify backup file {backup_file}: {e}') from e

    def _read_and_validate_csv(self, csv_path, expected_prefix):
        rows = []
        seen_serials = set()
        seen_nos = set()

        with csv_path.open('r', encoding='utf-8-sig', newline='') as stream:
            reader = csv.DictReader(stream)
            required_cols = {
                'No', 'Brand', 'Model', 'Year Start', 'Year End', 'Sub Model',
                'Variant', 'Doors', 'Seats', 'X', 'Fitting Confirm',
                'VEHICLE COUNTRY', 'MEASUREMENT COUNTRY', 'DRIVE'
            }
            missing = required_cols.difference(reader.fieldnames or [])
            if missing:
                raise CommandError(f'Missing required CSV columns: {", ".join(sorted(missing))}')

            allowed_fitting = {'Confirmed', 'Pending', 'Sampling', ''}

            for row_idx, row in enumerate(reader, start=1):
                raw_no = clean(row['No'])
                if not raw_no:
                    raise CommandError(f'Row {row_idx}: missing serial No.')
                if raw_no in seen_nos:
                    raise CommandError(f'Row {row_idx}: duplicate serial No {raw_no}.')
                seen_nos.add(raw_no)

                serial_num = int(raw_no)
                serial = f"{expected_prefix}{serial_num:04d}"
                if serial in seen_serials:
                    raise CommandError(f'Row {row_idx}: duplicate pattern serial {serial}.')
                seen_serials.add(serial)

                brand = clean(row['Brand']).upper()
                model = clean(row['Model']).upper()
                if not brand or not model:
                    raise CommandError(f'Row {row_idx}: Brand and Model are required.')

                year_start = parse_number(row['Year Start'], 'Year Start', row_idx)
                year_end = parse_number(row['Year End'], 'Year End', row_idx)
                if year_start is None or year_end is None:
                    raise CommandError(f'Row {row_idx}: Year Start and Year End are required.')
                if year_end < year_start:
                    raise CommandError(f'Row {row_idx}: Year End ({year_end}) < Year Start ({year_start}).')

                fitting = clean(row['Fitting Confirm'])
                if fitting and fitting not in allowed_fitting:
                    # Case-insensitive normalization
                    match = [opt for opt in allowed_fitting if opt.lower() == fitting.lower()]
                    if match:
                        fitting = match[0]
                    else:
                        raise CommandError(f'Row {row_idx}: invalid Fitting Confirm {fitting!r}.')

                vc = clean(row['VEHICLE COUNTRY']).upper()
                mc = clean(row['MEASUREMENT COUNTRY']).upper()
                drive = clean(row['DRIVE']).upper()

                if vc != 'GCC':
                    raise CommandError(f'Row {row_idx}: expected VEHICLE COUNTRY "GCC", got {vc!r}.')
                if mc != 'KSA':
                    raise CommandError(f'Row {row_idx}: expected MEASUREMENT COUNTRY "KSA", got {mc!r}.')
                if drive != 'LHD':
                    raise CommandError(f'Row {row_idx}: expected DRIVE "LHD", got {drive!r}.')

                rows.append({
                    'row_idx': row_idx,
                    'no': raw_no,
                    'serial': serial,
                    'brand': brand,
                    'model': model,
                    'year_start': year_start,
                    'year_end': year_end,
                    'sub_model': clean(row['Sub Model']).upper(),  # Maps to YearRange.br
                    'variant': clean(row['Variant']).upper() or '-',  # Maps to YearRange.sub_model
                    'doors': parse_number(row['Doors'], 'Doors', row_idx),
                    'seats': parse_number(row['Seats'], 'Seats', row_idx),
                    'x_code': clean(row['X']).upper(),
                    'fitting': fitting,
                    'vehicle_country': vc,
                    'measurement_country': mc,
                    'drive': drive,
                })

        if len(rows) != 221:
            raise CommandError(f'Expected exactly 221 rows in CSV, found {len(rows)}.')
        return rows

    def _audit_dependencies(self):
        complaints = list(Complaint.objects.filter(year__isnull=False).select_related('year'))
        folders = list(PatternDesignFolder.objects.select_related('vehicle').all())
        direct_images = list(PatternDesignImage.objects.filter(vehicle__isnull=False).select_related('vehicle'))
        drive_links = list(VehicleDriveLink.objects.select_related('vehicle').all())
        edit_logs = list(PatternEditLog.objects.filter(year_range__isnull=False).select_related('year_range'))

        return {
            'complaints': complaints,
            'folders': folders,
            'direct_images': direct_images,
            'drive_links': drive_links,
            'edit_logs': edit_logs,
        }

    def _print_dependency_report(self, report):
        self.stdout.write(self.style.NOTICE('\n--- Dependency Audit Report ---'))
        self.stdout.write(f'Complaints referencing YearRange: {len(report["complaints"])}')
        for c in report['complaints']:
            self.stdout.write(f'  • Complaint {c.complaint_id} -> YearRange {c.year.id} ({c.year.serial_number})')

        self.stdout.write(f'Design Folders referencing YearRange: {len(report["folders"])}')
        for f in report['folders']:
            self.stdout.write(f'  • Folder {f.id} "{f.name}" -> YearRange {f.vehicle.id} ({f.vehicle.serial_number})')

        self.stdout.write(f'Direct Design Images referencing YearRange: {len(report["direct_images"])}')
        for img in report['direct_images']:
            self.stdout.write(f'  • Image {img.id} "{img.title}" -> YearRange {img.vehicle.id} ({img.vehicle.serial_number})')

        self.stdout.write(f'Google Drive Links referencing YearRange: {len(report["drive_links"])}')
        for dl in report['drive_links']:
            self.stdout.write(f'  • DriveLink {dl.id} "{dl.title}" -> YearRange {dl.vehicle.id} ({dl.vehicle.serial_number})')
        self.stdout.write('--------------------------------\n')

    def _stage_catalogs(self, rows):
        # 1. Brands
        brand_map = {item.name.upper(): item for item in Brand.objects.all()}
        missing_brands = sorted({row['brand'] for row in rows}.difference(brand_map))
        if missing_brands:
            Brand.objects.bulk_create([Brand(name=name) for name in missing_brands])
            brand_map = {item.name.upper(): item for item in Brand.objects.all()}

        # 2. Models
        model_map = {(item.brand.name.upper(), item.name.upper()): item
                     for item in Model.objects.select_related('brand')}
        missing_models = sorted({(row['brand'], row['model']) for row in rows}.difference(model_map))
        if missing_models:
            Model.objects.bulk_create([
                Model(brand=brand_map[brand], name=name)
                for brand, name in missing_models
            ])
            model_map = {(item.brand.name.upper(), item.name.upper()): item
                         for item in Model.objects.select_related('brand')}

        # 3. SubModels (representing Variants)
        sub_map = {(item.model.brand.name.upper(), item.model.name.upper(), item.name.upper()): item
                   for item in SubModel.objects.select_related('model__brand')}
        missing_subs = sorted({(row['brand'], row['model'], row['variant']) for row in rows}.difference(sub_map))
        if missing_subs:
            SubModel.objects.bulk_create([
                SubModel(model=model_map[(brand, model)], name=name)
                for brand, model, name in missing_subs
            ])

    def _execute_safe_replacement(self, rows, gcc_country, ksa_country):
        sub_map = {(item.model.brand.name.upper(), item.model.name.upper(), item.name.upper()): item
                   for item in SubModel.objects.select_related('model__brand')}

        target_serials = [r['serial'] for r in rows]

        # Existing records mapped by serial
        existing_by_serial = {
            yr.serial_number.upper(): yr
            for yr in YearRange.objects.filter(serial_number__in=target_serials)
        }

        # Clear layout codes on existing records first to prevent transient unique collisions
        YearRange.objects.filter(serial_number__in=target_serials).update(layout_code=None)

        created_objs = []
        updated_objs = []

        for row in rows:
            yr = existing_by_serial.get(row['serial'].upper())
            if yr is None:
                yr = YearRange(serial_number=row['serial'])
                created_objs.append(yr)
            else:
                updated_objs.append(yr)

            yr.sub_model = sub_map[(row['brand'], row['model'], row['variant'])]
            yr.year_start = row['year_start']
            yr.year_end = row['year_end']
            yr.br = row['sub_model']  # Sub Model stored in br
            yr.number_of_seats = row['seats']
            yr.number_of_doors = row['doors']
            yr.x_code = row['x_code']
            # Only set layout_code if unique and non-empty
            yr.layout_code = None
            yr.fitting_confirmation = row['fitting']
            yr.vehicle_country = gcc_country
            yr.measurement_country = ksa_country
            yr.drive = row['drive']

        if created_objs:
            YearRange.objects.bulk_create(created_objs, batch_size=250)
        if updated_objs:
            YearRange.objects.bulk_update(
                updated_objs,
                [
                    'sub_model', 'year_start', 'year_end', 'br', 'number_of_seats',
                    'number_of_doors', 'x_code', 'layout_code', 'fitting_confirmation',
                    'vehicle_country', 'measurement_country', 'drive'
                ],
                batch_size=250
            )

        # Re-fetch the 221 active records
        active_records = {
            yr.serial_number.upper(): yr
            for yr in YearRange.objects.filter(serial_number__in=target_serials)
        }

        # Safely remap historical records outside the 001-221 set that have dependencies
        # Specifically:
        # S0237 (MAZDA CX-60 2025-2026) -> remap to S0198
        # S0229 (RENAULT DUSTER 2012-2013) -> remap to S0209
        # S0242 (KIA SONET 2020-2026) -> remap to S0217
        self._remap_historical_dependencies(active_records)

        # Now identify obsolete records outside target_serials
        obsolete_qs = YearRange.objects.exclude(serial_number__in=target_serials)
        obsolete_count = obsolete_qs.count()

        # Verify that NO active foreign keys remain on obsolete records before deletion
        for obs in obsolete_qs:
            if obs.complaint_set.exists():
                raise CommandError(f'Cannot delete obsolete YearRange {obs.id}: active complaint linked!')
            if obs.design_folders.exists():
                raise CommandError(f'Cannot delete obsolete YearRange {obs.id}: active design folder linked!')
            if obs.direct_design_images.exists():
                raise CommandError(f'Cannot delete obsolete YearRange {obs.id}: active design image linked!')
            if obs.drive_links.exists():
                raise CommandError(f'Cannot delete obsolete YearRange {obs.id}: active drive link linked!')

        deleted_count, _ = obsolete_qs.delete()
        return len(created_objs), len(updated_objs), deleted_count

    def _remap_historical_dependencies(self, active_records):
        remapping_targets = {
            'S0237': 'S0198',  # MAZDA CX-60
            'S0229': 'S0209',  # RENAULT DUSTER
            'S0242': 'S0217',  # KIA SONET
        }
        for old_serial, new_serial in remapping_targets.items():
            old_yr = YearRange.objects.filter(serial_number=old_serial).first()
            new_yr = active_records.get(new_serial)
            if old_yr and new_yr:
                # Remap folders
                old_yr.design_folders.update(vehicle=new_yr)
                # Remap direct images
                old_yr.direct_design_images.update(vehicle=new_yr)
                # Remap drive links
                old_yr.drive_links.update(vehicle=new_yr)
                # Remap complaints
                old_yr.complaint_set.update(year=new_yr)
                # Remap edit logs
                old_yr.edit_logs.update(year_range=new_yr)
                self.stdout.write(
                    self.style.SUCCESS(f'Remapped dependencies from historical {old_serial} to {new_serial} ({new_yr.id}).')
                )

    def _verify_import(self, rows, gcc_country, ksa_country):
        vehicles = {
            yr.serial_number.upper(): yr
            for yr in YearRange.objects.filter(
                serial_number__in=[r['serial'] for r in rows]
            ).select_related('sub_model__model__brand', 'vehicle_country', 'measurement_country')
        }

        mismatches = []
        for r in rows:
            v = vehicles.get(r['serial'].upper())
            if v is None:
                mismatches.append((r['serial'], 'Missing in database'))
                continue

            actual_brand = v.sub_model.model.brand.name.upper()
            actual_model = v.sub_model.model.name.upper()
            actual_variant = v.sub_model.name.upper()
            actual_sub_model = v.br.upper()
            actual_ys = v.year_start
            actual_ye = v.year_end
            actual_doors = v.number_of_doors
            actual_seats = v.number_of_seats
            actual_x = v.x_code.upper()
            actual_fitting = v.fitting_confirmation
            actual_vc = v.vehicle_country.name if v.vehicle_country else ''
            actual_mc = v.measurement_country.name if v.measurement_country else ''
            actual_drive = v.drive.upper()

            expected_variant = r['variant']
            expected_sub_model = r['sub_model']

            if actual_brand != r['brand']:
                mismatches.append((r['serial'], f'Brand: {actual_brand} != {r["brand"]}'))
            elif actual_model != r['model']:
                mismatches.append((r['serial'], f'Model: {actual_model} != {r["model"]}'))
            elif actual_ys != r['year_start']:
                mismatches.append((r['serial'], f'Year Start: {actual_ys} != {r["year_start"]}'))
            elif actual_ye != r['year_end']:
                mismatches.append((r['serial'], f'Year End: {actual_ye} != {r["year_end"]}'))
            elif actual_sub_model != expected_sub_model:
                mismatches.append((r['serial'], f'Sub Model: {actual_sub_model} != {expected_sub_model}'))
            elif actual_variant != expected_variant:
                mismatches.append((r['serial'], f'Variant: {actual_variant} != {expected_variant}'))
            elif actual_doors != r['doors']:
                mismatches.append((r['serial'], f'Doors: {actual_doors} != {r["doors"]}'))
            elif actual_seats != r['seats']:
                mismatches.append((r['serial'], f'Seats: {actual_seats} != {r["seats"]}'))
            elif actual_x != r['x_code']:
                mismatches.append((r['serial'], f'X-Code: {actual_x} != {r["x_code"]}'))
            elif actual_fitting != r['fitting']:
                mismatches.append((r['serial'], f'Fitting: {actual_fitting} != {r["fitting"]}'))
            elif actual_vc != 'GCC':
                mismatches.append((r['serial'], f'Vehicle Country: {actual_vc} != GCC'))
            elif actual_mc != 'KSA':
                mismatches.append((r['serial'], f'Measurement Country: {actual_mc} != KSA'))
            elif actual_drive != 'LHD':
                mismatches.append((r['serial'], f'Drive: {actual_drive} != LHD'))

        if mismatches:
            preview = '\n'.join([f'  • {serial}: {reason}' for serial, reason in mismatches[:10]])
            raise CommandError(f'Import verification failed ({len(mismatches)} mismatches):\n{preview}')
        self.stdout.write(self.style.SUCCESS('Verification passed: All 221 records match CSV source exactly.'))
