import { expect, test } from '@playwright/test';
import { login } from '../helpers/auth';
import { attachPageDiagnostics, expectNoDjangoError } from '../helpers/assertions';
import { routes, sample } from '../helpers/testData';

test.beforeEach(async ({ page }) => {
  await login(page);
});

test('master settings supports add, edit modal and delete', async ({ page }) => {
  const diagnostics = attachPageDiagnostics(page);
  await page.goto(routes.master);
  await expect(page.getByText('Current Settings')).toBeVisible();
  await page.locator('#id_category').selectOption('Channel');
  await page.locator('#id_name').fill(sample.masterName);
  await page.getByRole('button', { name: /Add Setting/i }).click({ noWaitAfter: true });
  await expect(page.getByText(sample.masterName)).toBeVisible();

  await page.locator('.setting-item', { hasText: sample.masterName }).locator('.action-btn.edit').click();
  await expect(page.locator('#editModal')).toBeVisible();
  await page.locator('#editName').fill(`${sample.masterName} Updated`);
  await page.getByRole('button', { name: /Update Setting/i }).click({ noWaitAfter: true });
  await expect(page.getByText(`${sample.masterName} Updated`)).toBeVisible();

  page.once('dialog', (dialog) => dialog.accept());
  await page.locator('.setting-item', { hasText: `${sample.masterName} Updated` }).locator('.action-btn.delete').click();
  await expect(page.getByText(`${sample.masterName} Updated`)).toHaveCount(0);
  await expectNoDjangoError(page);
  await diagnostics.assertClean();
});
