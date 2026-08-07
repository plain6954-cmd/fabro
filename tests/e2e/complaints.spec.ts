import { expect, test } from '@playwright/test';
import path from 'path';
import { login } from '../helpers/auth';
import { attachPageDiagnostics, expectNoDjangoError } from '../helpers/assertions';
import { routes, sample } from '../helpers/testData';
import { searchComplaints } from '../helpers/navigation';

test.beforeEach(async ({ page }) => {
  await login(page);
});

test('complaint type remains recognizable and synchronized while editing', async ({ page }) => {
  await page.goto(routes.addComplaint);

  const typeInput = page.locator('#id_complaint_type');
  const indicator = page.locator('#complaint-type-indicator');
  const indicatorTitle = page.locator('#complaint-type-indicator-title');
  const saveButton = page.locator('#save-complaint-button');

  await expect(typeInput).toHaveValue('pattern');
  await expect(indicatorTitle).toHaveText('Pattern Complaint');
  await expect(saveButton).toHaveAttribute('aria-label', 'Save Pattern Complaint');

  await page.locator('#complaint-type-production').click();
  await expect(typeInput).toHaveValue('production');
  await expect(indicator).toHaveClass(/type-production/);
  await expect(indicatorTitle).toHaveText('Production Complaint');
  await expect(saveButton).toHaveAttribute('aria-label', 'Save Production Complaint');
  await expect(page.locator('#complaint-type-production')).toHaveAttribute('aria-pressed', 'true');

  await page.locator('#complaint-type-line').click();
  await expect(typeInput).toHaveValue('line');
  await expect(indicator).toHaveClass(/type-line/);
  await expect(indicatorTitle).toHaveText('Line Complaint');
  await expect(saveButton).toHaveAttribute('aria-label', 'Save Line Complaint');

  await page.getByRole('button', { name: /Clear complaint form/i }).click();
  await expect(typeInput).toHaveValue('line');
  await expect(indicatorTitle).toHaveText('Line Complaint');

  await page.setViewportSize({ width: 390, height: 844 });
  await page.evaluate(() => window.scrollTo(0, document.body.scrollHeight / 2));
  await expect(indicator).toBeVisible();
  const indicatorBox = await indicator.boundingBox();
  const navbarBox = await page.locator('.navbar').boundingBox();
  expect(indicatorBox).not.toBeNull();
  expect(navbarBox).not.toBeNull();
  expect(indicatorBox!.y).toBeGreaterThanOrEqual(navbarBox!.y + navbarBox!.height - 1);
  expect(indicatorBox!.x + indicatorBox!.width).toBeLessThanOrEqual(390);
});

test('add complaint form supports fields, clear, cancel, upload, save, view, search, edit and delete', async ({ page }) => {
  const diagnostics = attachPageDiagnostics(page);
  await page.goto(routes.addComplaint);
  await expect(page.getByRole('heading', { name: /Add New Complaint/i })).toBeVisible();

  const description = page.locator('textarea[name="complaint_description"]');
  await description.fill('Text cleared by reset');
  await page.getByRole('button', { name: /Clear/i }).click({ force: true });
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
  await page.locator('#save-complaint-button').click({ force: true });
  await expect(page.getByRole('heading', { name: /Complaint Management/i })).toBeVisible();

  await searchComplaints(page, sample.complaintText, 'description');
  const createdRow = page.locator('tbody tr').first();
  await expect(createdRow).toBeVisible();

  await createdRow.locator('.action-btn.view').click({ force: true });
  await expect(page.locator('.complaint-modal.is-open')).toBeVisible();
  await expect(page.getByText(sample.complaintText)).toBeVisible();
  await page.locator('.complaint-modal .close-btn').click({ force: true });

  await createdRow.locator('.action-btn.edit').click({ force: true });
  await expect(page).toHaveURL(/\/complaint\/edit\//);
  const workflowStatus = page.locator('select[name="status"]');
  await expect(workflowStatus).toBeDisabled();
  await expect(workflowStatus).toHaveValue('Open');
  await page.locator('select[name="priority"]').selectOption('High');
  await page.getByRole('button', { name: /Update Complaint|Save/i }).click({ force: true });
  await expect(page.getByRole('heading', { name: /Complaint Management/i })).toBeVisible();
  await searchComplaints(page, sample.complaintText, 'description');

  page.once('dialog', (dialog) => dialog.accept());
  await page.locator('tbody tr').first().locator('.action-btn.delete').click({ force: true });
  await searchComplaints(page, sample.complaintText, 'description');
  await expect(page.locator('.empty-state').or(page.locator('tbody'))).toBeVisible();
  await expect(page.locator('tbody tr')).toHaveCount(0);
  await expectNoDjangoError(page);
  await diagnostics.assertClean();
});

test('cancel returns from add complaint to complaint list', async ({ page }) => {
  await page.goto(routes.addComplaint);
  await page.getByRole('link', { name: /Cancel/i }).click({ force: true });
  await expect(page).toHaveURL(/\/complaints\/$/);
});
