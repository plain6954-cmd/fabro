import { expect, test } from '@playwright/test';
import { login } from '../helpers/auth';
import { attachPageDiagnostics, expectNoDjangoError } from '../helpers/assertions';
import { routes } from '../helpers/testData';

test.beforeEach(async ({ page }) => {
  await login(page);
});

test('profile page loads and saves account details', async ({ page }) => {
  const diagnostics = attachPageDiagnostics(page);
  await page.goto(routes.profile);
  await expect(page.getByRole('heading', { name: /Profile Settings/i })).toBeVisible();
  await page.locator('input[name="email"]').fill('fabro.e2e.updated@example.com');
  await page.locator('input[name="first_name"]').fill('Fabro');
  await page.locator('input[name="last_name"]').fill('Tester');
  await page.getByRole('button', { name: /Save Details/i }).click({ noWaitAfter: true });
  await expect(page.getByText(/profile details have been updated/i)).toBeVisible();
  await expectNoDjangoError(page);
  await diagnostics.assertClean();
});
