import { expect, test } from '@playwright/test';
import { login } from '../helpers/auth';
import { attachPageDiagnostics, expectNoDjangoError } from '../helpers/assertions';
import { openViaNav } from '../helpers/navigation';

test.beforeEach(async ({ page }) => {
  await login(page);
});

test('dashboard loads cards and navigation works', async ({ page }) => {
  const diagnostics = attachPageDiagnostics(page);
  await expect(page.getByText('System Dashboard')).toBeVisible();
  await expect(page.getByText('Existing Complaints')).toBeVisible();
  await expect(page.getByText('System Statistics')).toBeVisible();
  await expect(page.getByText('Total Complaints')).toBeVisible();
  await openViaNav(page, 'Complaints', /\/complaints\/$/, /Complaint Management/i);
  await openViaNav(page, 'Vehicles', /\/add-car-details\/$/, /Vehicle Management/i);
  await openViaNav(page, 'SKU', /\/add-sku\/$/, /SKU Management/i);
  await openViaNav(page, 'Master', /\/master-settings\/$/, /Master Settings/i);
  await expectNoDjangoError(page);
  await diagnostics.assertClean();
});
