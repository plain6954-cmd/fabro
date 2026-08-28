import { expect, test } from '@playwright/test';
import { login } from '../helpers/auth';
import { attachPageDiagnostics, expectNoDjangoError } from '../helpers/assertions';
import { routes, sample } from '../helpers/testData';

test.beforeEach(async ({ page }) => {
  await login(page);
});

test('vehicle pages support add, search, edit and delete', async ({ page }) => {
  const diagnostics = attachPageDiagnostics(page);
  await page.goto(routes.addVehicle);
  await page.getByTitle('Add New Vehicle').click();
  await page.locator('#inline-add-row input[name="layout_code"]').fill(sample.vehicleLayout);
  await page.locator('#inline-add-row input[name="brand_name"]').fill(`PLAYWRIGHT CAR ${sample.vehicleLayout}`);
  await page.locator('#inline-add-row input[name="model_name"]').fill(`MODEL ${sample.vehicleLayout}`);
  await page.locator('#inline-add-row input[name="sub_model_name"]').fill('TRIM');
  await page.locator('input[name="year_start"]').fill('2024');
  await page.locator('input[name="year_end"]').fill('2026');
  await page.locator('input[name="number_of_seats"]').fill('5');
  await page.locator('input[name="number_of_doors"]').fill('4');
  await page.getByTitle('Add Vehicle').click({ force: true });
  await expect(page.getByRole('heading', { name: /Vehicle Management/i })).toBeVisible();

  await page.goto(routes.vehicles);
  await page.getByPlaceholder(/Search Vehicles/i).fill(sample.vehicleLayout);
  await expect(page.locator('#vehicleSearchDropdown')).toBeVisible();
  await expect(page.locator('#vehicleSearchDropdown')).toContainText('All Columns');
  await expect(page.locator('#vehicleSearchDropdown')).toContainText('Layout Code');
  await expect(page.locator('#vehicleSearchDropdown')).toContainText('Brand');
  await expect(page.locator('#vehicleSearchDropdown')).toContainText('Model');
  await expect(page.locator('#vehicleSearchDropdown')).toContainText('Sub-Model');
  await page.locator('#vehicleSearchDropdown [data-column="layout_code"]').click();
  await expect.poll(() => new URL(page.url()).searchParams.get('column')).toBe('layout_code');
  await expect.poll(() => new URL(page.url()).searchParams.get('search')).toBe(sample.vehicleLayout);
  await expect(page.getByText(sample.vehicleLayout, { exact: true })).toBeVisible();
  await page.locator('tr', { hasText: sample.vehicleLayout }).locator('.action-btn.edit').click({ force: true });
  await expect(page).toHaveURL(/\/edit-car\//);
  await page.locator('input[name="number_of_seats"]').fill('6');
  await page.getByRole('button', { name: /Save Changes/i }).click({ force: true });
  await expect(page).toHaveURL(/\/car-details\/$/);

  page.once('dialog', (dialog) => dialog.accept());
  await page.locator('tr', { hasText: sample.vehicleLayout }).locator('.action-btn.delete').click({ force: true });
  await expect(page.getByText(sample.vehicleLayout)).toHaveCount(0);
  await expectNoDjangoError(page);
  await diagnostics.assertClean();
});
