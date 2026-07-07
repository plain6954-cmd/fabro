import { expect, type Page } from '@playwright/test';
import { routes, testUser } from './testData';

export async function login(page: Page) {
  await page.goto(routes.login);
  await page.getByLabel('Username').fill(testUser.username);
  await page.getByLabel('Password').fill(testUser.password);
  await page.getByRole('button', { name: /sign in/i }).click({ noWaitAfter: true });
  await expect(page.getByText('System Dashboard')).toBeVisible();
}

export async function logout(page: Page) {
  await page.locator('.profile-trigger').hover();
  page.once('dialog', (dialog) => dialog.accept());
  await page.locator('.profile-dropdown-content .dropdown-item', { hasText: 'Logout' }).click();
  await expect(page).toHaveURL(/\/login\/|\/logout/);
}
