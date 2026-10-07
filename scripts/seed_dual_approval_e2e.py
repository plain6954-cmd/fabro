"""Seed test data for end-to-end dual approval browser verification."""
import os
import sys
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR))

import django
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'scripts.test_browser_settings')
django.setup()

from django.core.management import call_command
from django.contrib.auth.models import User
from management.models import (
    ApprovalRoles,
    Brand,
    MasterSetting,
    Model,
    PatternDesignFolder,
    SubModel,
    UserProfile,
    WorkflowRoles,
    YearRange,
)

def seed():
    print("Setting up test database tables...")
    call_command('migrate', '--run-syncdb', interactive=False)

    print("Creating test users...")
    users = [
        ('designer_amy', 'designer_amy@fabro.test', WorkflowRoles.FREELANCE_3D_DESIGNER, None),
        ('designer_bob', 'designer_bob@fabro.test', WorkflowRoles.FREELANCE_3D_DESIGNER, None),
        ('cad_john', 'cad_john@fabro.test', WorkflowRoles.APPROVER, ApprovalRoles.CAD),
        ('ed_sarah', 'ed_sarah@fabro.test', WorkflowRoles.APPROVER, ApprovalRoles.ED),
        ('pm_dave', 'pm_dave@fabro.test', WorkflowRoles.APPROVER, ApprovalRoles.PM),
        ('country_exec', 'country_exec@fabro.test', WorkflowRoles.COUNTRY_EXECUTIVE, None),
    ]

    for username, email, role, approval_role in users:
        u, _ = User.objects.get_or_create(username=username, defaults={'email': email})
        u.set_password('Password123!')
        u.is_active = True
        u.save()

        p, _ = UserProfile.objects.get_or_create(user=u)
        p.role = role
        p.approval_role = approval_role or ''
        if role == WorkflowRoles.COUNTRY_EXECUTIVE:
            country_setting, _ = MasterSetting.objects.get_or_create(category='country', name='United Arab Emirates')
            p.country = country_setting
        p.save()
        print(f"  User {username} ready with role {role} / {approval_role}")

    print("Creating catalog data...")
    brand, _ = Brand.objects.get_or_create(name='Lexus Design')
    model, _ = Model.objects.get_or_create(brand=brand, name='RX')
    sub_model, _ = SubModel.objects.get_or_create(model=model, name='350')
    vehicle, _ = YearRange.objects.get_or_create(
        sub_model=sub_model,
        year_start=2024,
        year_end=2025,
        defaults={'layout_code': 'RX-2425', 'number_of_seats': 5, 'number_of_doors': 4}
    )
    folder, _ = PatternDesignFolder.objects.get_or_create(
        vehicle=vehicle,
        name='Front Seats Upholstery',
        defaults={'created_by': User.objects.get(username='designer_amy')}
    )
    print(f"Vehicle ID: {vehicle.id}, Folder ID: {folder.id}")
    print("Database seeding completed successfully.")

if __name__ == '__main__':
    seed()
