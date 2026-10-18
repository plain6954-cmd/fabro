import { expect, test } from '@playwright/test';
import { mkdirSync, writeFileSync } from 'fs';
import { join } from 'path';
import { login } from '../helpers/auth';
import { routes } from '../helpers/testData';

const evidenceDir = join('output', 'codex-full-debug', 'screenshots');

test('capture authenticated module and responsive evidence without uploads', async ({ page }) => {
  test.setTimeout(180_000);
  mkdirSync(evidenceDir, { recursive: true });
  const diagnostics: { pageErrors: string[]; failedRequests: string[]; timings: Record<string, number> } = {
    pageErrors: [], failedRequests: [], timings: {},
  };
  page.on('pageerror', (error) => diagnostics.pageErrors.push(error.message));
  page.on('requestfailed', (request) => diagnostics.failedRequests.push(`${request.method()} ${request.url()}: ${request.failure()?.errorText}`));
  await login(page);

  const visit = async (name: string, route: string, visible: string) => {
    const start = performance.now();
    await page.goto(route);
    await expect(page.locator(visible)).toBeVisible();
    diagnostics.timings[name] = Math.round(performance.now() - start);
    await page.screenshot({ path: join(evidenceDir, `${name}.png`) });
  };

  await visit('dashboard', routes.dashboard, '#app-content');
  await visit('pattern-master', routes.vehicles, '#tab-pane-pattern-list');
  await visit('pattern-detail', `${routes.vehicles}?vehicle_id=1#design-options`, '#tab-pane-design-options');
  await page.screenshot({ path: join(evidenceDir, 'measurements.png') });
  await page.locator('#colorTopTabExisting').click();
  await expect(page.locator('#colorPickerExistingView')).toBeVisible();
  await page.screenshot({ path: join(evidenceDir, 'existing-colors.png') });
  await page.locator('#colorTopTabNew').click();
  await expect(page.locator('#newSingleToneContainer')).toBeVisible();
  await page.screenshot({ path: join(evidenceDir, 'pantone-single-tone.png') });
  await page.locator('.tone-radio-label', { hasText: 'Dual Tone' }).click();
  await expect(page.locator('#newDualToneContainer')).toBeVisible();
  await page.screenshot({ path: join(evidenceDir, 'pantone-dual-tone.png') });
  await page.locator('#sidebarNav3DDesignBtn').click();
  await expect(page.locator('#pattern3DDesignWorkspace')).toBeVisible();
  await page.screenshot({ path: join(evidenceDir, '3d-design-non-designer.png') });
  await visit('color-master', `${routes.vehicles}?subwindow=colors`, '#tab-pane-color-master');
  await visit('complaints', routes.complaints, '#app-content');
  await visit('sku', routes.sku, '#app-content');
  await visit('master-settings', routes.master, '#app-content');

  await page.setViewportSize({ width: 820, height: 1180 });
  await page.goto(`${routes.vehicles}?vehicle_id=1#design-options`);
  await expect(page.locator('#patternMeasurementsWorkspace')).toBeVisible();
  await page.screenshot({ path: join(evidenceDir, 'tablet-measurements.png') });
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto(routes.dashboard);
  await page.screenshot({ path: join(evidenceDir, 'mobile-navigation.png') });
  await page.goto(`${routes.vehicles}?vehicle_id=1#design-options`);
  await page.screenshot({ path: join(evidenceDir, 'mobile-measurements.png') });
  await page.locator('#sidebarNav3DDesignBtn').click();
  await page.screenshot({ path: join(evidenceDir, 'mobile-3d-design.png') });
  writeFileSync(join('output', 'codex-full-debug', 'browser-diagnostics.json'), JSON.stringify(diagnostics, null, 2));
  expect(diagnostics.pageErrors).toEqual([]);
});
