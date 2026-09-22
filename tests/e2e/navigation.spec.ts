import { expect, test } from '@playwright/test';
import { login } from '../helpers/auth';
import { attachPageDiagnostics, expectNoDjangoError } from '../helpers/assertions';
import { routes } from '../helpers/testData';

test.beforeEach(async ({ page }) => {
  await login(page);
});

test('complaint toolbar uses accessible icon-only actions', async ({ page }) => {
  const diagnostics = attachPageDiagnostics(page);
  await page.goto(routes.complaints);

  const toolbar = page.locator('#app-content .header-actions');
  const addComplaint = toolbar.getByRole('link', { name: 'Add Complaint' });
  const exportCsv = toolbar.getByRole('link', { name: 'Export CSV' });
  await expect(addComplaint).toBeVisible();
  await expect(exportCsv).toBeVisible();
  await expect(addComplaint).toHaveClass(/icon-btn/);
  await expect(exportCsv).toHaveClass(/icon-btn/);
  await expect(addComplaint.locator('i.fa-plus')).toHaveCount(1);
  await expect(exportCsv.locator('i.fa-download')).toHaveCount(1);
  await expect(addComplaint).not.toContainText('Add Complaint');
  await expect(exportCsv).not.toContainText('Export CSV');
  await expectNoDjangoError(page);
  await diagnostics.assertClean();
});

test('header navigation, profile menu and responsive layouts load', async ({ page }) => {
  const diagnostics = attachPageDiagnostics(page);
  const navTargets = [
    [routes.dashboard, /System Dashboard/i],
    [routes.addComplaint, /Add New Complaint/i],
    [routes.complaints, /Complaint Management/i],
    [routes.vehicles, /Pattern Master/i],
    [routes.sku, /SKU Management/i],
    [routes.master, /Master Settings/i],
    [routes.profile, /Profile Settings/i]
  ] as const;

  for (const [route, heading] of navTargets) {
    await page.goto(route);
    await expect(page.getByRole('heading', { name: heading })).toBeVisible();
    await expectNoDjangoError(page);
  }

  await page.locator('.profile-trigger').hover();
  await expect(page.locator('.profile-dropdown-content').getByText('Profile', { exact: true })).toBeVisible();
  await expect(page.locator('.profile-dropdown-content').getByText('Notifications')).toBeVisible();
  await diagnostics.assertClean();
});

test('HTMX navigation preserves the shell, updates history and returns partial HTML', async ({ page }) => {
  const diagnostics = attachPageDiagnostics(page);
  await page.goto(routes.dashboard);
  const scriptSources = await page.locator('script').evaluateAll((scripts) =>
    scripts.map((script) => (script as HTMLScriptElement).src || '[inline]')
  );
  expect(scriptSources).toContainEqual(expect.stringContaining('/vendor/htmx/'));
  await diagnostics.assertClean();
  await expect.poll(() => page.evaluate(() => Boolean((window as typeof window & { htmx?: unknown }).htmx))).toBe(true);
  await expect(page.locator(`.nav-links a.nav-link[href="${routes.complaints}"]`)).toHaveAttribute('hx-get');
  await page.evaluate(() => {
    (window as typeof window & { __fabroNavbar?: Element }).__fabroNavbar =
      document.querySelector('.navbar') || undefined;
  });

  const partialResponsePromise = page.waitForResponse((response) =>
    response.url().endsWith(routes.complaints)
    && response.request().headers()['hx-request'] === 'true'
  );
  await page.locator(`.nav-links a.nav-link[href="${routes.complaints}"]`).click();
  const partialResponse = await partialResponsePromise;
  const partialHtml = await partialResponse.text();

  await expect(page).toHaveURL(routes.complaints);
  await expect(page.getByRole('heading', { name: /Complaint Management/i })).toBeVisible();
  expect(partialHtml).toContain('id="app-content"');
  expect(partialHtml).toContain('data-fabro-page-head');
  expect(partialHtml).not.toContain('class="navbar"');
  expect(partialHtml).not.toContain('<!DOCTYPE html>');
  expect(await page.evaluate(() =>
    (window as typeof window & { __fabroNavbar?: Element }).__fabroNavbar
      === document.querySelector('.navbar')
  )).toBe(true);
  expect(await page.locator('#app-content form[hx-get], #app-content form[hx-post]').count()).toBe(0);

  await page.locator(`.nav-links a.nav-link[href="${routes.vehicles}"]`).click();
  await expect(page).toHaveURL(routes.vehicles);
  await expect(page.getByRole('heading', { name: /Pattern Master/i })).toBeVisible();
  expect(await page.evaluate(() =>
    (window as typeof window & { __fabroNavbar?: Element }).__fabroNavbar
      === document.querySelector('.navbar')
  )).toBe(true);

  await page.goBack();
  await expect(page).toHaveURL(routes.complaints);
  await expect(page.getByRole('heading', { name: /Complaint Management/i })).toBeVisible();
  await page.goForward();
  await expect(page).toHaveURL(routes.vehicles);
  await expect(page.getByRole('heading', { name: /Pattern Master/i })).toBeVisible();

  await expect(page.locator('.nav-links a.nav-link[href="/chat/"]')).not.toHaveAttribute('hx-get');
  await diagnostics.assertClean();
});

test('every eligible navbar destination uses partial navigation', async ({ page }) => {
  const diagnostics = attachPageDiagnostics(page);
  await page.goto(routes.dashboard);
  await page.evaluate(() => {
    (window as typeof window & { __fabroNavbar?: Element }).__fabroNavbar =
      document.querySelector('.navbar') || undefined;
  });

  const destinations = [
    [routes.addComplaint, /Add New Complaint/i],
    [routes.complaints, /Complaint Management/i],
    [routes.vehicles, /Pattern Master/i],
    [routes.sku, /SKU Management/i],
    [routes.master, /Master Settings/i],
    ['/approvals/', /Approvals Workspace/i],
    [routes.profile, /Profile Settings/i]
  ] as const;

  for (const [route, heading] of destinations) {
    const partialResponse = page.waitForResponse((response) =>
      new URL(response.url()).pathname === route
      && response.request().headers()['hx-request'] === 'true'
    );
    if (route === routes.profile) {
      await page.locator('.profile-trigger').hover();
    }
    await page.locator(`a[href="${route}"]`).first().click();
    await partialResponse;
    await expect(page).toHaveURL(route);
    await expect(page.getByRole('heading', { name: heading })).toBeVisible();
    expect(await page.evaluate(() =>
      (window as typeof window & { __fabroNavbar?: Element }).__fabroNavbar
        === document.querySelector('.navbar')
    )).toBe(true);
  }

  await diagnostics.assertClean();
});

test('HTMX waits for destination CSS before revealing and initializing the page', async ({ page }) => {
  const diagnostics = attachPageDiagnostics(page);
  let releaseStylesheet!: () => void;
  let stylesheetRequested!: () => void;
  const stylesheetGate = new Promise<void>((resolve) => { releaseStylesheet = resolve; });
  const stylesheetRequest = new Promise<void>((resolve) => { stylesheetRequested = resolve; });

  await page.route(/\/static\/management\/css\/dashboard\.css(?:\?.*)?$/, async (route) => {
    stylesheetRequested();
    await stylesheetGate;
    await route.continue();
  });

  await page.goto(routes.addComplaint);
  await page.evaluate(() => {
    const state = window as typeof window & {
      __fabroCallbackAt?: number;
      __fabroReadyAt?: number;
      __fabroQueuePageLoad?: (callback: () => void) => void;
    };
    const originalQueue = state.__fabroQueuePageLoad;
    if (originalQueue) {
      state.__fabroQueuePageLoad = (callback) => originalQueue(() => {
        state.__fabroCallbackAt = performance.now();
        callback();
      });
    }
    document.addEventListener('fabro:page-ready', () => {
      state.__fabroReadyAt = performance.now();
    }, { once: true });
  });

  await page.locator(`.nav-links a.nav-link[href="${routes.dashboard}"]`).click();
  await stylesheetRequest;

  await expect(page.locator('body')).toHaveAttribute('aria-busy', 'true');
  await expect(page.locator('.fabro-page-transition-layer')).toHaveCSS('opacity', '1');
  expect(await page.locator('head style[data-fabro-page-asset]').count()).toBeGreaterThan(0);
  await expect(page.locator('head link[data-fabro-page-asset][href*="dashboard.css"]')).toHaveCount(1);
  expect(await page.evaluate(() =>
    (window as typeof window & { __fabroCallbackAt?: number }).__fabroCallbackAt
  )).toBeUndefined();

  releaseStylesheet();

  await expect(page.getByRole('heading', { name: /System Dashboard/i })).toBeVisible();
  await expect(page.locator('body')).not.toHaveAttribute('aria-busy', 'true');
  await expect(page.locator('.fabro-page-transition-layer')).toHaveCSS('opacity', '0');
  await expect(page.locator('head style[data-fabro-page-asset]')).toHaveCount(0);
  const lifecycleTiming = await page.evaluate(() => {
    const state = window as typeof window & { __fabroCallbackAt?: number; __fabroReadyAt?: number };
    return { callbackAt: state.__fabroCallbackAt, readyAt: state.__fabroReadyAt };
  });
  expect(lifecycleTiming.callbackAt).toBeDefined();
  expect(lifecycleTiming.readyAt).toBeDefined();
  expect(lifecycleTiming.callbackAt!).toBeLessThanOrEqual(lifecycleTiming.readyAt!);
  expect(await page.locator('.dashboard-container').evaluate((element) =>
    getComputedStyle(element).display
  )).toBe('flex');
  await diagnostics.assertClean();
});

test('a failed destination stylesheet recovers with a full page load', async ({ page }) => {
  let stylesheetRequests = 0;
  let dashboardDocumentRequests = 0;

  page.on('request', (request) => {
    if (request.isNavigationRequest() && new URL(request.url()).pathname === routes.dashboard) {
      dashboardDocumentRequests += 1;
    }
  });
  await page.route(/\/static\/management\/css\/dashboard\.css(?:\?.*)?$/, async (route) => {
    stylesheetRequests += 1;
    if (stylesheetRequests === 1) {
      await route.abort('failed');
      return;
    }
    await route.continue();
  });

  await page.goto(routes.addComplaint);
  await page.locator(`.nav-links a.nav-link[href="${routes.dashboard}"]`).click();

  await expect(page).toHaveURL(routes.dashboard);
  await expect(page.getByRole('heading', { name: /System Dashboard/i })).toBeVisible();
  await expect(page.locator('body')).not.toHaveAttribute('aria-busy', 'true');
  expect(stylesheetRequests).toBeGreaterThanOrEqual(2);
  expect(dashboardDocumentRequests).toBeGreaterThanOrEqual(1);
});

test('a slower stale HTMX response cannot replace a newer navigation', async ({ page }) => {
  await page.goto(routes.dashboard);
  await page.route(`**${routes.vehicles}`, async (route) => {
    if (route.request().headers()['hx-request'] === 'true') {
      await new Promise((resolve) => setTimeout(resolve, 900));
    }
    await route.continue();
  });

  await page.evaluate(({ vehicles, complaints }) => {
    (document.querySelector(`.nav-links a[href="${vehicles}"]`) as HTMLAnchorElement).click();
    (document.querySelector(`.nav-links a[href="${complaints}"]`) as HTMLAnchorElement).click();
  }, { vehicles: routes.vehicles, complaints: routes.complaints });

  await expect(page).toHaveURL(routes.complaints);
  await expect(page.getByRole('heading', { name: /Complaint Management/i })).toBeVisible();
  await page.waitForTimeout(1100);
  await expect(page).toHaveURL(routes.complaints);
  await expect(page.getByRole('heading', { name: /Complaint Management/i })).toBeVisible();
  await expect(page.getByRole('heading', { name: /Pattern Master/i })).toHaveCount(0);
});

test('navigation remains stable at desktop, tablet and mobile widths', async ({ page }) => {
  const viewports = [
    { width: 1366, height: 768 },
    { width: 900, height: 1100 },
    { width: 390, height: 844 },
  ];

  for (const viewport of viewports) {
    await page.setViewportSize(viewport);
    await page.goto(routes.addComplaint);
    await page.locator(`a[href="${routes.dashboard}"]`).first().click();
    await expect(page.getByRole('heading', { name: /System Dashboard/i })).toBeVisible();
    await expect(page.locator('body')).not.toHaveAttribute('aria-busy', 'true');
    await expect(page.locator('.fabro-page-transition-layer')).toHaveCSS('opacity', '0');
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
  }
});
