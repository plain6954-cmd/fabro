import { expect, test } from '@playwright/test';
import { login } from '../helpers/auth';
import { expectNoDjangoError } from '../helpers/assertions';
import { routes } from '../helpers/testData';

test.beforeEach(async ({ page }) => {
  await login(page);
});

test('main pages are not blank across configured device projects', async ({ page }) => {
  const viewports = [
    { name: 'desktop', width: 1366, height: 768 },
    { name: 'tablet', width: 834, height: 1112 },
    { name: 'mobile', width: 390, height: 844 }
  ];

  for (const viewport of viewports) {
    await page.setViewportSize({ width: viewport.width, height: viewport.height });
    for (const route of [routes.dashboard, routes.addComplaint, routes.vehicles, routes.sku, routes.master, routes.profile]) {
      await page.goto(route);
      await expect(page.locator('body'), `${viewport.name} ${route}`).not.toBeEmpty();
      await expect(page.locator('.navbar'), `${viewport.name} ${route}`).toBeVisible();
      await expectNoDjangoError(page);
    }
  }
});

test('Arabic and Hindi retain LTR layout and translations at desktop and mobile widths', async ({ page }) => {
  const cases = [
    { language: 'ar', direction: 'ltr', dashboard: 'لوحة التحكم' },
    { language: 'hi', direction: 'ltr', dashboard: 'डैशबोर्ड' }
  ];

  for (const viewport of [{ width: 1366, height: 768 }, { width: 390, height: 844 }]) {
    await page.setViewportSize(viewport);
    for (const item of cases) {
      await page.goto(routes.dashboard);
      await page.locator('.profile-trigger').click();
      await page.locator('.language-menu-trigger').click();
      const languageOption = page.locator(`.language-menu-option[value="${item.language}"]`);
      await Promise.all([
        page.waitForNavigation(),
        languageOption.evaluate((button: HTMLButtonElement) => button.form?.requestSubmit(button))
      ]);

      await expect(page.locator('html')).toHaveAttribute('lang', item.language);
      await expect(page.locator('html')).toHaveAttribute('dir', item.direction);
      await expect(page.locator('body')).toContainText(item.dashboard);
      const horizontalOverflow = await page.evaluate(
        () => document.documentElement.scrollWidth - window.innerWidth
      );
      expect(horizontalOverflow).toBeLessThanOrEqual(1);
      await expectNoDjangoError(page);
    }
  }

  await page.goto(routes.dashboard);
  await page.locator('.profile-trigger').click();
  await page.locator('.language-menu-trigger').click();
  const englishOption = page.locator('.language-menu-option[value="en"]');
  await Promise.all([
    page.waitForNavigation(),
    englishOption.evaluate((button: HTMLButtonElement) => button.form?.requestSubmit(button))
  ]);
});

test('dashboard split layout scales cleanly without horizontal overflow across screen sizes', async ({ page }) => {
  const viewports = [
    { name: 'desktop', width: 1366, height: 768 },
    { name: 'tablet', width: 834, height: 1112 },
    { name: 'mobile', width: 390, height: 844 }
  ];

  for (const viewport of viewports) {
    await page.setViewportSize({ width: viewport.width, height: viewport.height });
    await page.goto(routes.dashboard);

    await expect(page.locator('.dashboard-container')).toBeVisible();
    await expect(page.getByText('Existing Complaints')).toBeVisible();

    const horizontalOverflow = await page.evaluate(
      () => document.documentElement.scrollWidth - window.innerWidth
    );
    expect(horizontalOverflow, `horizontal overflow on ${viewport.name}`).toBeLessThanOrEqual(1);
    await expectNoDjangoError(page);
  }
});

