import { expect, test } from '@playwright/test';
import { login, loginAs } from '../helpers/auth';
import { runDjangoCode } from '../helpers/django';
import { workflowUsers } from '../helpers/testData';

const endpoint = '/admin-panel/control-tower/';
test.beforeAll(() => {
  runDjangoCode(`
from datetime import timedelta
from django.contrib.auth import get_user_model
from django.utils import timezone
from management.models import PatternDesignImage, PatternDesignApproval, ActivityLog, YearRange
PatternDesignImage.objects.filter(title__startswith='CT browser ').delete()
actor = get_user_model().objects.get(username='fabro_e2e_cad')
for index in range(14):
    image = PatternDesignImage.objects.create(vehicle=YearRange.objects.first(), title=f'CT browser {index}',
        image='isolated-control-tower.png', uploaded_by=actor)
    review = PatternDesignApproval.objects.create(design_image=image, designer=actor,
        cycle=2 if index == 0 else 1, cad_status='skipped_uploader')
    PatternDesignApproval.objects.filter(pk=review.pk).update(submitted_at=timezone.now()-timedelta(hours=60 if index==1 else index))
ActivityLog.objects.create(user=actor, action='resubmitted', object_type='Design Image', object_name='CT browser recorded resubmission')
`);
});

test('current database counts, bounded queue, recorded activity and exact review navigation', async ({ page }) => {
  const errors: string[] = [];
  page.on('pageerror', error => errors.push(error.message));
  await login(page);
  await page.goto('/admin_panel/');
  await expect(page.locator('.erp-stat-tile')).toHaveCount(6);
  const response = await page.request.get(endpoint);
  expect(response.status()).toBe(200);
  const data = await response.json();
  for (const name of ['pending', 'delayed', 'revisions']) {
    await expect(page.locator(`[data-ct-count="${name}"]`)).toHaveText(String(data.counts[name]));
  }
  expect(data.counts.pending).toBe(28);
  await expect(page.locator('[data-ct-design]')).toHaveCount(12);
  await expect(page.locator('[data-ct-event]')).toHaveCount(15);
  await expect(page.locator('[data-ct-fragment="activity"]')).toContainText('CT browser recorded resubmission');
  await expect(page.locator('[data-ct-design]').first()).toContainText('CT browser 1');
  const href = await page.locator('[data-ct-design] .ct-action').first().getAttribute('href');
  await page.locator('[data-ct-design] .ct-action').first().click();
  await expect(page).toHaveURL(href!);
  await expect(page.locator('.design-review-page')).toBeVisible();
  expect(errors).toEqual([]);
});

test('thirty-second updates keep document, focused links, queue scroll and session forms intact', async ({ page }) => {
  await login(page);
  await page.clock.install();
  await page.goto('/admin_panel/');
  await page.clock.pauseAt(await page.evaluate(() => Date.now() + 1000));
  const link = page.locator('[data-ct-design] .ct-action').first();
  await link.focus();
  await page.evaluate(() => {
    (window as any).__ctDocument = document;
    (window as any).__ctFocused = document.activeElement;
    (window as any).__ctSessions = document.querySelector('.ct-session-panel');
    document.querySelector('.ct-queue-list')!.scrollTop = 60;
  });
  const before = Number(await page.locator('[data-ct-count="pending"]').innerText());
  runDjangoCode(`
from datetime import timedelta
from django.contrib.auth import get_user_model
from django.utils import timezone
from management.models import PatternDesignImage, PatternDesignApproval
actor=get_user_model().objects.get(username='fabro_e2e_cad')
image=PatternDesignImage.objects.create(title='CT browser live', image='isolated.png', uploaded_by=actor)
review=PatternDesignApproval.objects.create(design_image=image, designer=actor)
PatternDesignApproval.objects.filter(pk=review.pk).update(submitted_at=timezone.now()-timedelta(hours=80))
`);
  try {
    const updated = page.waitForResponse(response => response.url().endsWith(endpoint));
    await page.clock.runFor(30010);
    await updated;
    await expect(page.locator('[data-ct-count="pending"]')).toHaveText(String(before + 3));
    expect(await page.evaluate(() => (window as any).__ctDocument === document &&
      (window as any).__ctFocused === document.activeElement &&
      (window as any).__ctSessions === document.querySelector('.ct-session-panel'))).toBe(true);
    expect(await page.locator('.ct-queue-list').evaluate(element => element.scrollTop)).toBe(60);
    await expect(page.locator('[data-ct-fragment="attention"]')).not.toContainText('CT browser live');
    await page.locator('[data-ct-refresh]').focus();
    await expect(page.locator('[data-ct-fragment="attention"]')).toContainText('CT browser live');
    await expect(page.locator('[data-ct-updated]')).toHaveAttribute('datetime', /T/);
  } finally {
    runDjangoCode("from management.models import PatternDesignImage; PatternDesignImage.objects.filter(title='CT browser live').delete()");
  }
});

test('focus bursts do not overlap; hidden and inactive dashboards pause; removal cleans up', async ({ page }) => {
  await login(page);
  await page.clock.install();
  await page.goto('/admin_panel/');
  await page.clock.pauseAt(await page.evaluate(() => Date.now() + 1000));
  const payload = await (await page.request.get(endpoint)).json();
  let requests = 0, release: (() => void) | undefined;
  await page.route(`**${endpoint}`, async route => {
    requests++;
    await new Promise<void>(resolve => { release = resolve; });
    await route.fulfill({ json: payload });
  });
  await page.evaluate(() => { for (let i = 0; i < 8; i++) window.dispatchEvent(new Event('focus')); });
  await page.clock.runFor(1);
  await expect.poll(() => requests).toBe(1);
  await page.evaluate(() => { for (let i = 0; i < 8; i++) window.dispatchEvent(new Event('focus')); });
  await page.clock.runFor(90000);
  expect(requests).toBe(1);
  const released = page.waitForResponse(response => response.url().endsWith(endpoint));
  release!();
  await released;
  await page.evaluate(() => {
    Object.defineProperty(document, 'hidden', { configurable: true, value: true });
    document.dispatchEvent(new Event('visibilitychange'));
  });
  await page.clock.runFor(90000);
  expect(requests).toBe(1);
  await page.locator('#side-users').click();
  await page.evaluate(() => {
    Object.defineProperty(document, 'hidden', { configurable: true, value: false });
    document.dispatchEvent(new Event('visibilitychange'));
  });
  await page.clock.runFor(90000);
  expect(requests).toBe(1);
  await page.evaluate(() => document.getElementById('fabroControlTower')!.remove());
  await expect.poll(() => page.evaluate(() => !(window as any).__fabroControlTower)).toBe(true);
  await page.clock.runFor(90000);
  expect(requests).toBe(1);
});

test('failed refresh retains data and auth loss stops further polling', async ({ page }) => {
  await login(page);
  await page.clock.install();
  await page.goto('/admin_panel/');
  await page.clock.pauseAt(await page.evaluate(() => Date.now() + 1000));
  let calls = 0;
  await page.route(`**${endpoint}`, route => { calls++; return route.fulfill({ status: calls === 1 ? 503 : 403, body: '' }); });
  await page.locator('[data-ct-refresh]').click();
  await page.clock.runFor(1);
  await expect(page.locator('[data-ct-error]')).toContainText('Retrying automatically');
  await expect(page.locator('[data-ct-count="pending"]')).toHaveText('28');
  await page.clock.runFor(60010);
  await expect(page.locator('[data-ct-error]')).toContainText('Access changed');
  await page.clock.runFor(120000);
  expect(calls).toBe(2);
});

test('CAD cannot read admin metrics through a direct request', async ({ page }) => {
  await loginAs(page, workflowUsers.cad);
  expect((await page.request.get(endpoint)).status()).toBe(403);
});

test('desktop tablet and mobile layout retains six cards and compact usable controls', async ({ page }) => {
  await login(page);
  await page.goto('/admin_panel/');
  for (const width of [1366, 1024, 768, 390]) {
    await page.setViewportSize({ width, height: 844 });
    await page.locator('#fabroControlTower').scrollIntoViewIfNeeded();
    const dimensions = await page.evaluate(() => {
      const pane = document.querySelector('.erp-dashboard-pane')!;
      const session = document.querySelector('.ct-session-panel')!.getBoundingClientRect();
      return { pageOverflow: document.documentElement.scrollWidth - innerWidth,
        paneOverflow: pane.scrollWidth - pane.clientWidth, sessionHeight: session.height };
    });
    expect(dimensions.pageOverflow, `page at ${width}`).toBeLessThanOrEqual(1);
    expect(dimensions.paneOverflow, `dashboard at ${width}`).toBeLessThanOrEqual(1);
    expect(dimensions.sessionHeight).toBeLessThan(400);
    if (width >= 1024) {
      const a = await page.locator('[data-ct-fragment="pipeline"]').boundingBox();
      const b = await page.locator('[data-ct-fragment="attention"]').boundingBox();
      expect(Math.abs(a!.y - b!.y)).toBeLessThan(1);
      expect(a!.x + a!.width).toBeLessThan(b!.x);
    }
    if (width === 1366 || width === 390) {
      await page.screenshot({path: `output/control-tower-${width === 390 ? 'mobile' : 'desktop'}.png`});
    }
    if (width === 390) {
      expect((await page.locator('.ct-action').first().boundingBox())!.height).toBeGreaterThanOrEqual(40);
    }
  }
});

test('existing Kick and Terminate Others forms keep current session and confirmations', async ({ page, browser }) => {
  await login(page);
  const otherContext = await browser.newContext();
  const other = await otherContext.newPage();
  try {
    await login(other);
    await page.goto('/admin_panel/');
    const panel = page.locator('.ct-session-panel');
    await expect(panel).toContainText('CURRENT');
    const otherSession = (await otherContext.cookies()).find(cookie => cookie.name === 'sessionid')!.value;
    const target = panel.locator(`form[action*="${otherSession}"]`).getByRole('button', { name: 'Kick', exact: true });
    page.once('dialog', dialog => { expect(dialog.message()).toContain('Kick'); return dialog.accept(); });
    await target.click();
    await expect(page).toHaveURL(/admin_panel/);
    expect((await other.request.get(endpoint)).url()).toContain('/login/');
    await login(other);
    await page.goto('/admin_panel/');
    page.once('dialog', dialog => { expect(dialog.message()).toContain('Terminate all other'); return dialog.accept(); });
    await page.locator('.ct-session-panel').getByRole('button', { name: 'Terminate Others' }).click();
    await expect(page).toHaveURL(/admin_panel/);
    await expect(page.locator('.ct-session-panel')).toContainText('CURRENT');
    await expect(page.locator('.ct-session-panel').getByRole('button', { name: 'Kick', exact: true })).toHaveCount(0);
    expect((await other.request.get(endpoint)).url()).toContain('/login/');
    expect((await page.request.get(endpoint)).status()).toBe(200);
  } finally { await otherContext.close(); }
});
