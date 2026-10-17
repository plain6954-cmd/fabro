import { expect, test } from '@playwright/test';
import { login } from '../helpers/auth';
import { attachPageDiagnostics } from '../helpers/assertions';
import { routes } from '../helpers/testData';

test('major windows fit phone, tablet, and desktop viewports', async ({ page }) => {
  await login(page);
  const diagnostics = attachPageDiagnostics(page);
  const pages = [routes.dashboard, routes.vehicles, routes.complaints, routes.master, '/chat/'];

  for (const width of [360, 390, 768, 1024, 1440, 1920]) {
    await page.setViewportSize({ width, height: 900 });
    for (const route of pages) {
      const response = await page.goto(route);
      expect(response?.status(), `${route} at ${width}px`).toBe(200);
      await expect(page.locator('#app-content')).toBeVisible();
      await expect.poll(() => page.evaluate(() =>
        document.documentElement.scrollWidth - window.innerWidth
      ), { message: `${route} overflows at ${width}px` }).toBeLessThanOrEqual(1);
    }
  }
  await diagnostics.assertClean();
});
