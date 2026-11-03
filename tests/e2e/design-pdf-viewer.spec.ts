import { expect, test, type Page } from '@playwright/test';
import { readFileSync } from 'fs';
import { runDjangoCode } from '../helpers/django';
import { workflowUsers } from '../helpers/testData';

test.use({ deviceScaleFactor: 2 });
test.beforeAll(() => {
  runDjangoCode(`
from pathlib import Path
from shutil import copyfile
from django.conf import settings
from django.contrib.auth import get_user_model
from management.models import PatternDesignImage, YearRange
from management.tests_design_pdfs import make_pdf
output = settings.BASE_DIR / 'output'
output.mkdir(exist_ok=True)
(output / 'pdf-viewer-fixture.pdf').write_bytes(make_pdf())
target = Path(settings.MEDIA_ROOT) / 'pdf-viewer-fixture'
target.mkdir(parents=True, exist_ok=True)
copyfile(settings.BASE_DIR / 'media/pattern_designs/2026/10/test_designer_fix.png', target / 'existing.png')
PatternDesignImage.objects.get_or_create(vehicle=YearRange.objects.first(), title='E2E PDF sibling image.png',
    defaults={'uploaded_by': get_user_model().objects.get(username='fabro_e2e_cad'),
        'image': 'pdf-viewer-fixture/existing.png', 'thumbnail': 'pdf-viewer-fixture/existing.png', 'approval_status': 'approved'})
`);
});

async function openWorkspace(page: Page) {
  await page.goto('/login/');
  await page.getByLabel('Username').fill(workflowUsers.cad.username);
  await page.getByLabel('Password').fill(workflowUsers.cad.password);
  await page.getByRole('button', { name: /sign in/i }).click();
  await expect(page).not.toHaveURL(/\/login\//);
  await page.goto('/car-details/?vehicle_id=1#design-options');
  await page.locator('#sidebarNav3DDesignBtn').click();
  await expect(page.locator('#design3DFilesGallery')).toBeVisible();
}

test('legacy PDF widget retains upload progress, private delivery and responsive controls', async ({ page }) => {
  test.setTimeout(90_000);
  const errors: string[] = [], libraryRequests: string[] = [];
  page.on('pageerror', error => errors.push(error.message));
  page.on('request', request => { if (request.url().includes('/vendor/pdfjs/')) libraryRequests.push(request.url()); });
  await page.addInitScript(() => {
    const send = XMLHttpRequest.prototype.send;
    (window as any).pdfProgress = [];
    XMLHttpRequest.prototype.send = function (body) {
      if (body instanceof FormData && (body.get('images') as File)?.name === 'E2E uploaded design.pdf') {
        (window as any).pdfInitialProgress = document.querySelector('.tile-upload-percent')?.textContent;
        this.upload.addEventListener('progress', event => {
          (window as any).pdfProgress.push({ loaded: event.loaded, total: event.total,
            percent: document.querySelector('.tile-upload-percent')?.textContent });
        });
        const deliver = this.onload;
        this.onload = event => { (window as any).releasePdfConfirmation = () => deliver?.call(this, event); };
      }
      return send.call(this, body);
    };
    const NativeWorker = Worker;
    (window as any).pdfWorkers = 0;
    (window as any).pdfTerminations = 0;
    window.Worker = class extends NativeWorker {
      constructor(url: string | URL, options?: WorkerOptions) {
        super(url, options); (window as any).pdfWorkers++;
      }
      terminate() { (window as any).pdfTerminations++; super.terminate(); }
    };
  });
  await openWorkspace(page);
  await page.emulateMedia({ reducedMotion: 'no-preference' });
  expect(libraryRequests).toEqual([]);
  await page.locator('#design3DUploadInput').setInputFiles({ name: 'E2E uploaded design.pdf', mimeType: 'application/pdf', buffer: readFileSync('output/pdf-viewer-fixture.pdf') });
  const tile = page.locator('.fabro-design-tile[data-upload-id]', { hasText: 'E2E uploaded design.pdf' });
  expect(await page.evaluate(() => (window as any).pdfInitialProgress)).toBe('0%');
  await expect(tile.locator('.tile-upload-percent')).toHaveText('100%');
  await expect(tile.locator('.tile-upload-message')).toHaveText('Processing...');
  await expect(tile.locator('[data-design-pdf-id]')).toHaveCount(0);
  const before = await tile.boundingBox();
  const mediaBefore = await tile.locator('.tile-media-container').boundingBox();
  const progress = await page.evaluate(() => (window as any).pdfProgress);
  expect(progress.length).toBeGreaterThan(0);
  for (const event of progress) expect(event.percent).toBe(`${Math.floor(event.loaded / event.total * 100)}%`);
  await expect.poll(() => page.evaluate(() => typeof (window as any).releasePdfConfirmation)).toBe('function');
  await page.evaluate(() => (window as any).releasePdfConfirmation());
  const open = tile.locator('[data-design-pdf-id]');
  await expect(open).toBeVisible();
  await expect(tile).toHaveClass(/is-upload-revealed/);
  await expect(tile.locator('.tile-pdf-placeholder')).toHaveCSS('transition-duration', '0.3s, 0.3s');
  await expect(tile.locator('.tile-upload-overlay')).toHaveCount(0);
  const after = await tile.boundingBox();
  expect({ width: after!.width, height: after!.height }).toEqual({ width: before!.width, height: before!.height });
  expect((await open.boundingBox())!.height).toBe(mediaBefore!.height);
  await expect(tile.locator('.fa-file-pdf')).toBeVisible();
  await expect(tile.locator('.tile-overall-status')).toHaveText('Pending');
  await expect(page.locator('#design3DFilesGallery input[type="checkbox"]')).toHaveCount(0);
  await tile.locator('.approval-workflow-tile-btn').click();
  await expect(page.locator('#designApprovalDrawer')).toHaveClass(/is-open/);
  await expect(page.locator('#designPdfViewer')).not.toBeVisible();
  await page.locator('#designApprovalDrawer .drawer-close-btn').click();
  expect(libraryRequests).toEqual([]);

  const viewer = page.locator('#designPdfViewer');
  const canvas = page.locator('#designPdfCanvas');
  // Exercise the retained single-file widget directly; gallery thumbnails now open comparison.
  const openLegacy = async () => {
    const id = await open.getAttribute('data-design-pdf-id');
    await page.evaluate(value => (window as any).openDesignPdfViewer({id: Number(value), title: 'E2E uploaded design.pdf'}, document.querySelector(`[data-design-pdf-id="${value}"]`)), id);
  };
  await openLegacy();
  await expect(viewer).toBeVisible();
  await expect(canvas).toBeVisible();
  await expect(page.locator('#designImageViewer')).not.toBeVisible();
  await expect(page.locator('#designPdfCounter')).toHaveText('1 / 2');
  expect(libraryRequests.some(url => url.includes('pdf.min.mjs'))).toBe(true);
  expect(libraryRequests.some(url => url.includes('pdf.worker.min.mjs'))).toBe(true);
  const pixels = await canvas.evaluate((el: HTMLCanvasElement) => ({
    color: [...el.getContext('2d')!.getImageData(el.width / 2, el.height / 2, 1, 1).data],
    density: el.width / parseFloat(el.style.width),
  }));
  expect(pixels.color).toEqual([0, 153, 0, 255]);
  expect(pixels.density).toBeCloseTo(2, 1);
  await expect(viewer.getByRole('button', { name: 'Previous page', exact: true })).toBeDisabled();
  await viewer.getByRole('button', { name: 'Next page', exact: true }).click();
  await expect(page.locator('#designPdfCounter')).toHaveText('2 / 2');
  await expect(canvas).toBeVisible();
  expect(await canvas.evaluate(el => parseFloat(el.style.width) / parseFloat(el.style.height))).toBeCloseTo(2);
  await page.keyboard.press('Home');
  await expect(page.locator('#designPdfCounter')).toHaveText('1 / 2');
  await expect(canvas).toBeVisible();
  const width = await canvas.evaluate(el => parseFloat(el.style.width));
  await viewer.getByRole('button', { name: 'Zoom PDF in' }).click();
  await expect.poll(() => canvas.evaluate(el => parseFloat(el.style.width))).toBeCloseTo(width * 1.25, 1);
  await viewer.getByRole('button', { name: 'Zoom PDF out' }).click();
  await viewer.getByRole('button', { name: 'Fit to width' }).click();
  await expect.poll(() => canvas.evaluate(el => parseFloat(el.style.width))).toBeCloseTo(width, 1);
  const downloadEvent = page.waitForEvent('download');
  await viewer.getByRole('link', { name: 'Download PDF' }).click();
  expect((await downloadEvent).suggestedFilename()).toBe('E2E uploaded design.pdf');

  for (const viewport of [320, 768, 1366]) {
    await page.setViewportSize({ width: viewport, height: 900 });
    await expect.poll(async () => (await viewer.boundingBox())!.width).toBe(viewport);
    await expect(canvas).toBeVisible();
    await expect.poll(() => canvas.evaluate(el => parseFloat(el.style.width))).toBeCloseTo(viewport - 32, 1);
    for (const button of await viewer.getByRole('button').all()) {
      if (!await button.isVisible()) continue;
      const box = (await button.boundingBox())!;
      expect(box.x).toBeGreaterThanOrEqual(0);
      expect(box.x + box.width).toBeLessThanOrEqual(viewport + 1);
    }
    if (viewport === 320) await viewer.screenshot({ path: 'output/design-pdf-viewer-mobile.png' });
  }
  await page.keyboard.press('Escape');
  await expect(viewer).not.toBeVisible();
  await expect(open).toBeFocused();
  await expect.poll(() => page.evaluate(() => (window as any).pdfWorkers === (window as any).pdfTerminations)).toBe(true);
  await page.locator('#design3DListBtn').click();
  await expect(page.locator('#design3DFilesGallery input[type="checkbox"]')).toHaveCount(0);
  expect((await open.boundingBox())!.width).toBe(48);
  await openLegacy();
  await expect(canvas).toBeVisible();
  await viewer.getByRole('button', { name: 'Close PDF viewer' }).click();
  await expect(viewer).not.toBeVisible();
  const imageTile = page.locator('.fabro-design-tile', { hasText: 'E2E PDF sibling image.png' });
  await imageTile.locator('[data-design-image-id]').click();
  await expect(page.locator('#designComparisonViewer')).toBeVisible();
  await expect(viewer).not.toBeVisible();
  await page.keyboard.press('Escape');
  const id = await open.getAttribute('data-design-pdf-id');
  const pdfResponse = await page.request.get(`/design-images/${id}/download/`);
  expect(pdfResponse.headers()['content-type']).toBe('application/pdf');
  expect((await pdfResponse.body()).subarray(0, 5).toString()).toBe('%PDF-');
  const anonymous = await page.context().browser()!.newContext();
  expect((await anonymous.request.get(new URL(`/design-images/${id}/download/`, page.url()).href, { maxRedirects: 0 })).status()).toBe(302);
  await anonymous.close();
  expect(errors).toEqual([]);
});

test('invalid PDF upload and missing PDF have clear safe error and retry states', async ({ page }) => {
  await openWorkspace(page);
  await page.locator('#design3DUploadInput').setInputFiles({ name: 'E2E invalid document.pdf', mimeType: 'application/pdf', buffer: Buffer.from('<html>not PDF</html>') });
  const invalid = page.locator('.fabro-design-tile[data-upload-id]', { hasText: 'E2E invalid document.pdf' });
  await expect(invalid.locator('.tile-upload-message')).toHaveText('Invalid or damaged PDF file.');
  await expect(invalid.locator('.tile-upload-retry')).toBeEnabled();
  await expect(invalid.locator('[data-design-pdf-id]')).toHaveCount(0);
  await page.evaluate(() => (window as any).openDesignPdfViewer({ id: 2147483647, title: 'Missing PDF.pdf' }, document.getElementById('btnUpload3DDesigns')));
  const viewer = page.locator('#designPdfViewer');
  await expect(page.locator('#designPdfError')).toBeVisible();
  await expect(page.locator('#designPdfCanvas')).not.toBeVisible();
  await expect(page.locator('#designPdfDownload')).not.toBeVisible();
  await viewer.getByRole('button', { name: 'Retry', exact: true }).click();
  await expect(page.locator('#designPdfError')).toBeVisible();
  await viewer.getByRole('button', { name: 'Close PDF viewer' }).click();
  await expect(viewer).not.toBeVisible();
  expect(await page.evaluate(() => document.body.style.position)).not.toBe('fixed');
});
