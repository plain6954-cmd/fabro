import { expect, test } from '@playwright/test';
import { login } from '../helpers/auth';
import { expectNoDjangoError } from '../helpers/assertions';
import { routes } from '../helpers/testData';

test.beforeEach(async ({ page }) => {
  await login(page);
});

test('main pages are not blank across configured device projects', async ({ page }) => {
  const viewports = [
    { name: 'desktop', width: 1366, height: 768 },
    { name: 'tablet', width: 834, height: 1112 },
    { name: 'mobile', width: 390, height: 844 }
  ];

  for (const viewport of viewports) {
    await page.setViewportSize({ width: viewport.width, height: viewport.height });
    for (const route of [routes.dashboard, routes.addComplaint, routes.vehicles, routes.sku, routes.master, routes.profile]) {
      await page.goto(route);
      await expect(page.locator('body'), `${viewport.name} ${route}`).not.toBeEmpty();
      await expect(page.locator('.navbar'), `${viewport.name} ${route}`).toBeVisible();
      await expectNoDjangoError(page);
    }
  }
});
