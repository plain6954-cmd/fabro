import { expect, test } from '@playwright/test';
import { login } from '../helpers/auth';
import { attachPageDiagnostics, expectNoDjangoError } from '../helpers/assertions';
import { routes, sample } from '../helpers/testData';

test.beforeEach(async ({ page }) => {
  await login(page);
});

test('SKU page supports add, search, edit and delete', async ({ page }) => {
  const diagnostics = attachPageDiagnostics(page);
  await page.goto(routes.sku);
  await page.locator('input[name="code"]').fill(sample.skuCode);
  await page.locator('textarea[name="description"]').fill('Playwright SKU description');
  await page.locator('select[name="region"]').selectOption({ index: 1 }).catch(() => {});
  await page.locator('button[name="add_sku"]').click({ force: true });
  await expect(page.getByText(sample.skuCode)).toBeVisible();

  await page.getByPlaceholder(/Search SKUs/i).fill(sample.skuCode);
  await expect(page.locator('#skuTableBody')).toContainText(sample.skuCode);
  await page.locator('tr', { hasText: sample.skuCode }).locator('.action-btn.edit').click({ force: true });
  await page.locator('textarea[name="description"]').fill('Updated Playwright SKU');
  await page.getByRole('button', { name: /Update SKU/i }).click({ force: true });
  await expect(page).toHaveURL(/\/add-sku\/$/);

  page.once('dialog', (dialog) => dialog.accept());
  await page.locator('tr', { hasText: sample.skuCode }).locator('.action-btn.delete').click({ force: true });
  await expect(page.getByText(sample.skuCode)).toHaveCount(0);
  await expectNoDjangoError(page);
  await diagnostics.assertClean();
});
