import { expect, test } from '@playwright/test';
import path from 'path';
import { login } from '../helpers/auth';
import { attachPageDiagnostics, expectNoDjangoError } from '../helpers/assertions';
import { routes, sample } from '../helpers/testData';

test.beforeEach(async ({ page }) => {
  await login(page);
});

test('add complaint form supports fields, clear, cancel, upload, save, view, search, edit and delete', async ({ page }) => {
  const diagnostics = attachPageDiagnostics(page);
  await page.goto(routes.addComplaint);
  await expect(page.getByRole('heading', { name: /Add New Complaint/i })).toBeVisible();

  const description = page.locator('textarea[name="complaint_description"]');
  await description.fill('Text cleared by reset');
  await page.getByRole('button', { name: /Clear/i }).click();
  await expect(description).toHaveValue('Not Provided');

  await description.fill(sample.complaintText);
  await page.locator('select[name="channel"]').selectOption({ index: 1 }).catch(() => {});
  await page.locator('select[name="country"]').selectOption({ index: 1 }).catch(() => {});
  await page.locator('select[name="person"]').selectOption({ index: 1 }).catch(() => {});
  await page.locator('select[name="case_sub_category"]').selectOption({ index: 1 }).catch(() => {});
  await page.locator('select[name="series"]').selectOption({ index: 1 }).catch(() => {});
  await page.locator('select[name="material"]').selectOption({ index: 1 }).catch(() => {});
  await page.locator('select[name="sku"]').selectOption({ index: 1 }).catch(() => {});
  await page.locator('input[name="media_files"]').setInputFiles(path.join(process.cwd(), 'static', 'FABRO__BRAND ICON_FINAL_CMYK.png'));
  await expect(page.getByText(/file\(s\) selected/i)).toBeVisible();
  await page.getByRole('button', { name: /Save Complaint/i }).click({ noWaitAfter: true });
  await expect(page.getByRole('heading', { name: /Complaint Management/i })).toBeVisible();

  await page.getByPlaceholder(/Search complaints/i).fill(sample.complaintText);
  await page.locator('select[name="search_by"]').selectOption('complaint_description');
  await page.getByRole('button', { name: /Apply Filters/i }).click();
  const createdRow = page.locator('tbody tr').first();
  await expect(createdRow).toBeVisible();

  await createdRow.locator('.action-btn.view').click();
  await expect(page.locator('.complaint-modal.is-open')).toBeVisible();
  await expect(page.getByText(sample.complaintText)).toBeVisible();
  await page.locator('.complaint-modal .close-btn').click();

  await createdRow.locator('.action-btn.edit').click();
  await expect(page).toHaveURL(/\/complaint\/edit\//);
  await page.locator('select[name="status"]').selectOption('On Hold');
  await page.locator('select[name="priority"]').selectOption('High');
  await page.getByRole('button', { name: /Update Complaint|Save/i }).click({ noWaitAfter: true });
  await expect(page.getByRole('heading', { name: /Complaint Management/i })).toBeVisible();
  await page.getByPlaceholder(/Search complaints/i).fill(sample.complaintText);
  await page.locator('select[name="search_by"]').selectOption('complaint_description');
  await page.getByRole('button', { name: /Apply Filters/i }).click();

  page.once('dialog', (dialog) => dialog.accept());
  await page.locator('tbody tr').first().locator('.action-btn.delete').click();
  await page.getByPlaceholder(/Search complaints/i).fill(sample.complaintText);
  await page.locator('select[name="search_by"]').selectOption('complaint_description');
  await page.getByRole('button', { name: /Apply Filters/i }).click();
  await expect(page.locator('.empty-state').or(page.locator('tbody'))).toBeVisible();
  await expect(page.locator('tbody tr')).toHaveCount(0);
  await expectNoDjangoError(page);
  await diagnostics.assertClean();
});

test('cancel returns from add complaint to complaint list', async ({ page }) => {
  await page.goto(routes.addComplaint);
  await page.getByRole('link', { name: /Cancel/i }).click();
  await expect(page).toHaveURL(/\/complaints\/$/);
});
