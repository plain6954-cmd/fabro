import { expect, test } from '@playwright/test';
import { login } from '../helpers/auth';
import { routes } from '../helpers/testData';

test('rapid admin tab changes keep only the latest section active', async ({ page }) => {
  await login(page);
  await page.goto(routes.adminPanel);

  await page.route('**/admin_panel/?section=users', async (route) => {
    await new Promise((resolve) => setTimeout(resolve, 700));
    await route.continue();
  });

  await page.locator('#side-users').click();
  await page.locator('#side-skus').click();
  await expect(page.locator('#tab-skus')).toHaveClass(/\bactive\b/);
  await expect(page.locator('#tab-skus')).not.toHaveAttribute('aria-busy', 'true');
  await page.waitForTimeout(900);
  await expect(page.locator('.erp-tab-pane.active')).toHaveCount(1);
  await expect(page.locator('#tab-users')).not.toHaveClass(/\bactive\b/);
  await expect(page.locator('#tab-skus')).toHaveClass(/\bactive\b/);
});

test('admin sections remain within the viewport on small screens', async ({ page }) => {
  await login(page);
  for (const width of [320, 390, 768]) {
    await page.setViewportSize({ width, height: 740 });
    await page.goto(routes.adminPanel);
    await page.locator('#side-skus').click();
    await expect(page.locator('#tab-skus')).not.toHaveAttribute('aria-busy', 'true');
    const overflow = await page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth);
    expect(overflow, `admin page overflows at ${width}px`).toBeLessThanOrEqual(1);
  }
});
