import { expect, type Page } from '@playwright/test';
import { routes } from './testData';

export async function goTo(page: Page, route: string, heading: RegExp | string) {
  await page.goto(route);
  await expect(page.getByRole('heading', { name: heading })).toBeVisible();
}

export async function openViaNav(page: Page, label: string, urlPattern: RegExp, heading: RegExp | string) {
  await page.locator('.nav-links').getByText(label, { exact: true }).click();
  await expect(page).toHaveURL(urlPattern);
  await expect(page.getByRole('heading', { name: heading })).toBeVisible();
}

export async function searchComplaints(page: Page, query: string, searchBy: string) {
  await page.getByPlaceholder(/Search complaints/i).fill(query);
  await page.locator(`.search-option[data-search-by="${searchBy}"]`).click();
  await page.waitForLoadState('domcontentloaded');
}

export const appRoutes = routes;
