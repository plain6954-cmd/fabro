import { expect, test } from '@playwright/test';
import { login } from '../helpers/auth';
import { routes } from '../helpers/testData';

const viewports = [
  { width: 320, height: 568 },
  { width: 390, height: 844 },
  { width: 568, height: 320 },
  { width: 768, height: 1024 },
  { width: 1024, height: 768 },
  { width: 1366, height: 768 },
  { width: 1920, height: 1080 },
];

test('catalog pages remain usable across phone, tablet, and desktop sizes', async ({ page }) => {
  await login(page);

  for (const viewport of viewports) {
    await page.setViewportSize(viewport);

    for (const route of [routes.sku, routes.master]) {
      await page.goto(route);
      await expect(page.locator('#app-content h1')).toBeVisible();

      const layout = await page.evaluate(() => {
        const workspace = document.querySelector('.sku-workspace');
        const list = document.querySelector('.sku-workspace .table-container');
        const bottomNav = document.querySelector('.mobile-bottom-nav');
        const category = document.querySelector('.category-card');
        const action = Array.from(document.querySelectorAll('.sku-workspace .action-btn, .setting-item .action-btn'))
          .find((element) => element.getBoundingClientRect().width > 0);
        const search = document.querySelector('.sku-toolbar__search-row .header-search-input');
        const rect = (element: Element | null) => element?.getBoundingClientRect();
        return {
          documentWidth: document.documentElement.scrollWidth,
          viewportWidth: window.innerWidth,
          workspaceBottom: rect(workspace)?.bottom,
          listHeight: rect(list)?.height,
          navTop: bottomNav && getComputedStyle(bottomNav).display !== 'none' ? rect(bottomNav)?.top : null,
          categoryHeight: rect(category)?.height,
          actionWidth: rect(action)?.width,
          actionHeight: rect(action)?.height,
          searchRight: rect(search)?.right,
        };
      });

      expect(layout.documentWidth, `${route} at ${viewport.width}px overflows horizontally`).toBeLessThanOrEqual(layout.viewportWidth + 1);
      if (route === routes.sku) {
        expect(layout.listHeight).toBeGreaterThan(100);
        if (viewport.width <= 768 && viewport.height >= 500) {
          expect(layout.workspaceBottom).toBeLessThanOrEqual((layout.navTop ?? viewport.height) - 4);
          expect(layout.actionWidth).toBeGreaterThanOrEqual(44);
          expect(layout.actionHeight).toBeGreaterThanOrEqual(44);
          expect(layout.searchRight).toBeLessThanOrEqual(viewport.width);
        }
      } else if (viewport.width <= 699) {
        expect(layout.categoryHeight).toBeLessThan(200);
        expect(layout.actionWidth).toBeGreaterThanOrEqual(44);
        expect(layout.actionHeight).toBeGreaterThanOrEqual(44);
      }
    }
  }
});

test('CSV upload expansion does not clip the SKU list on a phone', async ({ page }) => {
  await login(page);
  await page.setViewportSize({ width: 320, height: 568 });
  await page.goto(routes.sku);
  await page.locator('#btnToggleCsvUpload').click();
  await expect(page.locator('#csvExpandContainer')).toBeVisible();
  await expect(page.locator('.sku-workspace')).toHaveClass(/sku-workspace--csv-open/);
  await expect(page.locator('.sku-workspace .table-container')).toBeVisible();
  await page.locator('.sku-workspace .table-container').scrollIntoViewIfNeeded();
  await expect(page.locator('.sku-workspace .table-container')).toBeInViewport();
});

test('complaint search fits narrow phones with usable controls', async ({ page }) => {
  await login(page);
  for (const width of [320, 390, 768]) {
    await page.setViewportSize({ width, height: 844 });
    await page.goto(routes.complaints);
    await expect(page.locator('#header-search-input')).toBeVisible();

    const layout = await page.evaluate(() => {
      const form = document.querySelector('#header-search-form')!.getBoundingClientRect();
      const buttons = Array.from(document.querySelectorAll('#header-search-form .icon-btn'))
        .map((button) => button.getBoundingClientRect());
      return {
        documentWidth: document.documentElement.scrollWidth,
        formRight: form.right,
        buttonSizes: buttons.map((button) => [button.width, button.height]),
      };
    });

    expect(layout.documentWidth).toBeLessThanOrEqual(width + 1);
    expect(layout.formRight).toBeLessThanOrEqual(width);
    for (const [buttonWidth, buttonHeight] of layout.buttonSizes) {
      expect(buttonWidth).toBeGreaterThanOrEqual(44);
      expect(buttonHeight).toBeGreaterThanOrEqual(44);
    }
  }
});

test('profile and language menus respond to touch and dismiss outside', async ({ browser }) => {
  const context = await browser.newContext({
    baseURL: process.env.E2E_BASE_URL || `http://127.0.0.1:${process.env.E2E_PORT || '8001'}`,
    viewport: { width: 390, height: 844 },
    isMobile: true,
    hasTouch: true,
  });
  try {
    const page = await context.newPage();
    await login(page);
    await page.locator('.profile-trigger').tap();
    await expect(page.locator('.profile-dropdown')).toHaveClass(/is-open/);
    await page.locator('.language-menu-trigger').tap();
    await expect(page.locator('.language-menu')).toHaveClass(/is-pinned/);
    await page.touchscreen.tap(10, 400);
    await expect(page.locator('.profile-dropdown')).not.toHaveClass(/is-open/);
  } finally {
    await context.close();
  }
});

test('pattern master search input fits narrow phones without placeholder truncation', async ({ page }) => {
  await login(page);

  for (const width of [320, 360, 390]) {
    await page.setViewportSize({ width, height: 740 });
    await page.goto(routes.vehicles);

    const searchInput = page.locator('#vehicle-search-input');
    await expect(searchInput).toBeVisible();

    const metrics = await searchInput.evaluate((el: HTMLInputElement) => {
      const style = window.getComputedStyle(el);
      const rect = el.getBoundingClientRect();
      const paddingLeft = parseFloat(style.paddingLeft);
      const paddingRight = parseFloat(style.paddingRight);
      const availableTextWidth = rect.width - paddingLeft - paddingRight;
      return {
        width: rect.width,
        paddingLeft,
        paddingRight,
        availableTextWidth,
        placeholder: el.placeholder,
      };
    });

    expect(metrics.placeholder).toMatch(/Search/i);
    expect(metrics.paddingRight).toBeLessThanOrEqual(16);
    expect(metrics.availableTextWidth).toBeGreaterThanOrEqual(100);
  }
});

test('mobile complaint filters apply and clear without hiding the list', async ({ page }) => {
  await login(page);
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto(routes.complaints);

  await page.locator('#filter-toggle').click();
  await expect(page.locator('#mobileFiltersSheet')).toHaveAttribute('aria-hidden', 'false');
  await page.locator('#mfcComplaintType').selectOption('pattern');
  await page.locator('#mfApplyBtn').click();
  await expect(page).toHaveURL(/complaint_type=pattern/);
  await expect(page.locator('#mobileFilterBadge')).toHaveText('1');
  await expect(page.locator('.table-container')).toBeVisible();

  await page.locator('#filter-toggle').click();
  await page.locator('#mfResetBtn').click();
  await expect(page).not.toHaveURL(/complaint_type=pattern/);
  await expect(page.locator('#mobileFilterBadge')).toBeHidden();
});
