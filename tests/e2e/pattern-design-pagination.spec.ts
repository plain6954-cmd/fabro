import { expect, test } from '@playwright/test';
import { login } from '../helpers/auth';
import { routes } from '../helpers/testData';

const preview = 'data:image/gif;base64,R0lGODlhAQABAAD/ACwAAAAAAQABAAACADs=';
const image = (id: number) => ({
  id,
  url: preview,
  original_url: `/design-original/${id}/`,
  title: `Design ${id}`,
  uploaded_at: 'Sep 30, 2026',
  approval_status: 'approved',
  can_approve: false,
});

test('design folder and image pagination reaches later server pages', async ({ page }) => {
  await login(page);
  await page.route(/\/api\/design-folders\/\?(?:.*)/, async (route) => {
    const params = new URL(route.request().url()).searchParams;
    const folderPage = Number(params.get('folder_page') || 1);
    const imagePage = Number(params.get('image_page') || 1);
    await route.fulfill({ json: {
      status: 'success',
      folders: folderPage === 1
        ? [{ id: 122, name: 'First folder', image_count: 0, preview_images: [], created_at: 'Sep 30, 2026' }]
        : [{ id: 123, name: 'Later folder', image_count: 5, preview_images: [], created_at: 'Sep 30, 2026' }],
      direct_images: imagePage === 1 ? [image(1), image(2), image(3), image(4)] : [image(5)],
      folder_pagination: { page: folderPage, pages: 2 },
      image_pagination: { page: imagePage, pages: 2 },
      vehicle: { id: 1, name: 'Test vehicle', google_drive_url: '' },
    }});
  });
  await page.route(/\/api\/design-folders\/123\/\?(?:.*)/, async (route) => {
    const folderPage = Number(new URL(route.request().url()).searchParams.get('page') || 1);
    await route.fulfill({ json: {
      status: 'success',
      folder: { id: 123, name: 'Later folder', image_count: 5 },
      images: folderPage === 1 ? [image(1), image(2), image(3), image(4)] : [image(5)],
      pagination: { page: folderPage, pages: 2 },
    }});
  });

  await page.goto(`${routes.vehicles}?vehicle_id=1#design-options`);
  await expect(page.locator('#designFoldersGrid')).toContainText('First folder');
  await page.locator('#nextDesignFoldersBtn').click();
  await expect(page.locator('#designFoldersGrid')).toContainText('Later folder');
  await page.locator('#designFoldersGrid .design-folder-card').click();
  await expect(page.locator('#designMatrixGrid .design-matrix-card')).toHaveCount(4);
  await page.locator('#nextMatrixBtn').click();
  await expect(page.locator('#designMatrixGrid')).toContainText('Design 5');
  await page.locator('#designMatrixGrid .design-matrix-card').click();
  await expect(page.locator('#enlargedImageCounter')).toHaveText('1 / 1');
  await expect(page.locator('#enlargedDownloadLink')).toHaveAttribute('href', '/design-original/5/');
  await page.locator('.enlarged-close-btn').click();

  await page.getByRole('button', { name: 'Folders' }).click();
  await page.locator('#nextDirectMatrixBtn').click();
  await expect(page.locator('#directImagesMatrixGrid')).toContainText('Design 5');
});
