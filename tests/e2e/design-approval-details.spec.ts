import { expect, test } from '@playwright/test';
import { mkdirSync, writeFileSync } from 'fs';
import { join } from 'path';
import { runDjangoCode } from '../helpers/django';
import { workflowUsers } from '../helpers/testData';

const reportDir = join('output', 'design-approval-details-verification');
test.beforeAll(() => {
  mkdirSync(reportDir, { recursive: true });
  // Reuse an existing local image. No upload endpoint or production record is used.
  runDjangoCode(`
from pathlib import Path
from shutil import copyfile
from django.conf import settings
from django.contrib.auth import get_user_model
from management.models import PatternDesignFolder, PatternDesignImage, WorkflowRoles, YearRange
from management.services.design_approvals import submit_design_for_approval
source = settings.BASE_DIR / 'media/pattern_designs/2026/10/test_designer_fix.png'
assert source.is_file(), 'Existing local design image unavailable; browser image verification cannot run.'
target = Path(settings.MEDIA_ROOT) / 'design-details-fixture'
target.mkdir(parents=True, exist_ok=True)
copyfile(source, target / 'existing.png')
copyfile(source, target / 'thumbnail.png')
designer = get_user_model().objects.create_user(username='details_browser_designer')
profile = designer.workflow_profile
profile.role = WorkflowRoles.FREELANCE_3D_DESIGNER
profile.save()
vehicle = YearRange.objects.first()
folder = PatternDesignFolder.objects.create(vehicle=vehicle, name='E2E approval details')
for title in ('E2E details front.png', 'E2E details back.png'):
    image = PatternDesignImage.objects.create(folder=folder, uploaded_by=designer,
        image='design-details-fixture/existing.png', thumbnail='design-details-fixture/thumbnail.png', title=title)
    submit_design_for_approval(image, designer)
`);
});

test('approval details identify the pattern and provide an accessible image-only viewer', async ({ page }) => {
  test.setTimeout(90_000);
  const errors: string[] = [];
  const requests: string[] = [];
  page.on('pageerror', error => errors.push(error.message));
  page.on('console', message => { if (message.type() === 'error') errors.push(`${message.text()} ${message.location().url}`); });
  page.on('request', request => { if (request.url().includes('/design-images/')) requests.push(request.url()); });
  await page.goto('/login/');
  await page.getByLabel('Username').fill(workflowUsers.cad.username);
  await page.getByLabel('Password').fill(workflowUsers.cad.password);
  await page.getByRole('button', { name: /sign in/i }).click();
  await expect(page).not.toHaveURL(/\/login\//);
  const listing = await page.request.get('/api/design-folders/?vehicle_id=1');
  const files = (await listing.json()).design_files as Array<{ id: number; title: string }>;
  const first = files.find(file => file.title === 'E2E details front.png')!;
  const second = files.find(file => file.title === 'E2E details back.png')!;
  expect(first).toBeTruthy(); expect(second).toBeTruthy();
  await page.goto(`/design-approvals/${first.id}/`);
  const identity = page.locator('.design-identity');
  await expect(identity).toContainText('PLAYWRIGHT BRAND PLAYWRIGHT MODEL 2024-2026 PLAYWRIGHT SUB');
  await expect(identity).toContainText('S0001');
  await expect(page.locator('#cadChangeType')).toHaveValue('minor');
  await page.locator('#cadCommentInput').fill('Keep this unsent review intact.');
  const reviewBefore = await page.locator('#cadReviewForm').evaluate((form: HTMLFormElement) => Array.from(new FormData(form).entries()));
  const open = page.getByRole('button', { name: 'Enlarge design image', exact: true });
  const viewer = page.getByRole('dialog', { name: 'E2E details front.png', exact: true });
  const image = page.locator('#designViewerImage');
  const layouts: unknown[] = [];
  for (const width of [320, 375, 768, 1024, 1440, 1920]) {
    await page.setViewportSize({ width, height: width < 768 ? 812 : 1080 });
    for (const light of [false, true]) {
      await page.evaluate(value => document.body.classList.toggle('light-mode', value), light);
      await page.evaluate(() => scrollTo(0, 420));
      const header = await identity.boundingBox();
      const navbar = await page.locator('.navbar').boundingBox();
      expect(header!.y).toBeGreaterThanOrEqual(navbar!.y + navbar!.height - 1);
      expect(await page.evaluate(() => document.documentElement.scrollWidth - innerWidth)).toBeLessThanOrEqual(1);
      await open.scrollIntoViewIfNeeded();
      const beforeScroll = await page.evaluate(() => scrollY);
      await open.click();
      await expect(viewer).toBeVisible();
      await expect.poll(() => image.evaluate((img: HTMLImageElement) => img.complete && img.naturalWidth > 0)).toBe(true);
      const bounds = await viewer.boundingBox();
      expect(bounds!.x).toBeGreaterThanOrEqual(0);
      expect(bounds!.y).toBeGreaterThanOrEqual(0);
      expect(bounds!.x + bounds!.width).toBeLessThanOrEqual(width);
      expect(bounds!.y + bounds!.height).toBeLessThanOrEqual(width < 768 ? 812 : 1080);
      for (const button of await viewer.getByRole('button').all()) {
        const rect = await button.boundingBox();
        expect(rect!.x).toBeGreaterThanOrEqual(bounds!.x);
        expect(rect!.x + rect!.width).toBeLessThanOrEqual(bounds!.x + bounds!.width + 1);
      }
      expect(await page.evaluate(() => document.body.style.position)).toBe('fixed');
      await expect(viewer).not.toContainText(/CAD|MD Review|Minor Change|Review Comments/);
      await viewer.getByRole('button', { name: 'Zoom in', exact: true }).click();
      await expect(page.locator('#designViewerZoom')).toHaveText('125%');
      await viewer.getByRole('button', { name: 'Zoom out', exact: true }).click();
      await expect(page.locator('#designViewerZoom')).toHaveText('100%');
      if ((width === 320 && !light) || (width === 1440 && light)) {
        await page.screenshot({ path: join(reportDir, `viewer-${width}-${light ? 'light' : 'dark'}.png`) });
      }
      await page.keyboard.press('Escape');
      await expect(page.locator('#designImageViewer')).not.toBeVisible();
      expect(await page.evaluate(() => scrollY)).toBe(beforeScroll);
      layouts.push({ width, light, header, bounds });
    }
  }
  // Full-size URLs are loaded on demand; reopening the same image does not reload it.
  expect(requests.filter(url => url.endsWith(`/design-images/${first.id}/download/`))).toHaveLength(1);
  await page.setViewportSize({ width: 320, height: 812 });
  await open.click();
  await viewer.getByRole('button', { name: 'Next image', exact: true }).click();
  await expect(page.locator('#designViewerTitle')).toHaveText('E2E details back.png');
  await expect(image).toHaveAttribute('src', `/design-images/${second.id}/download/`);
  await page.getByRole('button', { name: 'Previous image', exact: true }).click();
  await expect(page.locator('#designViewerTitle')).toHaveText('E2E details front.png');
  for (let n = 0; n < 10; n++) await viewer.getByRole('button', { name: 'Zoom in', exact: true }).click();
  const stage = page.locator('#designViewerStage');
  const box = (await stage.boundingBox())!;
  const cx = box.x + box.width / 2, cy = box.y + box.height / 2;
  await page.mouse.move(cx, cy); await page.mouse.down(); await page.mouse.move(cx + 70, cy + 30, { steps: 4 }); await page.mouse.up();
  expect(await image.evaluate(img => new DOMMatrixReadOnly(getComputedStyle(img).transform).m41)).toBeGreaterThan(0);
  await viewer.getByRole('button', { name: 'Reset zoom', exact: true }).click();
  // Real Chromium touch input exercises pinch handling.
  const cdp = await page.context().newCDPSession(page);
  await cdp.send('Emulation.setTouchEmulationEnabled', { enabled: true });
  await cdp.send('Input.dispatchTouchEvent', { type: 'touchStart', touchPoints: [{ x: cx - 25, y: cy, id: 1 }, { x: cx + 25, y: cy, id: 2 }] });
  await cdp.send('Input.dispatchTouchEvent', { type: 'touchMove', touchPoints: [{ x: cx - 55, y: cy, id: 1 }, { x: cx + 55, y: cy, id: 2 }] });
  await cdp.send('Input.dispatchTouchEvent', { type: 'touchEnd', touchPoints: [] });
  await expect(page.locator('#designViewerZoom')).not.toHaveText('100%');
  await cdp.send('Emulation.setTouchEmulationEnabled', { enabled: false }); await cdp.detach();
  await viewer.getByRole('button', { name: 'Close image viewer' }).click();
  await expect(page.locator('#designImageViewer')).not.toBeVisible();
  expect(await page.locator('#cadReviewForm').evaluate((form: HTMLFormElement) => Array.from(new FormData(form).entries()))).toEqual(reviewBefore);
  await page.setViewportSize({ width: 1440, height: 1080 });
  await page.evaluate(() => scrollTo(0, 0));
  await page.screenshot({ path: join(reportDir, 'details-vehicle-pattern-header.png') });
  expect(errors).toEqual([]);

  // A controlled missing image must show a retry state without closing the viewer.
  await page.route(`**/design-images/${second.id}/download/`, route => route.fulfill({ status: 200, contentType: 'text/plain', body: 'unavailable' }));
  await page.locator(`[data-design-preview="${second.id}"]`).click();
  await expect(page.locator('#designViewerError')).toBeVisible();
  await page.unroute(`**/design-images/${second.id}/download/`);
  await page.getByRole('button', { name: 'Retry', exact: true }).click();
  await expect(page.locator('#designViewerError')).toBeHidden();
  await expect.poll(() => image.evaluate((img: HTMLImageElement) => img.complete && img.naturalWidth > 0)).toBe(true);
  await page.keyboard.press('Escape');
  await expect(page.locator('#designImageViewer')).not.toBeVisible();
  // Page swaps dispose listeners and restore scrolling; history can initialize again.
  await page.getByRole('link', { name: /Approvals Queue/ }).click();
  await expect(page).toHaveURL(/\/design-approvals\/$/);
  await page.goBack();
  await expect(page.locator('.design-identity')).toBeVisible();
  await page.getByRole('button', { name: 'Enlarge design image', exact: true }).click();
  await expect(page.locator('#designImageViewer')).toBeVisible();
  await page.keyboard.press('Escape');
  await expect(page.locator('#designImageViewer')).not.toBeVisible();
  expect(errors).toEqual([]);
  writeFileSync(join(reportDir, 'verification.json'), JSON.stringify({ layouts, errors, requests }, null, 2));
});
