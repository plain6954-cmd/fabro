import { expect, test } from '@playwright/test';
import { login } from '../helpers/auth';
import { runDjangoCode } from '../helpers/django';
import { routes } from '../helpers/testData';

test('admin pagination follows browser history and fits a narrow viewport', async ({ page }) => {
  runDjangoCode(`
from management.models import SKU
SKU.objects.bulk_create([
    SKU(code=f'E2E-PAGE-{number:03d}', description='Admin pagination fixture')
    for number in range(55)
])
`);
  try {
    await login(page);
    await page.goto(routes.adminPanel);
    await page.locator('#side-skus').click();
    const skuPane = page.locator('#tab-skus');
    await expect(skuPane.locator('.erp-pagination')).toBeVisible();
    await skuPane.locator('.pattern-pagination__control--next').click();
    await expect(page).toHaveURL(/section=skus&section_page=2#skus$/);
    await expect(skuPane.locator('.pattern-pagination__bubble.is-active')).toHaveText('2');

    await page.locator('#side-users').click();
    await expect(page).toHaveURL(/section=users#users$/);
    await page.goBack();
    await expect(page).toHaveURL(/section=skus&section_page=2#skus$/);
    await expect(skuPane.locator('.pattern-pagination__bubble.is-active')).toHaveText('2');
    await page.goBack();
    await expect(page).toHaveURL(/section=skus#skus$/);
    await expect(skuPane.locator('.pattern-pagination__bubble.is-active')).toHaveText('1');
    await page.goForward();
    await expect(page).toHaveURL(/section=skus&section_page=2#skus$/);
    await expect(skuPane.locator('.pattern-pagination__bubble.is-active')).toHaveText('2');

    await page.setViewportSize({ width: 320, height: 740 });
    await expect(skuPane.locator('.erp-pagination')).toBeVisible();
    const overflow = await page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth);
    expect(overflow).toBeLessThanOrEqual(1);
  } finally {
    runDjangoCode(`
from management.models import SKU
SKU.objects.filter(code__startswith='E2E-PAGE-').delete()
`);
  }
});
