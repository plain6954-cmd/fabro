import { expect, test } from '@playwright/test';
import { mkdirSync, writeFileSync } from 'fs';
import { join } from 'path';
import { login } from '../helpers/auth';
import { runDjangoCode } from '../helpers/django';
import { routes } from '../helpers/testData';

const evidenceDir = join('output', 'codex-full-debug', 'screenshots');
const sizes = [
  [2560, 1440], [1920, 1080], [1648, 928], [1536, 864],
  [1366, 768], [1280, 720], [1024, 768], [820, 1180],
  [768, 1024], [430, 932], [390, 844], [375, 812],
  [360, 800], [320, 568], [568, 320],
] as const;

test.beforeAll(() => {
  mkdirSync(evidenceDir, { recursive: true });
  // Metadata-only fixtures in the disposable E2E database; no media file is created or uploaded.
  runDjangoCode(`
from django.contrib.auth import get_user_model
from django.utils import timezone
from management.models import PatternDesignImage, UserProfile, WorkflowRoles, YearRange
User = get_user_model()
designer, _ = User.objects.get_or_create(username='fabro_e2e_designer')
designer.set_password('FabroWorkflow!234')
designer.save()
profile, _ = UserProfile.objects.get_or_create(user=designer)
profile.role = WorkflowRoles.FREELANCE_3D_DESIGNER
profile.save()
vehicle = YearRange.objects.first()
for status in ('approved', 'rejected'):
    PatternDesignImage.objects.get_or_create(
        vehicle=vehicle, title='E2E ' + status + ' design.obj',
        defaults={
            'image': 'pattern_designs/e2e-' + status + '.obj',
            'uploaded_by': designer,
            'approval_status': status,
            'completed_at': timezone.now(),
            'approved_at': timezone.now() if status == 'approved' else None,
            'rejected_at': timezone.now() if status == 'rejected' else None,
            'rejection_reason': 'Revision required' if status == 'rejected' else '',
        },
    )
`);
});

test('3D design gallery and controls fit required viewport widths', async ({ page }) => {
  test.setTimeout(180_000);
  await login(page);
  await page.goto(`${routes.vehicles}?vehicle_id=1#design-options`);
  await page.locator('#sidebarNav3DDesignBtn').click();
  await expect(page.locator('#pattern3DDesignWorkspace')).toBeVisible();
  await expect(page.locator('.fabro-design-tile', { hasText: 'E2E approved design.obj' })).toHaveCount(1);
  await expect(page.locator('.fabro-design-tile', { hasText: 'E2E rejected design.obj' })).toHaveCount(1);
  await expect(page.locator('#refImagesCountBadge')).toHaveText('0');
  await expect(page.locator('#refImagesEmptyState')).toBeVisible();
  const results: Array<Record<string, unknown>> = [];
  for (const [width, height] of sizes) {
    await page.setViewportSize({ width, height });
    for (const view of ['grid', 'list'] as const) {
      await page.locator(view === 'grid' ? '#design3DGridBtn' : '#design3DListBtn').click();
      const metrics = await page.evaluate(() => {
        const controls = document.querySelector('#pattern3DDesignWorkspace .design-files-controls-bar')?.getBoundingClientRect();
        const search = document.querySelector('#design3DFilesSearch')?.getBoundingClientRect();
        const drawer = document.querySelector('#designApprovalDrawer')?.getBoundingClientRect();
        return {
          documentWidth: document.documentElement.scrollWidth,
          viewportWidth: innerWidth,
          controlsRight: controls?.right,
          searchWidth: search?.width,
          drawerWidth: drawer?.width,
          tileCount: document.querySelectorAll('.fabro-design-tile').length,
        };
      });
      results.push({ width, height, view, ...metrics });
      if ([2560, 1366, 820, 390, 320].includes(width) && view === 'grid') {
        await page.screenshot({ path: join(evidenceDir, `3d-design-${width}x${height}.png`), fullPage: width >= 820 });
      }
    }
  }
  writeFileSync(join('output', 'codex-full-debug', 'pattern-design-layout.json'), JSON.stringify(results, null, 2));
  expect(results.filter((result) => Number(result.documentWidth) > Number(result.viewportWidth) + 1)).toEqual([]);
  expect(results.filter((result) => Number(result.controlsRight) > Number(result.viewportWidth) + 1)).toEqual([]);
  expect(results.filter((result) => Number(result.searchWidth) < 80)).toEqual([]);
});

test('designer controls are role scoped and approval drawer works without uploads', async ({ page }) => {
  await login(page);
  await page.goto(`${routes.vehicles}?vehicle_id=1#design-options`);
  await page.locator('#sidebarNav3DDesignBtn').click();
  await expect(page.locator('#designerWorkflowPanelCol')).toHaveCount(0);
  await page.locator('#btnOpenTopApprovalWorkflow').click();
  await expect(page.locator('#designApprovalDrawer')).toHaveClass(/is-open/);
  await page.screenshot({ path: join(evidenceDir, '3d-approval-drawer-desktop.png'), fullPage: true });
  await page.locator('#designApprovalDrawer .drawer-close-btn').click();
  await expect(page.locator('#designApprovalDrawer')).not.toHaveClass(/is-open/);
  await page.context().clearCookies();
  await page.goto(routes.login);
  await page.getByLabel('Username').fill('fabro_e2e_designer');
  await page.getByLabel('Password').fill('FabroWorkflow!234');
  await page.getByRole('button', { name: /sign in/i }).click();
  await expect(page).not.toHaveURL(/\/login\//);
  await page.goto(`${routes.vehicles}?vehicle_id=1#design-options`);
  await page.locator('#sidebarNav3DDesignBtn').click();
  await expect(page.locator('#designerWorkflowPanelCol')).toBeVisible();
  await page.screenshot({ path: join(evidenceDir, '3d-design-designer-desktop.png'), fullPage: true });
});

test('reference gallery scrolls and previews existing image metadata', async ({ page }) => {
  // Metadata-only records: the browser neither selects nor uploads any file.
  runDjangoCode(`
from django.contrib.auth import get_user_model
from management.models import PatternDesignImage, YearRange
designer = get_user_model().objects.get(username='fabro_e2e_designer')
vehicle = YearRange.objects.first()
for index in range(5):
    PatternDesignImage.objects.get_or_create(
        vehicle=vehicle, title=f'E2E reference {index + 1}.png',
        defaults={'image': f'pattern_designs/e2e-reference-{index + 1}.png', 'uploaded_by': designer, 'file_size': 1024, 'is_reference': True},
    )
`);
  await login(page);
  await page.goto(`${routes.vehicles}?vehicle_id=1#design-options`);
  await page.locator('#sidebarNav3DDesignBtn').click();
  await expect(page.locator('#refImagesScrollTrack .ref-image-card')).toHaveCount(5);
  const rejectedStyling = await page.locator('.fabro-design-tile.is-rejected').first().evaluate((tile) => ({
    thumbnailOpacity: Number(getComputedStyle(tile.querySelector('.tile-media-container > *')!).opacity),
    filenameOpacity: Number(getComputedStyle(tile.querySelector('.tile-title')!).opacity),
  }));
  expect(rejectedStyling.thumbnailOpacity).toBeLessThanOrEqual(0.5);
  expect(rejectedStyling.filenameOpacity).toBe(1);
  await page.locator('.fabro-design-tile.is-approved').first().screenshot({ path: join(evidenceDir, 'approved-design-tile.png') });
  await page.locator('.fabro-design-tile.is-rejected').first().screenshot({ path: join(evidenceDir, 'rejected-design-tile.png') });
  await expect(page.locator('#btnUploadRefImages')).toHaveCount(1);
  await expect(page.locator('#refScrollNext')).toBeVisible();
  const threeFit = await page.evaluate(() => {
    const trackRect = document.getElementById('refImagesScrollTrack')?.getBoundingClientRect();
    const thirdRect = document.querySelectorAll('#refImagesScrollTrack .ref-image-card')[2]?.getBoundingClientRect();
    return Boolean(trackRect && thirdRect && thirdRect.right <= trackRect.right + 1);
  });
  expect(threeFit).toBe(true);
  await page.screenshot({ path: join(evidenceDir, 'reference-gallery-five-images.png') });
  const track = page.locator('#refImagesScrollTrack');
  await page.locator('#refScrollNext').click();
  await expect.poll(() => track.evaluate((element) => element.scrollLeft)).toBeGreaterThan(0);
  await track.hover();
  await page.mouse.wheel(280, 0);
  await expect.poll(() => track.evaluate((element) => element.scrollLeft)).toBeGreaterThan(0);
  await page.locator('#refImagesScrollTrack .ref-image-card').first().click();
  await expect(page.locator('#interiorMediaPreviewModal')).toBeVisible();
  await expect(page.locator('#interiorMediaPreviewContainer')).toContainText('E2E reference');
  await page.keyboard.press('Escape');
  await page.setViewportSize({ width: 390, height: 844 });
  await expect(page.locator('#refScrollNext')).toBeVisible();
  expect(await page.evaluate(() => document.documentElement.scrollWidth - innerWidth)).toBeLessThanOrEqual(1);
  await page.screenshot({ path: join(evidenceDir, 'mobile-reference-gallery.png') });
});
