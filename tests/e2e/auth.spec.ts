import { expect, test } from '@playwright/test';
import { login, logout } from '../helpers/auth';
import { attachPageDiagnostics, expectNoDjangoError } from '../helpers/assertions';
import { routes, testUser } from '../helpers/testData';

test.describe('authentication', () => {
  test('valid login persists session and logout works', async ({ page }) => {
    const diagnostics = attachPageDiagnostics(page);
    await login(page);
    await page.reload();
    await expect(page.getByText('System Dashboard')).toBeVisible();
    await logout(page);
    await diagnostics.assertClean();
  });

  test('invalid login shows validation message', async ({ page }) => {
    const diagnostics = attachPageDiagnostics(page);
    await page.goto(routes.login);
    await page.getByLabel('Username').fill(testUser.username);
    await page.getByLabel('Password').fill('wrong-password');
    await page.getByRole('button', { name: /sign in/i }).click();
    await expect(page.getByText(/Invalid username or password/i)).toBeVisible();
    await expectNoDjangoError(page);
    await diagnostics.assertClean();
  });

  test('protected pages redirect anonymous users to login', async ({ page }) => {
    await page.goto(routes.dashboard);
    await expect(page).toHaveURL(/\/login\/\?next=/);
    await expect(page.getByRole('heading', { name: /Welcome Back/i })).toBeVisible();
  });
});
