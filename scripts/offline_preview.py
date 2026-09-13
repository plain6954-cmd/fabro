"""Local browser fixture server, backed exclusively by disposable RAM tables."""
import verify_offline  # Activates standalone settings and blocks external sockets.
from django.contrib.auth import get_user_model
from django.contrib.staticfiles.handlers import StaticFilesHandler
from django.core.wsgi import get_wsgi_application
from django.test.runner import DiscoverRunner
from django.utils import timezone
from wsgiref.simple_server import make_server
from management.models import (
    Brand, Model, SubModel, YearRange, SKU, MasterSetting, Complaint, UserProfile,
    WorkflowRoles, ApprovalRoles,
)
from management.services.workflow import submit_factory_review

runner = DiscoverRunner(verbosity=0, interactive=False)
database_config = runner.setup_databases()
User = get_user_model()
admin = User.objects.create_superuser('offline-admin', 'offline@example.invalid', 'Offline-Test-123!')
peer = User.objects.create_user('offline-peer', password='Offline-Test-123!')
country = MasterSetting.objects.get(category='Country', name='India')
for category, name in (
    ('Channel', 'Offline Channel'), ('Pattern Complaint Type', 'Offline Pattern'),
    ('Production Complaint Type', 'Offline Production'), ('Quality Complaint Type', 'Offline Quality'),
    ('Factory Complaint Type', 'Offline Factory'), ('Series', 'Offline Series'),
    ('Material', 'Offline Material'), ('Region', 'Offline Region'),
):
    MasterSetting.objects.get_or_create(category=category, name=name)
brand = Brand.objects.create(name='OFFLINE BRAND')
model = Model.objects.create(brand=brand, name='OFFLINE MODEL')
submodel = SubModel.objects.create(model=model, name='Standard')
for number in range(55):
    YearRange.objects.create(
        sub_model=submodel, year_start=2000 + number, year_end=2001 + number,
        layout_code=f'OFFLINE-{number}', serial_number=f'I{number:04d}',
        vehicle_country=country, measurement_country=country,
        number_of_seats=5, number_of_doors=4,
    )
    SKU.objects.create(code=f'OFFLINE-SKU-{number}', description='Synthetic browser fixture')
for role in (ApprovalRoles.PM, ApprovalRoles.OM, ApprovalRoles.CAD):
    approver = User.objects.create_user(f'offline-{role.lower()}')
    profile = approver.workflow_profile
    profile.role, profile.approval_role = WorkflowRoles.APPROVER, role
    profile.save()
for number in range(3):
    complaint = Complaint.objects.create(
        date=timezone.localdate(), complaint_type='pattern', created_by=admin,
        brand=brand, model=model, sub_model=submodel, year=YearRange.objects.first(),
        country=country, serial_no=f'OFFLINE-{number}',
        complaint_description='Synthetic complaint for responsive and interaction verification.',
        assigned_factory_executive=admin,
    )
    submit_factory_review(complaint, admin, 'Synthetic reason', 'Synthetic action plan', 'low')

try:
    with make_server('127.0.0.1', 8766, StaticFilesHandler(get_wsgi_application())) as server:
        print('OFFLINE_PREVIEW_READY http://127.0.0.1:8766', flush=True)
        server.serve_forever()
finally:
    runner.teardown_databases(database_config)
