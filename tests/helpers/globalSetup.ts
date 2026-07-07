import { execFileSync } from 'child_process';
import { testUser } from './testData';

const pythonCommand = process.env.PYTHON || (process.platform === 'win32'
  ? '.\\.venv\\Scripts\\python.exe'
  : './.venv/bin/python');

function runPython(code: string) {
  execFileSync(pythonCommand, ['manage.py', 'shell', '-c', code], {
    stdio: 'inherit',
    env: {
      ...process.env,
      E2E_USERNAME: testUser.username,
      E2E_PASSWORD: testUser.password,
      E2E_EMAIL: testUser.email
    }
  });
}

export default async function globalSetup() {
  runPython(`
from django.contrib.auth import get_user_model
from management.models import Brand, Model, SubModel, YearRange, MasterSetting, SKU
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
`);
}
