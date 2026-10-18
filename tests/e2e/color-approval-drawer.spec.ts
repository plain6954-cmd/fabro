import { expect, test } from '@playwright/test';
import { mkdirSync } from 'fs';
import { join } from 'path';
import { login } from '../helpers/auth';
import { runDjangoCode } from '../helpers/django';
import { routes } from '../helpers/testData';

test.beforeAll(() => {
  // Approval metadata only in the disposable E2E database; no media is uploaded.
  runDjangoCode(`
from django.contrib.auth import get_user_model
from management.models import PatternColorSelection, PatternColorApprovalDecision, YearRange
User = get_user_model()
vehicle = YearRange.objects.first()
selection, _ = PatternColorSelection.objects.get_or_create(
    vehicle=vehicle, inner_pantone_code='E2E 19-1664 TCX',
    defaults={
        'tone_type': PatternColorSelection.TONE_SINGLE,
        'inner_source': PatternColorSelection.SOURCE_NEW,
        'inner_hex_code': '#A11B32',
        'inner_color_name': 'E2E Approval Color',
        'status': PatternColorSelection.STATUS_PENDING,
        'is_new_color': True,
        'submitted_by': User.objects.get(username='fabro_e2e_admin'),
    },
)
for department in ('MD', 'ED', 'CAD'):
    PatternColorApprovalDecision.objects.get_or_create(selection=selection, department=department)
`);
});

test('new-color approval drawer opens, shows reviewer matrix, and closes at desktop and mobile', async ({ page }) => {
  await login(page);
  const evidenceDir = join('output', 'codex-full-debug', 'screenshots');
  mkdirSync(evidenceDir, { recursive: true });
  for (const size of [{ width: 1366, height: 768 }, { width: 390, height: 844 }]) {
    await page.setViewportSize(size);
    await page.goto(`${routes.vehicles}?vehicle_id=1#design-options`);
    await expect(page.locator('#patternColorStatusCard')).toBeVisible();
    await page.locator('#btnViewColorApprovalDetails').click();
    await expect(page.locator('#fabroColorApprovalDrawer')).toHaveClass(/is-open/);
    await expect(page.locator('#drawerContent')).toBeVisible();
    await expect(page.locator('#fabroColorApprovalDrawer')).toContainText('MD');
    await expect(page.locator('#fabroColorApprovalDrawer')).toContainText('ED');
    await expect(page.locator('#fabroColorApprovalDrawer')).toContainText('CAD');
    await page.screenshot({ path: join(evidenceDir, size.width === 390 ? 'mobile-color-approval-drawer.png' : 'color-approval-drawer.png') });
    await page.keyboard.press('Escape');
    await expect(page.locator('#fabroColorApprovalDrawer')).not.toHaveClass(/is-open/);
  }
});
