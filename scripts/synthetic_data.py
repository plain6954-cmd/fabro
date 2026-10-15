"""Deterministic, idempotent FABRO navigation fixture for disposable SQLite."""

import json
import os
import secrets
from datetime import date, timedelta
from pathlib import Path

from PIL import Image, ImageDraw


PREFIX = 'navsyn_'
PATTERNS = 300
COMPLAINTS = 400
SKUS = 150
DESIGNS = 180
COMPLAINT_ATTACHMENTS = 100
FIXTURE_DATE = date(2026, 10, 15)
MASTER_VALUES = {
    'Country': ('India', 'KSA', 'UAE'),
    'Channel': ('Synthetic Portal', 'Synthetic Email', 'Synthetic Factory'),
    'Pattern Complaint Type': ('Pattern Fit', 'Cutting Template'),
    'Production Complaint Type': ('Synthetic Stitching', 'Assembly Defect'),
    'Quality Complaint Type': ('Surface Finish', 'Inspection Variance'),
    'Factory Complaint Type': ('Assembly Fitment', 'Line Trial'),
    'Series': ('Test Premium', 'Test Standard'),
    'Material': ('Synthetic Leather A', 'Synthetic Leather B'),
    'Region': ('Synthetic North', 'Synthetic South'),
}


def assert_isolated_database():
    from django.conf import settings
    from django.db import connection

    root = Path(settings.BASE_DIR).resolve()
    existing_local = getattr(settings, 'SYNTHETIC_NAV_TARGET', '') == 'existing-local-db'
    if existing_local and root.name != 'fast-navigation-htmx':
        raise RuntimeError('Existing-local fixture is restricted to the feature worktree.')
    target = (root / ('db.sqlite3' if existing_local else 'output/navigation-synthetic.sqlite3')).resolve()
    media = (root / 'output' / ('navigation-local-media' if existing_local else 'navigation-synthetic-media')).resolve()
    if (not getattr(settings, 'SYNTHETIC_NAV_DB', False)
            or root.name not in {'fast-navigation-htmx', 'fast-navigation-baseline'}
            or root.parent.name != 'output'
            or not (root / '.git').is_file()
            or connection.vendor != 'sqlite'
            or Path(connection.settings_dict['NAME']).resolve() != target
            or Path(settings.MEDIA_ROOT).resolve() != media
            or getattr(settings, 'USE_S3_STORAGE', False)):
        raise RuntimeError('Synthetic seed refused: Django is not on the isolated worktree SQLite database.')
    return root


def local_credentials(root, account_names):
    """Keep generated per-account passwords in an ignored local-only file."""
    from django.conf import settings

    credential_name = ('navigation-local-credentials.json'
                       if getattr(settings, 'SYNTHETIC_NAV_TARGET', '') == 'existing-local-db'
                       else 'navigation-synthetic-credentials.json')
    path = root / 'output' / credential_name
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        payload = json.loads(path.read_text(encoding='utf8'))
        if set(payload.get('users', {})) != set(account_names):
            raise RuntimeError('Credential file has a different account set; inspect it before reseeding.')
        return payload['users'], path
    from django.contrib.auth import get_user_model
    if get_user_model().objects.filter(username__in=account_names).exists():
        raise RuntimeError('Synthetic users exist but their local credential file is missing; '
                           'restore the credential file before reseeding.')
    passwords = {name: secrets.token_urlsafe(32) for name in account_names}
    payload = {'purpose': 'Local disposable FABRO navigation fixture', 'users': passwords}
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        with os.fdopen(descriptor, 'w', encoding='utf8') as output:
            json.dump(payload, output, indent=2)
        os.chmod(path, 0o600)
    except Exception:
        path.unlink(missing_ok=True)
        raise
    return passwords, path


def placeholder(relative_path, number, size):
    """Create a labelled synthetic JPEG, with no customer or production media."""
    from django.conf import settings

    target = (Path(settings.MEDIA_ROOT) / relative_path).resolve()
    target.relative_to(Path(settings.MEDIA_ROOT).resolve())
    if target.exists():
        return target.stat().st_size
    target.parent.mkdir(parents=True, exist_ok=True)
    color = ((number * 37) % 160 + 40, (number * 53) % 150 + 50,
             (number * 29) % 130 + 70)
    image = Image.new('RGB', size, color)
    draw = ImageDraw.Draw(image)
    for stripe in range(8):
        x = (stripe * size[0]) // 8
        draw.rectangle((x, 0, x + size[0] // 25, size[1]),
                       fill=tuple(min(255, channel + stripe * 5) for channel in color))
    draw.text((16, 16), f'SYNTHETIC FABRO {number:04d}', fill='white')
    image.save(target, 'JPEG', quality=78, optimize=True)
    return target.stat().st_size


def seed():
    from django.conf import settings
    from django.contrib.auth import get_user_model
    from django.core.cache import cache
    from django.db import connection, transaction
    from django.utils import timezone
    from management.models import (
        ApprovalRoles, ApprovalStages, Brand, ChatMessage, Complaint,
        ComplaintApproval, ComplaintMedia, ComplaintTimeline, ComplaintTypes,
        DecisionStatuses, FactoryPriorities, MasterSetting, Model,
        PatternAlteration, PatternDesignApproval, PatternDesignFolder,
        PatternDesignImage, SKU, SubModel, UserProfile, WorkflowRoles,
        WorkflowStatuses, YearRange,
    )

    root = assert_isolated_database()
    synthetic_types = (ComplaintTypes.PATTERN, ComplaintTypes.PRODUCTION,
                       ComplaintTypes.QUALITY, ComplaintTypes.LINE)
    synthetic_complaint_ids = {
        f'{ComplaintTypes.PREFIXES[synthetic_types[(number - 1) % 4]]}-2610{(number - 1) // 4 + 1:04d}'
        for number in range(1, COMPLAINTS + 1)
    }
    existing_local = getattr(settings, 'SYNTHETIC_NAV_TARGET', '') == 'existing-local-db'
    unexpected = {
        'users': not existing_local and get_user_model().objects.exclude(username__startswith=PREFIX).exists(),
        'brands': Brand.objects.exclude(name__startswith='SYNTHETIC BRAND').exists(),
        'patterns': YearRange.objects.exclude(layout_code__startswith='NAVSYN-').exists(),
        'skus': SKU.objects.exclude(code__startswith='NAVSYN-SKU-').exists(),
        'complaints': Complaint.objects.exclude(complaint_id__in=synthetic_complaint_ids).exists(),
        'designs': PatternDesignImage.objects.exclude(
            client_upload_key__startswith='navsyn-design-').exists(),
        'master_settings': not existing_local and not set(MasterSetting.objects.values_list('category', 'name')).issubset(
            {(category, name) for category, names in MASTER_VALUES.items() for name in names}),
    }
    if any(unexpected.values()):
        raise RuntimeError(f'Synthetic seed refused: unrelated application records exist ({unexpected}).')
    roles = {
        'admin': (WorkflowRoles.ADMIN, '', True, 'India'),
        'country_ksa': (WorkflowRoles.COUNTRY_EXECUTIVE, '', False, 'KSA'),
        'country_uae': (WorkflowRoles.COUNTRY_EXECUTIVE, '', False, 'UAE'),
        'factory': (WorkflowRoles.FACTORY_EXECUTIVE, '', False, 'India'),
        'registrar': (WorkflowRoles.FACTORY_COMPLAINT_REGISTRAR, '', False, 'India'),
        'viewer': (WorkflowRoles.FACTORY_VIEWER, '', False, 'India'),
        'designer': (WorkflowRoles.FREELANCE_3D_DESIGNER, '', False, 'India'),
        'other_designer': (WorkflowRoles.FREELANCE_3D_DESIGNER, '', False, 'India'),
        **{role.lower(): (WorkflowRoles.APPROVER, role, False, 'India')
           for role in (ApprovalRoles.PM, ApprovalRoles.OM, ApprovalRoles.CAD,
                        ApprovalRoles.ED, ApprovalRoles.MD)},
    }
    names = {role: PREFIX + role for role in roles}
    passwords, credential_path = local_credentials(root, names.values())

    with transaction.atomic():
        masters = {}
        for category, values in MASTER_VALUES.items():
            for value in values:
                masters[(category, value)], _ = MasterSetting.objects.get_or_create(
                    category=category, name=value)

        users = {}
        for role, (workflow_role, approval_role, is_admin, country) in roles.items():
            username = names[role]
            user, created = get_user_model().objects.get_or_create(
                username=username,
                defaults={'email': f'{username}@fabro.test', 'is_staff': is_admin,
                          'is_superuser': is_admin},
            )
            if created:
                user.set_password(passwords[username])
                user.save(update_fields=['password'])
            profile, _ = UserProfile.objects.get_or_create(user=user)
            profile.role = workflow_role
            profile.approval_role = approval_role
            profile.country = masters[('Country', country)]
            profile.can_receive_factory_assignments = role == 'factory'
            profile.save()
            users[role] = user

        brands = []
        submodels = []
        for brand_number in range(1, 7):
            brand, _ = Brand.objects.get_or_create(name=f'SYNTHETIC BRAND {brand_number:02d}')
            brands.append(brand)
            for model_number in range(1, 5):
                model, _ = Model.objects.get_or_create(
                    brand=brand, name=f'TEST MODEL {model_number:02d}')
                for variant in ('Urban', 'Touring'):
                    submodel, _ = SubModel.objects.get_or_create(
                        model=model, name=f'{variant} Synthetic')
                    submodels.append(submodel)

        existing_layouts = set(YearRange.objects.filter(
            layout_code__startswith='NAVSYN-').values_list('layout_code', flat=True))
        new_vehicles = []
        for number in range(1, PATTERNS + 1):
            layout = f'NAVSYN-{number:05d}'
            if layout in existing_layouts:
                continue
            country = (masters[('Country', 'India')], masters[('Country', 'KSA')],
                       masters[('Country', 'UAE')])[number % 3]
            prefix = {'India': 'I', 'KSA': 'S', 'UAE': 'U'}[country.name]
            new_vehicles.append(YearRange(
                sub_model=submodels[(number - 1) % len(submodels)],
                serial_number=f'{prefix}{number:04d}',
                year_start=2017 + number % 8, year_end=2025 + number % 2,
                number_of_seats=5 if number % 4 else 7,
                number_of_doors=4 if number % 5 else 2,
                layout_code=layout, br=f'BR-{number % 10:02d}',
                x_code=f'X-SYN-{number:04d}',
                fitting_confirmation='Confirmed' if number % 3 else 'Pending',
                drive='LHD' if number % 2 else 'RHD', vehicle_country=country,
                measurement_country=masters[('Country', 'India')],
            ))
        YearRange.objects.bulk_create(new_vehicles, batch_size=100)
        vehicles = list(YearRange.objects.filter(
            layout_code__startswith='NAVSYN-').order_by('layout_code'))

        existing_skus = set(SKU.objects.filter(code__startswith='NAVSYN-SKU-')
                            .values_list('code', flat=True))
        SKU.objects.bulk_create([
            SKU(code=f'NAVSYN-SKU-{number:04d}',
                description=f'Synthetic upholstery catalogue item {number:04d}',
                region=masters[('Region', 'Synthetic North' if number % 2 else 'Synthetic South')])
            for number in range(1, SKUS + 1)
            if f'NAVSYN-SKU-{number:04d}' not in existing_skus
        ], batch_size=100)
        skus = list(SKU.objects.filter(code__startswith='NAVSYN-SKU-').order_by('code'))

        folders = {}
        for number in range(1, DESIGNS + 1):
            vehicle = vehicles[(number * 7 - 1) % len(vehicles)]
            if vehicle.pk not in folders:
                folders[vehicle.pk], _ = PatternDesignFolder.objects.get_or_create(
                    vehicle=vehicle, name=f'Synthetic Design Options {vehicle.layout_code}',
                    defaults={'description': 'Generated placeholder designs',
                              'created_by': users['designer']})
            image_path = f'pattern_designs/synthetic/design-{number:04d}.jpg'
            thumb_path = f'pattern_design_thumbnails/synthetic/design-{number:04d}.jpg'
            image_bytes = placeholder(image_path, number, (640, 360))
            placeholder(thumb_path, number, (240, 135))
            state = number % 5
            approval_status = 'approved' if state == 2 else 'rejected' if state == 3 else 'pending'
            image, _ = PatternDesignImage.objects.get_or_create(
                client_upload_key=f'navsyn-design-{number:04d}',
                defaults={'folder': folders[vehicle.pk], 'vehicle': vehicle,
                          'image': image_path, 'thumbnail': thumb_path,
                          'title': f'Synthetic Seat Design {number:04d}',
                          'file_size': image_bytes, 'uploaded_by': users['designer'],
                          'approval_status': approval_status,
                          'approved_by': users['ed'] if state == 2 else None,
                          'approved_at': timezone.now() if state == 2 else None,
                          'rejected_by': users['ed'] if state == 3 else None,
                          'rejected_at': timezone.now() if state == 3 else None,
                          'rejection_reason': 'Synthetic fit revision requested.' if state == 3 else ''})
            if state == 4:
                PatternDesignApproval.objects.get_or_create(
                    design_image=image, cycle=1,
                    defaults={'designer': users['designer'], 'status': 'rejected',
                              'cad_reviewer': users['cad'], 'cad_status': 'approved',
                              'ed_reviewer': users['ed'], 'ed_status': 'rejected',
                              'ed_comment': 'Synthetic first-cycle revision request.'})
                cycle = 2
                state = 0
            else:
                cycle = 1
            approval_values = {
                0: ('pending', 'pending', 'pending'),
                1: ('partially_approved', 'approved', 'pending'),
                2: ('approved', 'approved', 'approved'),
                3: ('rejected', 'approved', 'rejected'),
            }[state]
            PatternDesignApproval.objects.get_or_create(
                design_image=image, cycle=cycle,
                defaults={'designer': users['designer'], 'status': approval_values[0],
                          'cad_reviewer': users['cad'] if state else None,
                          'cad_status': approval_values[1],
                          'ed_reviewer': users['ed'] if state in (2, 3) else None,
                          'ed_status': approval_values[2],
                          'ed_comment': 'Synthetic design revision required.' if state == 3 else ''})

        complaint_types = (ComplaintTypes.PATTERN, ComplaintTypes.PRODUCTION,
                           ComplaintTypes.QUALITY, ComplaintTypes.LINE)
        type_master = {
            ComplaintTypes.PATTERN: masters[('Pattern Complaint Type', 'Pattern Fit')],
            ComplaintTypes.PRODUCTION: masters[('Production Complaint Type', 'Synthetic Stitching')],
            ComplaintTypes.QUALITY: masters[('Quality Complaint Type', 'Surface Finish')],
            ComplaintTypes.LINE: masters[('Factory Complaint Type', 'Assembly Fitment')],
        }
        statuses = tuple(value for value, _ in WorkflowStatuses.CHOICES)
        existing_ids = set(Complaint.objects.filter(complaint_id__contains='-2610')
                           .values_list('complaint_id', flat=True))
        new_complaints = []
        for number in range(1, COMPLAINTS + 1):
            complaint_type = complaint_types[(number - 1) % 4]
            complaint_id = f'{ComplaintTypes.PREFIXES[complaint_type]}-2610{(number - 1)//4 + 1:04d}'
            if complaint_id in existing_ids:
                continue
            state = statuses[(number - 1) % len(statuses)]
            vehicle = vehicles[(number * 11 - 1) % len(vehicles)]
            reporter_role = 'registrar' if complaint_type == ComplaintTypes.LINE else (
                'country_ksa' if number % 3 == 0 else 'country_uae' if number % 3 == 1 else 'factory')
            country_name = 'KSA' if reporter_role == 'country_ksa' else (
                'UAE' if reporter_role == 'country_uae' else 'India')
            priority = ('Low', 'Medium', 'High')[number % 3]
            assigned = None if state == WorkflowStatuses.SUBMITTED else users['factory']
            action_ready = state not in (WorkflowStatuses.SUBMITTED,
                                         WorkflowStatuses.ASSIGNED_TO_FACTORY,
                                         WorkflowStatuses.FACTORY_REVIEW)
            new_complaints.append(Complaint(
                complaint_id=complaint_id, complaint_type=complaint_type,
                workflow_status=state, created_by=users[reporter_role],
                assigned_factory_executive=assigned,
                date=FIXTURE_DATE - timedelta(days=number % 14),
                channel=masters[('Channel', 'Synthetic Portal')],
                country=masters[('Country', country_name)],
                case_sub_category=type_master[complaint_type],
                series=masters[('Series', 'Test Premium' if number % 2 else 'Test Standard')],
                material=masters[('Material', 'Synthetic Leather A' if number % 2 else 'Synthetic Leather B')],
                sku=skus[(number - 1) % len(skus)],
                brand=vehicle.sub_model.model.brand, model=vehicle.sub_model.model,
                sub_model=vehicle.sub_model, year=vehicle,
                status='Closed' if state == WorkflowStatuses.CLOSED else
                       'On Hold' if state == WorkflowStatuses.ON_HOLD else 'Open',
                priority=priority,
                complaint_description=f'Synthetic {complaint_type} fit and finish observation {number:04d}.',
                serial_no=f'SYN-VIN-{number:06d}', batch_no=f'SYN-BATCH-{number % 40:03d}',
                factory_reason='Synthetic root cause for load testing.' if action_ready else '',
                factory_action_plan='Inspect template, correct fitting, verify sample.' if action_ready else '',
                factory_priority={'Low': FactoryPriorities.LOW,
                                  'Medium': FactoryPriorities.MEDIUM,
                                  'High': FactoryPriorities.TOP}[priority] if action_ready else '',
                cad_date=FIXTURE_DATE if state == WorkflowStatuses.CLOSED else None,
                updated_order_no=f'SYN-CONTAINER-{number:05d}' if state == WorkflowStatuses.CLOSED else '',
                closed_at=timezone.now() if state == WorkflowStatuses.CLOSED else None,
                closed_by=users['factory'] if state == WorkflowStatuses.CLOSED else None,
            ))
        Complaint.objects.bulk_create(new_complaints, batch_size=100)
        complaints = list(Complaint.objects.filter(
            complaint_id__in=[f'{ComplaintTypes.PREFIXES[complaint_types[(n-1)%4]]}-2610{(n-1)//4+1:04d}'
                             for n in range(1, COMPLAINTS + 1)]).order_by('complaint_id'))

        role_order = (ApprovalRoles.PM, ApprovalRoles.OM, ApprovalRoles.CAD,
                      ApprovalRoles.ED, ApprovalRoles.MD)
        approval_rows = []
        timeline_rows = []
        for complaint in complaints:
            status = complaint.workflow_status
            if status in (WorkflowStatuses.SUBMITTED, WorkflowStatuses.ASSIGNED_TO_FACTORY,
                          WorkflowStatuses.FACTORY_REVIEW, WorkflowStatuses.ON_HOLD):
                continue
            required = role_order[:3 if complaint.factory_priority == FactoryPriorities.LOW
                                  else 4 if complaint.factory_priority == FactoryPriorities.MEDIUM else 5]
            existing = set(ComplaintApproval.objects.filter(complaint=complaint)
                           .values_list('approval_round', 'approver_role'))
            for index, role in enumerate(required):
                if (1, role) not in existing:
                    decision = (DecisionStatuses.REJECTED if status == WorkflowStatuses.REWORK_REQUIRED
                                and index == 0 else DecisionStatuses.PENDING if status == WorkflowStatuses.AWAITING_APPROVAL
                                or (status == WorkflowStatuses.PARTIALLY_APPROVED and index > 0)
                                else DecisionStatuses.APPROVED)
                    approval_rows.append(ComplaintApproval(
                        complaint=complaint, approval_round=1,
                        review_stage=ApprovalStages.INITIAL, approver_role=role,
                        approver_user=users[role.lower()], status=decision,
                        decided_at=timezone.now() if decision != DecisionStatuses.PENDING else None,
                        comment='Synthetic reviewer decision.' if decision != DecisionStatuses.PENDING else ''))
            if status in (WorkflowStatuses.AWAITING_EXECUTION_VERIFICATION,
                          WorkflowStatuses.EXECUTION_PARTIALLY_VERIFIED,
                          WorkflowStatuses.PENDING_FINAL_UPDATE, WorkflowStatuses.CLOSED):
                for index, role in enumerate(required):
                    if (2, role) in existing:
                        continue
                    decision = (DecisionStatuses.PENDING if status == WorkflowStatuses.AWAITING_EXECUTION_VERIFICATION
                                or (status == WorkflowStatuses.EXECUTION_PARTIALLY_VERIFIED and index > 0)
                                else DecisionStatuses.APPROVED)
                    approval_rows.append(ComplaintApproval(
                        complaint=complaint, approval_round=2,
                        review_stage=ApprovalStages.EXECUTION_VERIFICATION,
                        approver_role=role, approver_user=users[role.lower()],
                        status=decision,
                        decided_at=timezone.now() if decision != DecisionStatuses.PENDING else None,
                        comment='Synthetic execution verification.' if decision != DecisionStatuses.PENDING else ''))
            if not complaint.timeline_events.exists():
                timeline_rows.append(ComplaintTimeline(
                    complaint=complaint, action_type='synthetic_fixture',
                    title='Synthetic workflow record',
                    description='Generated for isolated performance testing.',
                    user=complaint.created_by))
        ComplaintApproval.objects.bulk_create(approval_rows, batch_size=200)
        reconsideration_rows = []
        for complaint in complaints:
            if complaint.workflow_status != WorkflowStatuses.REWORK_REQUIRED:
                continue
            trigger = ComplaintApproval.objects.filter(
                complaint=complaint, approval_round=1,
                status=DecisionStatuses.REJECTED).first()
            if not trigger:
                continue
            required = role_order[:3 if complaint.factory_priority == FactoryPriorities.LOW
                                  else 4 if complaint.factory_priority == FactoryPriorities.MEDIUM else 5]
            existing = set(ComplaintApproval.objects.filter(
                complaint=complaint, approval_round=2).values_list('approver_role', flat=True))
            for role in required[1:]:
                if role in existing:
                    continue
                decision = (DecisionStatuses.REJECTED if role == ApprovalRoles.OM
                            else DecisionStatuses.APPROVED)
                reconsideration_rows.append(ComplaintApproval(
                    complaint=complaint, approval_round=2,
                    review_stage=ApprovalStages.RECONSIDERATION,
                    trigger_approval=trigger, approver_role=role,
                    approver_user=users[role.lower()], status=decision,
                    decided_at=timezone.now(),
                    comment='Synthetic rework requested.' if decision == DecisionStatuses.REJECTED
                            else 'Synthetic vote to proceed.'))
        ComplaintApproval.objects.bulk_create(reconsideration_rows, batch_size=100)
        ComplaintTimeline.objects.bulk_create(timeline_rows, batch_size=100)

        for number in range(1, COMPLAINT_ATTACHMENTS + 1):
            complaint = complaints[(number * 3 - 1) % len(complaints)]
            media_path = f'complaint_media/synthetic/attachment-{number:04d}.jpg'
            placeholder(media_path, number + 1000, (640, 400))
            ComplaintMedia.objects.get_or_create(complaint=complaint, file=media_path)

        if not PatternAlteration.objects.filter(summary='Synthetic pattern change request').exists():
            PatternAlteration.objects.create(
                requested_by=users['factory'], action_type='update',
                pattern_ids=[vehicles[0].pk], summary='Synthetic pattern change request',
                payload={'note': 'Synthetic test fixture'}, status='pending')
        if not ChatMessage.objects.filter(message='Synthetic navigation load message').exists():
            ChatMessage.objects.create(sender=users['factory'], recipient=users['admin'],
                                       message='Synthetic navigation load message')

    cache.clear()
    connection.check_constraints()
    with connection.cursor() as cursor:
        cursor.execute('PRAGMA quick_check')
        if cursor.fetchone()[0] != 'ok':
            raise RuntimeError('SQLite quick_check failed after seeding.')
    counts = {
        'users': get_user_model().objects.filter(username__startswith=PREFIX).count(),
        'brands': Brand.objects.filter(name__startswith='SYNTHETIC BRAND').count(),
        'models': Model.objects.filter(brand__name__startswith='SYNTHETIC BRAND').count(),
        'variants': SubModel.objects.filter(model__brand__name__startswith='SYNTHETIC BRAND').count(),
        'patterns': YearRange.objects.filter(layout_code__startswith='NAVSYN-').count(),
        'skus': SKU.objects.filter(code__startswith='NAVSYN-SKU-').count(),
        'complaints': len(complaints),
        'design_folders': PatternDesignFolder.objects.filter(name__startswith='Synthetic Design Options').count(),
        'design_images': PatternDesignImage.objects.filter(client_upload_key__startswith='navsyn-design-').count(),
        'design_approvals': PatternDesignApproval.objects.filter(
            design_image__client_upload_key__startswith='navsyn-design-').count(),
        'complaint_approvals': ComplaintApproval.objects.filter(complaint__in=complaints).count(),
        'attachments': ComplaintMedia.objects.filter(file__startswith='complaint_media/synthetic/').count(),
    }
    return {'database': str(Path(connection.settings_dict['NAME']).resolve()),
            'database_bytes': Path(connection.settings_dict['NAME']).stat().st_size,
            'media_root': str(Path(settings.MEDIA_ROOT).resolve()),
            'credentials_file': str(credential_path), 'counts': counts}
