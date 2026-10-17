import { expect, test } from '@playwright/test';
import { login } from '../helpers/auth';
import { attachPageDiagnostics } from '../helpers/assertions';
import { routes } from '../helpers/testData';

test('Color Master view switch and live color editor work at mobile and desktop widths', async ({ page }) => {
  await login(page);
  const diagnostics = attachPageDiagnostics(page);
  await page.goto(`${routes.vehicles}?subwindow=colors`);
  await expect(page.locator('#tab-pane-color-master .page-title')).toBeVisible();

  for (const width of [360, 768, 1440]) {
    await page.setViewportSize({ width, height: 900 });
    await expect.poll(() => page.evaluate(() =>
      document.documentElement.scrollWidth - window.innerWidth
    )).toBeLessThanOrEqual(1);
    await page.locator('.toggle[for="colorViewToggle"]').click();
    await expect(page.locator('#colorListTableWrapper')).toBeVisible();
    await page.locator('.toggle[for="colorViewToggle"]').click();
    await expect(page.locator('#colorTilesGrid')).toBeVisible();
  }

  await page.locator('#btnOpenCreateColorModal').click();
  await expect(page.locator('#createColorModal')).toBeVisible();
  await page.locator('#newColorName').fill('Browser Color Preview');
  await page.locator('#newColorHex').fill('#AB12CD');
  await page.locator('#newColorHex').blur();
  await expect(page.locator('#createColorLiveName')).toHaveText('Browser Color Preview');
  await expect.poll(() => page.locator('#createColorLiveSwatch').evaluate((element) =>
    getComputedStyle(element).backgroundColor
  )).toBe('rgb(171, 18, 205)');
  await page.locator('#createColorModal .close-btn').click();
  await expect(page.locator('#createColorModal')).toBeHidden();
  await diagnostics.assertClean();
});
