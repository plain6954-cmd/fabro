import { expect, test, type Browser, type Page } from '@playwright/test';
import { readFileSync } from 'fs';
import { runDjangoCode } from '../helpers/django';
import { workflowUsers } from '../helpers/testData';

test.beforeAll(() => {
  runDjangoCode(`
from pathlib import Path
from shutil import copyfile
from django.conf import settings
from django.contrib.auth import get_user_model
from management.models import ApprovalRoles, PatternDesignImage, WorkflowRoles, YearRange
from management.tests_design_pdfs import make_pdf
output = settings.BASE_DIR / 'output'
output.mkdir(exist_ok=True)
(output / 'gallery-sync-fixture.pdf').write_bytes(make_pdf())
target = Path(settings.MEDIA_ROOT) / 'gallery-sync-fixture'
target.mkdir(parents=True, exist_ok=True)
copyfile(settings.BASE_DIR / 'media/pattern_designs/2026/10/test_designer_fix.png', target / 'existing.png')
PatternDesignImage.objects.get_or_create(vehicle=YearRange.objects.first(), title='E2E sync existing.png',
    defaults={'uploaded_by': get_user_model().objects.get(username='fabro_e2e_cad'),
        'image': 'gallery-sync-fixture/existing.png', 'thumbnail': 'gallery-sync-fixture/existing.png', 'approval_status': 'approved'})
md, _ = get_user_model().objects.get_or_create(username='sync_browser_md')
md.set_password('FabroWorkflow!234')
md.save()
profile = md.workflow_profile
profile.role, profile.approval_role = WorkflowRoles.APPROVER, ApprovalRoles.MD
profile.save()
`);
});

async function signIn(browser: Browser, user: { username: string; password: string }, gallery = true) {
  const context = await browser.newContext({ viewport: { width: 1366, height: 900 }, reducedMotion: 'reduce' });
  const page = await context.newPage();
  await page.goto('/login/');
  await page.getByLabel('Username').fill(user.username);
  await page.getByLabel('Password').fill(user.password);
  await page.getByRole('button', { name: /sign in/i }).click();
  await expect(page).not.toHaveURL(/\/login\//);
  if (gallery) {
    await page.goto('/car-details/?vehicle_id=1#design-options');
    await page.locator('#sidebarNav3DDesignBtn').click();
    await expect(page.locator('#design3DFilesGallery .fabro-design-tile').first()).toBeVisible();
  }
  return page;
}

async function csrf(page: Page) {
  return (await page.context().cookies()).find(cookie => cookie.name === 'csrftoken')!.value;
}

async function upload(page: Page, name: string, mimeType: string, buffer: Buffer, id: string) {
  const response = await page.request.post('/api/vehicles/1/design-images/upload/', {
    headers: { 'X-CSRFToken': await csrf(page), 'X-Upload-Id': id },
    multipart: { is_reference: '0', images: { name, mimeType, buffer } },
  });
  expect(response.status()).toBe(200);
  return (await response.json()).images[0];
}

async function decide(page: Page, id: number, stage: string, rejected = false) {
  const response = await page.request.post(`/api/design-images/${id}/${rejected ? 'reject' : 'approve'}/`, {
    headers: { 'X-CSRFToken': await csrf(page) },
    data: { stage, change_type: 'major', comment: rejected ? 'Revise this design' : 'Sync verification' },
  });
  expect(response.status()).toBe(200);
}

test('three users see image/PDF uploads and approval changes without refresh or interrupted work', async ({ browser }) => {
  test.setTimeout(150_000);
  const actor = await signIn(browser, workflowUsers.cad);
  const observer = await signIn(browser, workflowUsers.ed);
  const reviewer = await signIn(browser, { username: 'sync_browser_md', password: 'FabroWorkflow!234' }, false);
  try {
    const errors: string[] = [], metadataRequests: string[] = [], checks: number[] = [];
    let reloads = 0, fullDownloads = 0;
    observer.on('pageerror', error => errors.push(error.message));
    observer.on('framenavigated', frame => { if (frame === observer.mainFrame()) reloads++; });
    observer.on('request', request => {
      const url = new URL(request.url());
      if (url.pathname !== '/api/design-folders/') return;
      if (url.searchParams.has('files')) metadataRequests.push(url.searchParams.get('files')!);
      else if (!url.searchParams.has('gallery_sync')) fullDownloads++;
    });
    observer.on('response', response => {
      const url = new URL(response.url());
      if (url.searchParams.get('gallery_sync') === '1' && !url.searchParams.has('files')) checks.push(response.status());
    });
    await observer.emulateMedia({ reducedMotion: 'no-preference' });
    await observer.locator('#design3DFilesSearch').fill('E2E sync ');
    await observer.locator('#pattern3DDesignWorkspace .design-sort-select').selectOption('name');
    await observer.locator('#design3DListBtn').click();
    const existing = observer.locator('.fabro-design-tile', { hasText: 'E2E sync existing.png' });
    await existing.evaluate(el => { (window as any).syncExistingTile = el; });
    await observer.evaluate(() => {
      (window as any).syncAnimations = [];
      new MutationObserver(records => {
        for (const record of records) for (const node of Array.from(record.addedNodes)) {
          if (node instanceof HTMLElement && node.classList.contains('is-gallery-added')) {
            (window as any).syncAnimations.push(getComputedStyle(node).animationDuration);
          }
        }
      }).observe(document.getElementById('design3DFilesGallery')!, { childList: true });
    });
    const originalUrl = observer.url();
    const beforeScroll = await observer.evaluate(() => ({ x: scrollX, y: scrollY }));
    const image = await upload(actor, 'E2E sync incoming.png', 'image/png', readFileSync('media/pattern_designs/2026/10/test_designer_fix.png'), 'sync-browser-image');
    const imageTile = observer.locator(`.fabro-design-tile[data-file-id="${image.id}"]`);
    await expect(imageTile).toHaveCount(1, { timeout: 20_000 });
    expect(await observer.evaluate(() => ({ x: scrollX, y: scrollY }))).toEqual(beforeScroll);
    expect(await existing.evaluate(el => el === (window as any).syncExistingTile)).toBe(true);
    await expect(observer.locator('#design3DFilesGallery input[type="checkbox"]')).toHaveCount(0);
    await expect(observer.locator('#design3DFilesGallery')).toHaveClass(/view-list/);
    await expect(observer.locator('#design3DFilesSearch')).toHaveValue('E2E sync ');
    await expect(observer.locator('#pattern3DDesignWorkspace .design-sort-select')).toHaveValue('name');
    const imageOpen = imageTile.locator('[data-design-image-id]');
    await imageOpen.evaluate(el => { (window as any).syncImageOpener = el; });
    // Retained legacy widget regression; actual thumbnail comparison is covered separately.
    await imageOpen.evaluate((el, file) => (window as any).openDesignImageViewer([{id:file.id,title:file.title,url:`/design-images/${file.id}/download/`}],file.id,el), image);
    const imageViewer = observer.locator('#designImageViewer');
    await expect(imageViewer).toBeVisible();
    await imageViewer.getByRole('button', { name: 'Zoom in', exact: true }).click();
    await decide(reviewer, image.id, 'md');
    await expect(imageTile.locator('.approver-dot-badge[title="MD: APPROVED"]')).toHaveCount(1, { timeout: 20_000 });
    await expect(imageViewer).toBeVisible();
    await expect(observer.locator('#designViewerZoom')).toHaveText('125%');
    await observer.keyboard.press('Escape');
    await expect(imageOpen).toBeFocused();
    expect(await imageOpen.evaluate(el => el === (window as any).syncImageOpener)).toBe(true);
    await expect(imageTile.locator('input[type="checkbox"]')).toHaveCount(0);
    await imageTile.locator('.approval-workflow-tile-btn').click();
    const draft = observer.locator('#designDrawerDecisionRemarks');
    await draft.fill('Unsaved sync draft');
    await observer.locator('input[name="drawerChangeType"][value="major"]').check();
    await decide(observer, image.id, 'ed');
    await expect(imageTile.locator('.tile-overall-status')).toHaveText('Approved', { timeout: 20_000 });
    await expect(imageTile.locator('.tile-overall-status')).toHaveCSS('background-color', 'rgb(22, 163, 74)');
    await expect(actor.locator(`.fabro-design-tile[data-file-id="${image.id}"] .tile-overall-status`)).toHaveText('Approved', { timeout: 20_000 });
    await expect(observer.locator('#designApprovalDrawer')).toHaveClass(/is-open/);
    await expect(draft).toHaveValue('Unsaved sync draft');
    await expect(observer.locator('input[name="drawerChangeType"][value="major"]')).toBeChecked();
    await expect(observer.locator('#drawerFileSelector')).toHaveValue(String(image.id));
    await observer.locator('#designApprovalDrawer .drawer-close-btn').click();

    await observer.locator('#design3DGridBtn').click();
    const pdf = await upload(actor, 'E2E sync incoming.pdf', 'application/pdf', readFileSync('output/gallery-sync-fixture.pdf'), 'sync-browser-pdf');
    const pdfTile = observer.locator(`.fabro-design-tile[data-file-id="${pdf.id}"]`);
    await expect(pdfTile).toHaveCount(1, { timeout: 20_000 });
    await pdfTile.locator('[data-design-pdf-id]').evaluate((el, file) => (window as any).openDesignPdfViewer({id:file.id,title:file.title},el), pdf);
    await expect(observer.locator('#designPdfCanvas')).toBeVisible();
    await observer.locator('#designPdfViewer').getByRole('button', { name: 'Zoom PDF in' }).click();
    await expect(observer.locator('#designPdfZoom')).toHaveText('125%');
    await decide(reviewer, pdf.id, 'md', true);
    await expect(pdfTile.locator('.tile-overall-status')).toHaveText('Rejected', { timeout: 20_000 });
    await expect(pdfTile.locator('.tile-overall-status')).toHaveCSS('background-color', 'rgb(220, 38, 38)');
    await expect(observer.locator('#designPdfViewer')).toBeVisible();
    await expect(observer.locator('#designPdfZoom')).toHaveText('125%');
    await expect(observer.locator('#designPdfCounter')).toHaveText('1 / 2');
    await observer.keyboard.press('Escape');
    await expect(pdfTile.locator('[data-design-pdf-id]')).toBeFocused();
    const titles = await observer.locator('#design3DFilesGallery .tile-title').allTextContents();
    expect(titles).toEqual([...titles].sort((a, b) => a.localeCompare(b)));
    expect(await observer.evaluate(() => (window as any).syncAnimations)).toContain('0.28s');
    expect(observer.url()).toBe(originalUrl);
    expect(reloads).toBe(0);
    expect(fullDownloads).toBe(0);
    expect(metadataRequests.length).toBeGreaterThanOrEqual(4);
    expect(metadataRequests.every(ids => ids === String(image.id) || ids === String(pdf.id))).toBe(true);
    const metadataCount = metadataRequests.length;
    await expect.poll(() => checks.includes(304), { timeout: 15_000 }).toBe(true);
    expect(metadataRequests.length).toBe(metadataCount);
    await expect(imageTile).toHaveCount(1);
    await expect(pdfTile).toHaveCount(1);
    expect(errors).toEqual([]);

    // A hidden workspace stops checks; reopening it checks immediately.
    await observer.evaluate(() => (window as any).switchSidebarSection('measurements'));
    await expect(observer.locator('#pattern3DDesignWorkspace')).not.toBeVisible();
    await observer.waitForTimeout(500); // Let any request already in flight settle.
    const hiddenChecks = checks.length;
    await observer.waitForTimeout(11_000);
    expect(checks.length).toBe(hiddenChecks);
    await observer.locator('#sidebarNav3DDesignBtn').click();
    await expect.poll(() => checks.length, { timeout: 3000 }).toBeGreaterThan(hiddenChecks);
  } finally {
    await Promise.all([actor.context().close(), observer.context().close(), reviewer.context().close()]);
  }
});
