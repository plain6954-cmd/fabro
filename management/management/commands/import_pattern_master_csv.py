import csv
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from management.models import Brand, Model, SubModel, YearRange, format_pattern_serial


def clean(value):
    return (value or '').strip()


def number(value, label, row_number):
    value = clean(value)
    if not value:
        return None
    try:
        return int(float(value))
    except ValueError as exc:
        raise CommandError(f'Row {row_number}: invalid {label} value {value!r}.') from exc


class Command(BaseCommand):
    help = 'Upsert every Pattern Master row from the approved Google Sheet CSV export.'

    def add_arguments(self, parser):
        parser.add_argument('csv_path', type=Path)
        parser.add_argument(
            '--apply', action='store_true',
            help='Commit changes. Without this flag the command performs a rolled-back dry run.',
        )

    def handle(self, *args, **options):
        csv_path = options['csv_path']
        if not csv_path.is_file():
            raise CommandError(f'CSV file does not exist: {csv_path}')
        rows = self._read_rows(csv_path)
        with transaction.atomic():
            created, updated = self._upsert(rows)
            self._verify(rows)
            if not options['apply']:
                transaction.set_rollback(True)
        mode = 'APPLIED' if options['apply'] else 'DRY RUN'
        self.stdout.write(self.style.SUCCESS(
            f'{mode}: {created} created, {updated} updated, '
            f'{len(rows)} sheet rows preserved and verified.'
        ))

    def _read_rows(self, csv_path):
        parsed = []
        seen_serials = set()
        with csv_path.open('r', encoding='utf-8-sig', newline='') as stream:
            reader = csv.DictReader(stream)
            required = {'#', 'Brand', 'Model', 'Year Start', 'Year End', 'BR',
                        'Sub Model', 'Doors', 'Seats', 'X', 'Fitting Confirm'}
            missing = required.difference(reader.fieldnames or [])
            if missing:
                raise CommandError(f'Missing required columns: {", ".join(sorted(missing))}')
            for row_number, row in enumerate(reader, start=2):
                brand = clean(row['Brand']).upper()
                model = clean(row['Model']).upper()
                if not brand and not model:
                    continue
                if not brand or not model:
                    raise CommandError(f'Row {row_number}: Brand and Model are required.')
                serial = format_pattern_serial(clean(row['#']))
                if serial in seen_serials:
                    raise CommandError(f'Row {row_number}: duplicate sheet serial {serial}.')
                seen_serials.add(serial)
                parsed.append({
                    'serial': serial,
                    'brand': brand,
                    'model': model,
                    'sub_model': clean(row['Sub Model']).upper() or '-',
                    'year_start': number(row['Year Start'], 'Year Start', row_number),
                    'year_end': number(row['Year End'], 'Year End', row_number),
                    'seats': number(row['Seats'], 'Seats', row_number),
                    'doors': number(row['Doors'], 'Doors', row_number),
                    'br': clean(row['BR']).upper(),
                    'x_code': clean(row['X']).upper(),
                    'fitting': clean(row['Fitting Confirm']).title(),
                })
        return parsed

    def _upsert(self, rows):
        brand_map = {item.name.upper(): item for item in Brand.objects.all()}
        missing = sorted({row['brand'] for row in rows}.difference(brand_map))
        Brand.objects.bulk_create([Brand(name=name) for name in missing])
        brand_map = {item.name.upper(): item for item in Brand.objects.all()}

        model_map = {(item.brand.name.upper(), item.name.upper()): item
                     for item in Model.objects.select_related('brand')}
        missing = sorted({(row['brand'], row['model']) for row in rows}.difference(model_map))
        Model.objects.bulk_create([Model(brand=brand_map[brand], name=name)
                                   for brand, name in missing])
        model_map = {(item.brand.name.upper(), item.name.upper()): item
                     for item in Model.objects.select_related('brand')}

        sub_map = {(item.model.brand.name.upper(), item.model.name.upper(), item.name.upper()): item
                   for item in SubModel.objects.select_related('model__brand')}
        missing = sorted({(row['brand'], row['model'], row['sub_model']) for row in rows}.difference(sub_map))
        SubModel.objects.bulk_create([
            SubModel(model=model_map[(brand, model)], name=name)
            for brand, model, name in missing
        ])
        sub_map = {(item.model.brand.name.upper(), item.model.name.upper(), item.name.upper()): item
                   for item in SubModel.objects.select_related('model__brand')}

        serials = [row['serial'] for row in rows]
        existing = {item.serial_number.upper(): item for item in
                    YearRange.objects.filter(serial_number__in=serials).order_by('id')}
        creates, updates = [], []
        for row in rows:
            vehicle = existing.get(row['serial'])
            if vehicle is None:
                vehicle = YearRange(serial_number=row['serial'])
                creates.append(vehicle)
            else:
                updates.append(vehicle)
            vehicle.sub_model = sub_map[(row['brand'], row['model'], row['sub_model'])]
            vehicle.year_start = row['year_start']
            vehicle.year_end = row['year_end']
            vehicle.br = row['br']
            vehicle.number_of_seats = row['seats']
            vehicle.number_of_doors = row['doors']
            vehicle.x_code = row['x_code']
            vehicle.fitting_confirmation = row['fitting']

        YearRange.objects.bulk_create(creates, batch_size=250)
        YearRange.objects.bulk_update(
            updates,
            ['sub_model', 'year_start', 'year_end', 'br', 'number_of_seats',
             'number_of_doors', 'x_code', 'fitting_confirmation'],
            batch_size=250,
        )
        return len(creates), len(updates)

    def _verify(self, rows):
        vehicles = {
            item.serial_number.upper(): item
            for item in YearRange.objects.filter(
                serial_number__in=[row['serial'] for row in rows]
            ).select_related('sub_model__model__brand')
        }
        mismatches = []
        for row in rows:
            vehicle = vehicles.get(row['serial'])
            actual = None if vehicle is None else (
                vehicle.sub_model.model.brand.name.upper(),
                vehicle.sub_model.model.name.upper(),
                vehicle.year_start,
                vehicle.year_end,
                vehicle.br,
                vehicle.sub_model.name.upper(),
                vehicle.number_of_doors,
                vehicle.number_of_seats,
                vehicle.x_code,
                vehicle.fitting_confirmation,
            )
            expected = (
                row['brand'], row['model'], row['year_start'], row['year_end'],
                row['br'], row['sub_model'], row['doors'], row['seats'],
                row['x_code'], row['fitting'],
            )
            if actual != expected:
                mismatches.append(row['serial'])
        if mismatches:
            preview = ', '.join(mismatches[:10])
            raise CommandError(f'Import verification failed for: {preview}')
