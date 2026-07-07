import { expect, test } from '@playwright/test';
import { login } from '../helpers/auth';
import { attachPageDiagnostics, expectNoDjangoError, expectTheme } from '../helpers/assertions';
import { routes } from '../helpers/testData';

test.beforeEach(async ({ page }) => {
  await login(page);
});

test('theme toggles between dark and light and persists after refresh', async ({ page }) => {
  const diagnostics = attachPageDiagnostics(page);
  await page.goto(routes.dashboard);
  await page.locator('.profile-trigger').hover();
  await page.locator('.toggle-switch').click();
  await expectTheme(page, 'light');
  await page.reload();
  await expectTheme(page, 'light');

  for (const route of [routes.dashboard, routes.addComplaint, routes.vehicles, routes.sku, routes.master, routes.profile]) {
    await page.goto(route);
    await expectTheme(page, 'light');
    await expectNoDjangoError(page);
  }

  await page.locator('.profile-trigger').hover();
  await page.locator('.toggle-switch').click();
  await expectTheme(page, 'dark');
  await diagnostics.assertClean();
});
