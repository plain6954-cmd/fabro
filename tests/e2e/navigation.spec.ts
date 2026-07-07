import { expect, test } from '@playwright/test';
import { login } from '../helpers/auth';
import { attachPageDiagnostics, expectNoDjangoError } from '../helpers/assertions';
import { routes } from '../helpers/testData';

test.beforeEach(async ({ page }) => {
  await login(page);
});

test('header navigation, profile menu and responsive layouts load', async ({ page }) => {
  const diagnostics = attachPageDiagnostics(page);
  const navTargets = [
    [routes.dashboard, /System Dashboard/i],
    [routes.addComplaint, /Add New Complaint/i],
    [routes.complaints, /Complaint Management/i],
    [routes.vehicles, /Vehicle Management/i],
    [routes.sku, /SKU Management/i],
    [routes.master, /Master Settings/i],
    [routes.profile, /Profile Settings/i]
  ] as const;

  for (const [route, heading] of navTargets) {
    await page.goto(route);
    await expect(page.getByRole('heading', { name: heading })).toBeVisible();
    await expectNoDjangoError(page);
  }

  await page.locator('.profile-trigger').hover();
  await expect(page.locator('.profile-dropdown-content').getByText('Profile Settings')).toBeVisible();
  await expect(page.locator('.profile-dropdown-content').getByText('Notifications')).toBeVisible();
  await diagnostics.assertClean();
});
