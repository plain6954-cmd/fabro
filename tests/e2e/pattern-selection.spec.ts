import { expect, test } from '@playwright/test';
import { login } from '../helpers/auth';
import { routes } from '../helpers/testData';

test('pattern selection exposes actions after direct and partial navigation', async ({ page }) => {
  await login(page);
  for (const partial of [false, true]) {
    if (partial) {
      await page.goto(routes.dashboard);
      await page.locator(`.nav-links a.nav-link[href="${routes.vehicles}"]`).click();
    } else {
      await page.goto(routes.vehicles);
    }
    const checkbox = page.locator('tr[id^="row-view-"] .pattern-row-select').first();
    await checkbox.check();
    await expect(page.locator('#patternActionsWrapper')).toBeVisible();
    await page.locator('#patternActionsToggleBtn').click();
    await expect(page.locator('#patternActionsDrawer')).toHaveClass(/is-open/);
  }
});

test('pattern audit log opens and resolves after partial navigation', async ({ page }) => {
  await login(page);
  await page.goto(routes.dashboard);
  await page.locator(`.nav-links a.nav-link[href="${routes.vehicles}"]`).click();
  await page.locator('tr[id^="row-view-"] .pattern-row-select').first().check();
  await page.locator('#patternActionsToggleBtn').click();
  const request = page.waitForResponse((response) => /\/api\/pattern\/\d+\/logs\//.test(response.url()));
  await page.locator('#actionBtnLog').click();
  expect((await request).status()).toBe(200);
  await expect(page.locator('#patternLogPopover')).toBeVisible();
  await expect(page.locator('#patternLogBody')).not.toContainText('Loading audit logs...');
});
