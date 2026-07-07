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
  await page.getByPlaceholder(/layout code/i).fill(sample.vehicleLayout);
  await page.getByPlaceholder(/BMW|Mercedes/i).fill(`PLAYWRIGHT CAR ${sample.vehicleLayout}`);
  await page.getByPlaceholder(/X5|C-Class/i).fill(`MODEL ${sample.vehicleLayout}`);
  await page.getByPlaceholder(/Sport|Luxury/i).fill('TRIM');
  await page.locator('input[name="year_start"]').fill('2024');
  await page.locator('input[name="year_end"]').fill('2026');
  await page.locator('input[name="number_of_seats"]').fill('5');
  await page.locator('input[name="number_of_doors"]').fill('4');
  await page.getByRole('button', { name: /Add Vehicle/i }).click({ noWaitAfter: true });
  await expect(page.getByRole('heading', { name: /Vehicle Management/i })).toBeVisible();

  await page.goto(routes.vehicles);
  await page.getByPlaceholder(/Search by Layout Code/i).fill(sample.vehicleLayout);
  await expect(page.getByText(sample.vehicleLayout, { exact: true })).toBeVisible();
  await page.locator('tr', { hasText: sample.vehicleLayout }).locator('.action-btn.edit').click();
  await expect(page).toHaveURL(/\/edit-car\//);
  await page.locator('input[name="number_of_seats"]').fill('6');
  await page.getByRole('button', { name: /Save Changes/i }).click({ noWaitAfter: true });
  await expect(page).toHaveURL(/\/car-details\/$/);

  page.once('dialog', (dialog) => dialog.accept());
  await page.locator('tr', { hasText: sample.vehicleLayout }).locator('.action-btn.delete').click();
  await expect(page.getByText(sample.vehicleLayout)).toHaveCount(0);
  await expectNoDjangoError(page);
  await diagnostics.assertClean();
});
