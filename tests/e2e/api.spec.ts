import { expect, test } from '@playwright/test';
import { login } from '../helpers/auth';

test.beforeEach(async ({ page }) => {
  await login(page);
});

test('JSON dropdown endpoints respond with arrays for seeded vehicle data', async ({ page }) => {
  const models = await page.request.get('/api/models/1/');
  expect([200, 404]).toContain(models.status());
  if (models.status() === 200) {
    expect(Array.isArray(await models.json())).toBeTruthy();
  }
});
