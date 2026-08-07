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
  await page.locator('#btnToggleAddSku').click();
  await page.locator('#id_code').fill(sample.skuCode);
  await page.locator('#id_description').fill('Playwright SKU description');
  await page.locator('#id_region').selectOption({ index: 1 }).catch(() => {});
  await page.locator('button[name="add_sku"]').click({ force: true });
  await expect(page.getByText(sample.skuCode)).toBeVisible();

  await page.getByPlaceholder(/Search SKUs/i).fill(sample.skuCode);
  await expect(page.locator('#skuTableBody')).toContainText(sample.skuCode);
  const skuRow = page.locator('tr', { hasText: sample.skuCode });
  const skuRowId = await skuRow.getAttribute('id');
  const skuId = skuRowId?.replace('sku-row-', '');
  await skuRow.locator('.action-btn.edit').click({ force: true });
  const editRow = page.locator(`#sku-edit-row-${skuId}`);
  await editRow.locator('input[name="description"]').fill('Updated Playwright SKU');
  await editRow.locator('button[title="Save Changes"]').click({ force: true });
  await expect(page).toHaveURL(/\/add-sku\/$/);

  page.once('dialog', (dialog) => dialog.accept());
  await page.locator('tr', { hasText: sample.skuCode }).locator('.action-btn.delete').click({ force: true });
  await expect(page.getByText(sample.skuCode)).toHaveCount(0);
  await expectNoDjangoError(page);
  await diagnostics.assertClean();
});
