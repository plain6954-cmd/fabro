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
