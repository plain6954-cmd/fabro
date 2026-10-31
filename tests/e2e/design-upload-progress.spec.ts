import { expect, test, type Page } from '@playwright/test';
import { readFileSync } from 'fs';
import { runDjangoCode } from '../helpers/django';
import { workflowUsers } from '../helpers/testData';

const source = 'media/pattern_designs/2026/10/test_designer_fix.png';
const image = readFileSync(source);

test.beforeAll(() => {
  runDjangoCode(`
from pathlib import Path
from shutil import copyfile
from django.conf import settings
from django.contrib.auth import get_user_model
from management.models import PatternDesignImage, WorkflowRoles, YearRange
target = Path(settings.MEDIA_ROOT) / 'upload-progress-fixture'
target.mkdir(parents=True, exist_ok=True)
copyfile(settings.BASE_DIR / '${source}', target / 'existing.png')
PatternDesignImage.objects.get_or_create(vehicle=YearRange.objects.first(), title='E2E progress existing.png',
    defaults={'uploaded_by': get_user_model().objects.get(username='fabro_e2e_cad'),
        'image': 'upload-progress-fixture/existing.png', 'thumbnail': 'upload-progress-fixture/existing.png',
        'approval_status': 'approved'})
designer, _ = get_user_model().objects.get_or_create(username='progress_browser_designer')
designer.set_password('FabroWorkflow!234')
designer.save()
profile = designer.workflow_profile
profile.role = WorkflowRoles.FREELANCE_3D_DESIGNER
profile.save()
`);
});

async function openWorkspace(page: Page, credentials = workflowUsers.cad) {
  await page.goto('/login/');
  await page.getByLabel('Username').fill(credentials.username);
  await page.getByLabel('Password').fill(credentials.password);
  await page.getByRole('button', { name: /sign in/i }).click();
  await expect(page).not.toHaveURL(/\/login\//);
  await page.goto('/car-details/?vehicle_id=1#design-options');
  await page.locator('#sidebarNav3DDesignBtn').click();
  await expect(page.locator('#design3DFilesGallery .fabro-design-tile').first()).toBeVisible();
}

test('independent byte progress, server confirmation, stable tiles and safe per-file retries', async ({ page }) => {
  test.setTimeout(90_000);
  // Control transport timing, but save through the real authenticated Django endpoint.
  await page.addInitScript(() => {
    const NativeXHR = window.XMLHttpRequest;
    (window as any).uploadRequests = [];
    class ControlledXHR {
      upload = new NativeXHR().upload;
      headers: Record<string, string> = {};
      url = ''; body: FormData | null = null; status = 0; response: any;
      onload?: () => void; onerror?: () => void; onabort?: () => void; onloadend?: () => void;
      open(_method: string, url: string) { this.url = url; }
      setRequestHeader(name: string, value: string) { this.headers[name] = value; }
      send(body: FormData) { this.body = body; (window as any).uploadRequests.push(this); }
      abort() { this.onabort?.(); this.onloadend?.(); }
      progress(loaded: number, total: number) {
        this.upload.dispatchEvent(new ProgressEvent('progress', { lengthComputable: true, loaded, total }));
        if (loaded === total) this.upload.dispatchEvent(new ProgressEvent('load'));
      }
      async save(loseResponse = false) {
        const response = await fetch(this.url, { method: 'POST', headers: this.headers, body: this.body });
        this.status = response.status;
        this.response = await response.json();
        if (loseResponse) this.onerror?.();
        else this.onload?.();
        this.onloadend?.();
      }
    }
    window.XMLHttpRequest = ControlledXHR as any;
  });
  await openWorkspace(page);
  await page.emulateMedia({ reducedMotion: 'no-preference' });
  const existing = page.locator('.fabro-design-tile', { hasText: 'E2E progress existing.png' });
  await page.locator('#design3DFilesSearch').fill('E2E progress existing');
  await existing.evaluate(el => { (window as any).uploadExistingTile = el; });
  const uploads = page.locator('.fabro-design-tile[data-upload-id]');
  await page.locator('#design3DUploadInput').setInputFiles([
    { name: 'E2E progress response-lost.png', mimeType: 'image/png', buffer: image },
    { name: 'E2E progress preview-retry.png', mimeType: 'image/png', buffer: image },
  ]);
  const first = uploads.filter({ hasText: 'E2E progress response-lost.png' });
  const second = uploads.filter({ hasText: 'E2E progress preview-retry.png' });
  await expect(first.locator('.tile-upload-percent')).toHaveText('0%');
  await expect(second.locator('.tile-upload-percent')).toHaveText('0%');
  const before = await first.boundingBox();
  const mediaBefore = await first.locator('.tile-media-container').boundingBox();
  const layouts: Array<{ width: number; mode: string; tile: { width: number; height: number }; media: { width: number; height: number } }> = [];
  for (const width of [375, 768, 1366]) {
    await page.setViewportSize({ width, height: 900 });
    for (const mode of ['list', 'grid']) {
      await page.locator(mode === 'grid' ? '#design3DGridBtn' : '#design3DListBtn').click();
      layouts.push({ width, mode, tile: (await first.boundingBox())!, media: (await first.locator('.tile-media-container').boundingBox())! });
    }
  }
  await page.evaluate(() => {
    (window as any).handle3DDesignSelected([new File(['duplicate'], 'duplicate.png')]);
    (window as any).uploadRequests[0].progress(250, 1000);
  });
  expect(await page.evaluate(() => (window as any).uploadRequests.length)).toBe(1);
  await expect(first.locator('.tile-upload-percent')).toHaveText('25%');
  await expect(first.locator('[role="progressbar"]')).toHaveAttribute('aria-valuenow', '25');
  await expect(second.locator('.tile-upload-percent')).toHaveText('0%');
  await expect(second.locator('.tile-upload-message')).toHaveText('Queued');
  await expect(page.locator('#btnUpload3DDesigns')).toBeDisabled();
  await page.locator('#design3DListBtn').click();
  expect((await first.locator('.tile-media-container').boundingBox())!.width).toBe(48);
  await page.locator('#design3DGridBtn').click();
  await first.screenshot({ path: 'output/design-upload-progress.png' });
  await page.evaluate(() => (window as any).uploadRequests[0].progress(1000, 1000));
  await expect(first.locator('.tile-upload-percent')).toHaveText('100%');
  await expect(first.locator('.tile-upload-message')).toHaveText('Processing...');
  await expect(first.locator('img')).toHaveCount(0);
  await page.evaluate(() => (window as any).uploadRequests[0].save(true));
  await expect(first.locator('.tile-upload-message')).toContainText('Connection interrupted');
  await expect(first.locator('.tile-upload-retry')).toBeDisabled();
  await expect(second.locator('.tile-upload-percent')).toHaveText('0%');
  // A saved image's preview failure must be retryable without another POST.
  let releaseImage!: () => void;
  const imageGate = new Promise<void>(resolve => { releaseImage = resolve; });
  await page.route('**/media/pattern_design_thumbnails/**', async route => {
    await imageGate;
    await route.abort('failed');
  });
  await page.evaluate(() => {
    (window as any).uploadRequests[1].progress(680, 1000);
  });
  await expect(second.locator('.tile-upload-percent')).toHaveText('68%');
  await expect(first.locator('.tile-upload-percent')).toHaveText('100%');
  await page.evaluate(() => {
    (window as any).uploadRequests[1].progress(1000, 1000);
    return (window as any).uploadRequests[1].save();
  });
  await expect(second.locator('.tile-upload-message')).toHaveText('Loading image...');
  await expect(second.locator('img')).toHaveCount(0);
  releaseImage();
  await expect(second.locator('.tile-upload-message')).toContainText('File saved');
  await page.unroute('**/media/pattern_design_thumbnails/**');
  await second.locator('.tile-upload-retry').click();
  await expect(second.locator('img')).toBeVisible();
  await expect(second).toHaveClass(/is-upload-revealed/);
  await expect(second.locator('img')).toHaveCSS('transition-duration', '0.3s, 0.3s');
  await expect(second.locator('.tile-upload-overlay')).toHaveCount(0);
  expect(await page.evaluate(() => (window as any).uploadRequests.length)).toBe(2);
  await first.locator('.tile-upload-retry').click();
  expect(await page.evaluate(() => (window as any).uploadRequests.length)).toBe(3);
  const requests = await page.evaluate(() => (window as any).uploadRequests.map((request: any) => ({
    uploadId: request.headers['X-Upload-Id'], csrf: request.headers['X-CSRFToken'], filename: request.body.get('images').name,
  })));
  expect(requests[0].uploadId).toBe(requests[2].uploadId);
  expect(requests[0].uploadId).not.toBe(requests[1].uploadId);
  expect(requests[0].csrf).toBeTruthy();
  expect(requests[0].filename).toBe(requests[2].filename);
  await page.evaluate(() => {
    (window as any).uploadRequests[2].progress(1000, 1000);
    return (window as any).uploadRequests[2].save();
  });
  await expect(first.locator('.tile-upload-overlay')).toHaveCount(0);
  await expect(first.locator('img')).toBeVisible();
  const after = await first.boundingBox();
  const mediaAfter = await first.locator('.tile-media-container').boundingBox();
  expect(after!.width).toBe(before!.width);
  expect(after!.height).toBe(before!.height);
  expect(mediaAfter!.height).toBe(mediaBefore!.height);
  expect(await existing.evaluate(el => el === (window as any).uploadExistingTile)).toBe(true);
  await expect(page.locator('#design3DFilesGallery input[type="checkbox"]')).toHaveCount(0);
  await expect(first.locator('.tile-overall-status')).toHaveText('Pending');
  await expect(first.locator('.tile-delete-x-btn')).toHaveCount(0); // CAD upload does not grant delete permission.
  await page.locator('#design3DFilesSearch').fill('E2E progress ');
  await page.locator('#design3DFilesSearch').blur();
  await page.evaluate(() => (window as any).sort3DDesignFiles('name'));
  expect(await page.locator('.fabro-design-tile .tile-title').allTextContents()).toEqual([
    'E2E progress existing.png', 'E2E progress preview-retry.png', 'E2E progress response-lost.png',
  ]);
  for (const layout of layouts) {
    await page.setViewportSize({ width: layout.width, height: 900 });
    await page.locator(layout.mode === 'grid' ? '#design3DGridBtn' : '#design3DListBtn').click();
    const tile = (await first.boundingBox())!, media = (await first.locator('.tile-media-container').boundingBox())!;
    expect({ width: tile.width, height: tile.height }).toEqual({ width: layout.tile.width, height: layout.tile.height });
    expect({ width: media.width, height: media.height }).toEqual({ width: layout.media.width, height: layout.media.height });
  }
  const data = await (await page.request.get('/api/design-folders/?vehicle_id=1')).json();
  const saved = data.design_files.filter((file: any) => file.title.startsWith('E2E progress ') && file.title !== 'E2E progress existing.png');
  expect(saved).toHaveLength(2);
  for (const file of saved) expect(file.cad.status).toBe('skipped_uploader');
  await first.locator('[data-design-image-id]').click();
  await expect(page.locator('#designImageViewer')).toBeVisible();
  await expect(page.locator('#designViewerTitle')).toHaveText('E2E progress response-lost.png');
  await page.keyboard.press('Escape');
  await first.locator('.approval-workflow-tile-btn').click();
  await expect(page.locator('#designApprovalDrawer')).toHaveClass(/is-open/);
  await expect(page.locator('#drawerFileName')).toHaveText('E2E progress response-lost.png');
});

test('native XHR byte progress, reduced motion and server validation remain intact', async ({ page }) => {
  await page.addInitScript(() => {
    (window as any).nativeUploadProgress = [];
    const send = XMLHttpRequest.prototype.send;
    XMLHttpRequest.prototype.send = function (body) {
      this.upload.addEventListener('progress', event => {
        const tile = document.querySelector('.is-upload-pending');
        (window as any).nativeUploadProgress.push({ loaded: event.loaded, total: event.total,
          computable: event.lengthComputable, label: tile?.querySelector('.tile-upload-percent')?.textContent });
      });
      return send.call(this, body);
    };
  });
  await openWorkspace(page, { username: 'progress_browser_designer', password: 'FabroWorkflow!234' });
  await page.emulateMedia({ reducedMotion: 'reduce' });
  await page.locator('#design3DUploadInput').setInputFiles({
    name: 'E2E native progress.png', mimeType: 'image/png', buffer: Buffer.concat([image, Buffer.alloc(1024 * 1024)]),
  });
  const tile = page.locator('.fabro-design-tile[data-upload-id]', { hasText: 'E2E native progress.png' });
  await expect(tile.locator('.tile-upload-overlay')).toHaveCount(0);
  await expect(tile.locator('img')).toBeVisible();
  const events = await page.evaluate(() => (window as any).nativeUploadProgress);
  expect(events.length).toBeGreaterThan(0);
  for (const event of events.filter((event: any) => event.computable)) {
    expect(event.label).toBe(`${Math.floor(event.loaded / event.total * 100)}%`);
  }
  // Reduced motion overrides the upload reveal's 300ms transition.
  await tile.evaluate(el => el.classList.add('is-upload-revealing'));
  expect(await tile.locator('img').evaluate(el => parseFloat(getComputedStyle(el).transitionDuration))).toBeLessThanOrEqual(0.00001);
  await tile.evaluate(el => el.classList.remove('is-upload-revealing'));
  // A later backend status refresh must update a completed upload's normal indicator.
  runDjangoCode(`
from management.models import PatternDesignImage
PatternDesignImage.objects.filter(title='E2E native progress.png').update(approval_status='approved')
`);
  await page.evaluate(() => (window as any).load3DDesignWorkspace(1));
  await expect(tile.locator('.tile-overall-status')).toHaveText('Approved');
  await expect(tile.locator('input[type="checkbox"]')).toHaveCount(0);
  await page.locator('#design3DUploadInput').setInputFiles({ name: 'E2E invalid.exe', mimeType: 'application/octet-stream', buffer: Buffer.from('invalid') });
  const invalid = page.locator('.fabro-design-tile[data-upload-id]', { hasText: 'E2E invalid.exe' });
  await expect(invalid.locator('.tile-upload-message')).toContainText('Unsupported or empty file');
  await expect(invalid.locator('.tile-upload-retry')).toBeEnabled();
  await expect(invalid.locator('img')).toHaveCount(0);
  const data = await (await page.request.get('/api/design-folders/?vehicle_id=1')).json();
  expect(data.design_files.some((file: any) => file.title === 'E2E invalid.exe')).toBe(false);
  page.once('dialog', dialog => dialog.accept());
  await tile.locator('.tile-delete-x-btn').click();
  await expect(tile).toHaveCount(0);
  await page.evaluate(() => (window as any).load3DDesignWorkspace(1));
  await expect(page.locator('.fabro-design-tile', { hasText: 'E2E native progress.png' })).toHaveCount(0);
});
