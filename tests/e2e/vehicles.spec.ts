import { expect, test } from '@playwright/test';
import { login } from '../helpers/auth';
import { attachPageDiagnostics, expectNoDjangoError } from '../helpers/assertions';
import { routes, sample } from '../helpers/testData';

test.beforeEach(async ({ page }) => {
  await login(page);
});

test('vehicle pages support add, search, edit and deletion approval requests', async ({ page }) => {
  test.setTimeout(90_000);
  const diagnostics = attachPageDiagnostics(page);
  await page.goto(routes.addVehicle);
  await page.getByTitle('Add New Pattern').click();
  await page.locator('#inline-add-row input[name="x_code"]').fill(sample.vehicleLayout);
  await page.locator('#inline-add-row input[name="brand_name"]').fill(`PLAYWRIGHT CAR ${sample.vehicleLayout}`);
  await page.locator('#inline-add-row input[name="model_name"]').fill(`MODEL ${sample.vehicleLayout}`);
  await page.locator('#inline-add-row input[name="sub_model_name"]').fill('TRIM');
  await page.locator('#inline-add-row input[name="year_start"]').fill('2024');
  await page.locator('#inline-add-row input[name="year_end"]').fill('2026');
  await page.locator('#inline-add-row input[name="number_of_seats"]').fill('5');
  await page.locator('#inline-add-row input[name="number_of_doors"]').fill('4');
  await page.locator('#inline-add-row [title="Add Vehicle"]').click();
  await expect(page.getByRole('heading', { name: /Pattern Master/i })).toBeVisible();

  await page.goto(routes.vehicles);
  await page.locator('#vehicle-search-input').fill(sample.vehicleLayout);
  await expect(page.locator('#vehicle-search-options')).toBeVisible();
  await expect(page.locator('#vehicle-search-options')).toContainText('All Fields');
  await expect(page.locator('#vehicle-search-options')).toContainText('X-Code');
  await expect(page.locator('#vehicle-search-options')).toContainText('Brand');
  await expect(page.locator('#vehicle-search-options')).toContainText('Model');
  await expect(page.locator('#vehicle-search-options')).toContainText('Sub-Model');
  await page.locator('#vehicle-search-options [data-search-by="x_code"]').click();
  await expect.poll(() => new URL(page.url()).searchParams.get('search_by')).toBe('x_code');
  await expect.poll(() => new URL(page.url()).searchParams.get('search')).toBe(sample.vehicleLayout);
  const createdRow = page.locator('tr[id^="row-view-"]', { hasText: sample.vehicleLayout });
  await expect(createdRow).toBeVisible();
  await createdRow.locator('.pattern-row-select').check();
  await page.locator('#patternActionsToggleBtn').click();
  await page.locator('#actionBtnEdit').click();
  const editRow = page.locator('tr.inline-edit-row:visible');
  await editRow.locator('input[name="number_of_seats"]').fill('6');
  await editRow.locator('.save-btn').click();
  await expect(createdRow.locator('.col-seats')).toHaveText('6');

  await createdRow.locator('.pattern-row-select').check();
  await page.locator('#patternActionsToggleBtn').click();
  page.once('dialog', (dialog) => dialog.accept());
  const deletionResponse = page.waitForResponse((response) => response.url().includes('/api/patterns/bulk-delete/') && response.request().method() === 'POST');
  await page.locator('#actionBtnDeleteSingle').click();
  const response = await deletionResponse;
  expect(response.status()).toBe(200);
  expect(await response.json()).toMatchObject({ success: true });
  await expect(createdRow).toBeVisible();
  await expectNoDjangoError(page);
  await diagnostics.assertClean();
});
