import { expect, test } from '@playwright/test';
import { login } from '../helpers/auth';
import { attachPageDiagnostics, expectNoDjangoError, expectTheme } from '../helpers/assertions';
import { routes } from '../helpers/testData';

test.beforeEach(async ({ page }) => {
  await login(page);
});

test('dark application theme remains consistent across routes and refresh', async ({ page }) => {
  const diagnostics = attachPageDiagnostics(page);
  await page.goto(routes.dashboard);
  await expectTheme(page, 'dark');
  await page.reload();
  await expectTheme(page, 'dark');

  for (const route of [routes.dashboard, routes.addComplaint, routes.vehicles, routes.sku, routes.master, routes.profile]) {
    await page.goto(route);
    await expectTheme(page, 'dark');
    await expectNoDjangoError(page);
  }
  await diagnostics.assertClean();
});
