import { chromium } from '@playwright/test';

const baseURL = process.env.FABRO_AUDIT_BASE_URL || 'http://127.0.0.1:8000';
const username = process.env.FABRO_AUDIT_USERNAME || 'audit_admin';
const password = process.env.FABRO_AUDIT_PASSWORD;

if (!password) {
  throw new Error('FABRO_AUDIT_PASSWORD is required.');
}

const routes = [
  '/',
  '/complaints/',
  '/add-complaint/',
  '/car-details/',
  '/add-car-details/',
  '/add-sku/',
  '/master-settings/',
  '/profile/',
  '/admin_panel/',
  '/notifications/',
];

const viewports = [
  { name: 'desktop', width: 1366, height: 768 },
  { name: 'tablet', width: 834, height: 1112 },
  { name: 'mobile', width: 390, height: 844 },
];

const browser = await chromium.launch({ headless: true });
const context = await browser.newContext({ viewport: viewports[0] });
const page = await context.newPage();
const pageErrors = [];
const consoleErrors = [];
const httpErrors = [];

page.on('pageerror', (error) => pageErrors.push(error.message));
page.on('console', (message) => {
  if (message.type() === 'error') consoleErrors.push(message.text());
});
page.on('response', (response) => {
  if (response.status() >= 400) {
    httpErrors.push(`${response.status()} ${response.url()}`);
  }
});

await page.goto(`${baseURL}/login/`, { waitUntil: 'domcontentloaded' });
await page.getByLabel('Username').fill(username);
await page.getByLabel('Password').fill(password);
await page.getByRole('button', { name: /sign in/i }).click();
await page.waitForURL((url) => url.pathname === '/');

const results = [];
for (const viewport of viewports) {
  await page.setViewportSize(viewport);
  for (const route of routes) {
    const started = Date.now();
    const response = await page.goto(`${baseURL}${route}`, {
      waitUntil: 'domcontentloaded',
      timeout: 60_000,
    });
    const metrics = await page.evaluate(() => ({
      bodyTextLength: document.body?.innerText?.trim().length || 0,
      horizontalOverflow: Math.max(
        document.documentElement.scrollWidth - document.documentElement.clientWidth,
        document.body.scrollWidth - document.body.clientWidth,
      ),
      profileText: document.querySelector('.profile-trigger')?.textContent?.replace(/\s+/g, ' ').trim() || '',
      heading: document.querySelector('h1, h2')?.textContent?.replace(/\s+/g, ' ').trim() || '',
    }));
    results.push({
      viewport: viewport.name,
      route,
      status: response?.status() || 0,
      milliseconds: Date.now() - started,
      ...metrics,
    });
  }
}

console.log(JSON.stringify({ results, pageErrors, consoleErrors, httpErrors: [...new Set(httpErrors)] }, null, 2));
await browser.close();
