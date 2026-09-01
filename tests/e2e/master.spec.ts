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
  await page.getByRole('button', { name: /Add Setting/i }).click({ force: true });
  await expect(page.getByText(sample.masterName)).toBeVisible();

  const createdSetting = page.locator('.setting-item', { hasText: sample.masterName });
  await expect(createdSetting).toBeVisible();
  await createdSetting.locator('.action-btn.edit').click({ force: true });
  await expect(page.locator('#editModal')).toBeVisible();
  await page.locator('#editName').fill(`${sample.masterName} Updated`);
  await page.getByRole('button', { name: /Update Setting/i }).click({ force: true });
  await expect(page.getByText(`${sample.masterName} Updated`)).toBeVisible();

  page.once('dialog', (dialog) => dialog.accept());
  await page.locator('.setting-item', { hasText: `${sample.masterName} Updated` }).locator('.action-btn.delete').click({ force: true });
  await expect(page.getByText(`${sample.masterName} Updated`)).toHaveCount(0);
  await expectNoDjangoError(page);
  await diagnostics.assertClean();
});

test('master settings translates its controls and built-in values', async ({ page }) => {
  await page.goto(routes.master);

  try {
    await page.locator('.profile-trigger').click();
    await page.locator('.language-menu-trigger').click();
    await page.locator('.language-menu-option[value="ar"]').click();
    await page.waitForLoadState('domcontentloaded');

    await expect(page.getByRole('heading', { name: 'الإعدادات الرئيسية' })).toBeVisible();
    await expect(page.getByText('إضافة إعداد جديد', { exact: true })).toBeVisible();
    await expect(page.getByText('الإعدادات الحالية', { exact: true })).toBeVisible();
    const addSettingForm = page.locator('.form-section');
    await expect(addSettingForm.getByText('الفئة', { exact: true })).toBeVisible();
    await expect(addSettingForm.getByText('الاسم', { exact: true })).toBeVisible();
    await expect(page.getByRole('button', { name: 'إضافة الإعداد' })).toBeVisible();
    await expect(page.getByText('واتساب', { exact: true })).toBeVisible();
  } finally {
    if (!page.isClosed()) {
      await page.locator('.profile-trigger').click();
      await page.locator('.language-menu-trigger').click();
      await page.locator('.language-menu-option[value="en"]').click();
      await page.waitForLoadState('domcontentloaded');
    }
  }
});
