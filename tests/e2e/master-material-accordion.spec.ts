import { expect, test } from '@playwright/test';
import { login } from '../helpers/auth';
import { attachPageDiagnostics } from '../helpers/assertions';
import { routes } from '../helpers/testData';

test('material variants remain usable through HTMX navigation and responsive widths', async ({ page }) => {
  await login(page);
  const diagnostics = attachPageDiagnostics(page);
  await page.goto(routes.master);
  const materialName = `Browser Material ${Date.now()}`;
  await page.locator('.form-section select[name="category"]').selectOption('Material');
  await page.locator('.form-section input[name="name"]').fill(materialName);
  await page.locator('.form-section button[type="submit"]').click();
  const material = page.locator('.material-master-accordion', { hasText: materialName });
  await expect(material).toBeVisible();
  const variantsUrl = '**/master-settings/materials/*/variants/';
  await page.route(variantsUrl, async (route) => {
    await new Promise((resolve) => setTimeout(resolve, 1500));
    await route.continue();
  });
  const freshVariants = page.waitForResponse((response) =>
    response.url().includes('/master-settings/materials/')
    && response.url().endsWith('/variants/')
  );
  await material.locator('.action-btn.edit').click();
  await expect(page.locator('#materialEditModal')).toBeVisible();
  await page.locator('#materialNameInput').fill(`${materialName} Updated`);

  for (const name of ['Premium', 'Standard']) {
    await page.locator('#materialVariantNewInput').fill(name);
    await page.locator('#materialVariantAddBtn').click();
  }
  await freshVariants;
  await expect(page.locator('#materialVariantList .material-variant-row')).toHaveCount(2);
  await page.unroute(variantsUrl);
  const saved = page.waitForResponse((response) => response.url().includes('/edit-master-setting/')
    && response.request().method() === 'POST');
  await page.locator('#materialModalSaveBtn').click();
  const savedResponse = await saved;
  expect(savedResponse.status()).toBe(200);
  expect((await savedResponse.json()).name).toBe(`${materialName} Updated`);
  await expect(page.locator('#materialEditModal')).toBeHidden();
  await expect(material.locator('.setting-name')).toHaveText(`${materialName} Updated`);
  await material.locator('.action-btn.edit').click();
  await expect(page.locator('#materialNameInput')).toHaveValue(`${materialName} Updated`);
  await page.locator('.material-btn-cancel-icon').click();

  for (const width of [360, 390, 768, 1024, 1440, 1920]) {
    await page.setViewportSize({ width, height: 900 });
    await expect.poll(() => page.evaluate(() =>
      document.documentElement.scrollWidth - window.innerWidth
    )).toBeLessThanOrEqual(1);
    if (await material.locator('.material-accordion-trigger').getAttribute('aria-expanded') === 'false') {
      await material.locator('.material-accordion-trigger').click();
    }
    await expect(material.locator('.material-variant-subrow')).toHaveCount(2);
    await expect(material.locator('.material-variant-subname', { hasText: 'Premium' })).toBeVisible();
  }

  const requests: string[] = [];
  page.on('request', (request) => {
    if (request.url().includes('/edit-master-setting/') && request.method() === 'POST') {
      requests.push(request.postData() || '');
    }
  });
  page.once('dialog', (dialog) => dialog.accept());
  await material.locator('.material-variant-subrow', { hasText: 'Premium' })
    .locator('.variant-subdelete').click();
  await expect(material.locator('.material-variant-subrow')).toHaveCount(1);
  expect(requests).toHaveLength(1);
  expect(requests[0]).toContain('delete_variant_id');
  expect(requests[0]).not.toContain('variants_json');

  for (let cycle = 0; cycle < 3; cycle++) {
    await page.locator(`.nav-links a.nav-link[href="${routes.dashboard}"]`).click();
    await expect(page.getByText('System Dashboard')).toBeVisible();
    await page.locator(`.nav-links a.nav-link[href="${routes.master}"]`).click();
    await expect(page.getByRole('heading', { name: /Master Settings/i })).toBeVisible();
  }
  await page.goBack();
  await expect(page.getByText('System Dashboard')).toBeVisible();
  await page.goForward();
  await expect(page.getByRole('heading', { name: /Master Settings/i })).toBeVisible();
  const restoredMaterial = page.locator('.material-master-accordion', { hasText: materialName });
  if (await restoredMaterial.locator('.material-accordion-trigger').getAttribute('aria-expanded') === 'false') {
    await restoredMaterial.locator('.material-accordion-trigger').click();
  }
  page.once('dialog', (dialog) => dialog.accept());
  await restoredMaterial.locator('.variant-subdelete').click();
  await expect(restoredMaterial.locator('.material-variant-subrow')).toHaveCount(0);
  expect(requests).toHaveLength(2);
  await expect(restoredMaterial.locator('.material-accordion-trigger')).toBeDisabled();
  await diagnostics.assertClean();
});
