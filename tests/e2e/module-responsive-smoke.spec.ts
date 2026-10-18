import { expect, test } from '@playwright/test';
import { writeFileSync } from 'fs';
import { join } from 'path';
import { login } from '../helpers/auth';
import { routes } from '../helpers/testData';

const sizes = [
  [2560, 1440], [1920, 1080], [1648, 928], [1536, 864],
  [1366, 768], [1280, 720], [1024, 768], [820, 1180],
  [768, 1024], [430, 932], [390, 844], [375, 812],
  [360, 800], [320, 568], [568, 320],
] as const;

test('primary workspaces avoid document overflow at required viewport widths', async ({ page }) => {
  test.setTimeout(180_000);
  await login(page);
  const modules = [
    ['dashboard', routes.dashboard],
    ['complaints', routes.complaints],
    ['patterns', routes.vehicles],
    ['approvals', '/approvals/'],
    ['sku', routes.sku],
    ['master-settings', routes.master],
    ['admin-panel', routes.adminPanel],
    ['chat', '/chat/'],
  ] as const;
  const measurements: Array<{ module: string; width: number; height: number; documentWidth: number; viewportWidth: number }> = [];
  for (const [moduleName, url] of modules) {
    await page.goto(url);
    await expect(page.locator('body')).toBeVisible();
    for (const [width, height] of sizes) {
      await page.setViewportSize({ width, height });
      const metric = await page.evaluate(() => ({
        documentWidth: document.documentElement.scrollWidth,
        viewportWidth: window.innerWidth,
      }));
      measurements.push({ module: moduleName, width, height, ...metric });
    }
  }
  writeFileSync(join('output', 'codex-full-debug', 'module-responsive-layout.json'), JSON.stringify(measurements, null, 2));
  expect(measurements.filter((item) => item.documentWidth > item.viewportWidth + 1)).toEqual([]);
});
