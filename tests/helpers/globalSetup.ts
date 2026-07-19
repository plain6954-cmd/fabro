import { runDjango, runDjangoCode } from './django';

export default async function globalSetup() {
  runDjango(['migrate', '--noinput']);
  runDjango(['flush', '--noinput']);
  runDjangoCode(`
from django.contrib.auth import get_user_model
from management.models import (
    ApprovalRoles, Brand, Complaint, ComplaintTypes, Model, SubModel, YearRange,
    MasterSetting, SKU, UserProfile, WorkflowRoles, WorkflowStatuses,
)
import os
User = get_user_model()
username = os.environ["E2E_USERNAME"]
password = os.environ["E2E_PASSWORD"]
email = os.environ["E2E_EMAIL"]
user, _ = User.objects.get_or_create(username=username, defaults={"email": email, "is_staff": True, "is_superuser": True})
user.email = email
user.is_staff = True
user.is_superuser = True
user.set_password(password)
user.save()
for category, name in [
    ("Channel", "WhatsApp"),
    ("Country", "KSA"),
    ("Reported By", "Playwright Reporter"),
    ("Type", "Stitching"),
    ("Type", "Pattern Complaint"),
    ("Type", "Production Complaint"),
    ("Type", "Line Complaint"),
    ("Series", "Luxe"),
    ("Material", "Rexin"),
    ("Region", "E2E Region"),
]:
    setting = MasterSetting.objects.filter(name=name).first()
    if setting:
        if setting.category != category:
            setting.category = category
            setting.save(update_fields=["category"])
    else:
        MasterSetting.objects.create(category=category, name=name)
brand, _ = Brand.objects.get_or_create(name="PLAYWRIGHT BRAND")
model, _ = Model.objects.get_or_create(brand=brand, name="PLAYWRIGHT MODEL")
sub_model, _ = SubModel.objects.get_or_create(model=model, name="PLAYWRIGHT SUB")
YearRange.objects.get_or_create(sub_model=sub_model, year_start=2024, year_end=2026, defaults={"layout_code": "PW-LAYOUT", "number_of_seats": 5, "number_of_doors": 4})
region = MasterSetting.objects.filter(category="Region").first()
SKU.objects.get_or_create(code="PW-SKU-SEED", defaults={"description": "Seed SKU for browser tests", "region": region})

workflow_password = "FabroWorkflow!234"
workflow_accounts = {
    "fabro_e2e_factory": (WorkflowRoles.FACTORY_EXECUTIVE, ""),
    "fabro_e2e_pm": (WorkflowRoles.APPROVER, ApprovalRoles.PM),
    "fabro_e2e_om": (WorkflowRoles.APPROVER, ApprovalRoles.OM),
    "fabro_e2e_cad": (WorkflowRoles.APPROVER, ApprovalRoles.CAD),
    "fabro_e2e_ed": (WorkflowRoles.APPROVER, ApprovalRoles.ED),
}
workflow_users = {}
for workflow_username, (workflow_role, approval_role) in workflow_accounts.items():
    workflow_user, _ = User.objects.get_or_create(
        username=workflow_username,
        defaults={"email": f"{workflow_username}@example.com"},
    )
    workflow_user.set_password(workflow_password)
    workflow_user.save()
    profile, _ = UserProfile.objects.get_or_create(user=workflow_user)
    profile.role = workflow_role
    profile.approval_role = approval_role
    profile.can_receive_factory_assignments = workflow_role == WorkflowRoles.FACTORY_EXECUTIVE
    profile.save()
    workflow_users[workflow_username] = workflow_user

production_type = MasterSetting.objects.get(category="Type", name="Production Complaint")
country = MasterSetting.objects.get(category="Country", name="KSA")
Complaint.objects.get_or_create(
    batch_order="E2E-WORKFLOW-APPROVAL",
    defaults={
        "date": "2026-07-14",
        "country": country,
        "case_sub_category": production_type,
        "complaint_type": ComplaintTypes.PRODUCTION,
        "workflow_status": WorkflowStatuses.ASSIGNED_TO_FACTORY,
        "created_by": user,
        "assigned_factory_executive": workflow_users["fabro_e2e_factory"],
        "status": "Open",
        "priority": "Medium",
        "complaint_description": "E2E complete approval and closure workflow",
    },
)
`);
}
