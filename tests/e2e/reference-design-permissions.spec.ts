import { expect, test, type Page } from '@playwright/test';
import { runDjangoCode } from '../helpers/django';
import { routes, testUser, workflowUsers } from '../helpers/testData';

const password = 'FabroWorkflow!234';

test.beforeAll(() => {
  // Disposable E2E database only; no physical media is uploaded.
  runDjangoCode(`
from django.contrib.auth import get_user_model
from management.models import ApprovalRoles, PatternDesignImage, UserProfile, WorkflowRoles, YearRange

User = get_user_model()
for username, role, approval_role in [
    ('fabro_e2e_ref_md', WorkflowRoles.APPROVER, ApprovalRoles.MD),
    ('fabro_e2e_ref_cad', WorkflowRoles.APPROVER, ApprovalRoles.CAD),
    ('fabro_e2e_ref_ed', WorkflowRoles.APPROVER, ApprovalRoles.ED),
    ('fabro_e2e_ref_designer', WorkflowRoles.FREELANCE_3D_DESIGNER, None),
    ('fabro_e2e_ref_pm', WorkflowRoles.APPROVER, ApprovalRoles.PM),
    ('fabro_e2e_ref_om', WorkflowRoles.APPROVER, ApprovalRoles.OM),
    ('fabro_e2e_ref_admin', WorkflowRoles.ADMIN, None),
]:
    user, _ = User.objects.get_or_create(username=username)
    user.set_password('FabroWorkflow!234')
    user.save()
    profile, _ = UserProfile.objects.get_or_create(user=user)
    profile.role = role
    profile.approval_role = approval_role if approval_role is not None else ''
    profile.save()

vehicle = YearRange.objects.first()
PatternDesignImage.objects.get_or_create(
    vehicle=vehicle,
    title='E2E reference CAD.obj',
    defaults={
        'image': 'pattern_designs/e2e-reference-cad.obj',
        'uploaded_by': User.objects.get(username='fabro_e2e_ref_md'),
        'is_reference': True,
        'file_size': 1024,
        'approval_status': 'approved',
    },
)
`);
});

async function signIn(page: Page, username: string, userPassword = password) {
  await page.context().clearCookies();
  await page.goto(routes.login);
  await page.getByLabel('Username').fill(username);
  await page.getByLabel('Password').fill(userPassword);
  await page.getByRole('button', { name: /sign in/i }).click({ noWaitAfter: true });
  await expect(page).not.toHaveURL(/\/login\//, { timeout: 20000 });
}

async function openDesignWorkspace(page: Page) {
  await page.goto(`${routes.vehicles}?vehicle_id=1#design-options`);
  await page.locator('#sidebarNav3DDesignBtn').click();
  await expect(page.locator('#refImagesScrollTrack')).toBeVisible();
}

test('reference and design upload buttons follow role permissions', async ({ page }) => {
  test.setTimeout(120_000);

  for (const user of [
    { ...testUser, reference: true, design: false },
    { username: 'fabro_e2e_ref_admin', password, reference: false, design: true },
    { username: 'fabro_e2e_ref_md', password, reference: true, design: true },
    { username: 'fabro_e2e_ref_cad', password, reference: true, design: true },
    { username: 'fabro_e2e_ref_ed', password, reference: true, design: true },
    { username: 'fabro_e2e_ref_designer', password, reference: false, design: true },
    { username: 'fabro_e2e_ref_pm', password, reference: false, design: true },
    { username: 'fabro_e2e_ref_om', password, reference: false, design: true },
  ]) {
    await signIn(page, user.username, user.password);
    await openDesignWorkspace(page);

    await expect(page.locator('#btnUploadRefImages')).toHaveCount(user.reference ? 1 : 0);
    await expect(page.locator('#btnUpload3DDesigns')).toHaveCount(user.design ? 1 : 0);
    await expect(page.locator('#design3DUploadInput')).toBeHidden();
    if (user.design) {
      await expect(page.locator('#btnUpload3DDesigns')).toBeVisible();
      await expect(page.locator('#btnUpload3DDesigns')).toHaveText('');
      await expect(page.locator('#btnUpload3DDesigns')).toHaveAttribute('title', 'Upload Designs');
      await expect(page.locator('#btnUpload3DDesigns')).toHaveAttribute('aria-label', 'Upload Designs');
      const choosing = page.waitForEvent('filechooser');
      await page.locator('#btnUpload3DDesigns').click();
      expect((await choosing).isMultiple()).toBe(true);
    }
  }
});

test('non-image reference uses authenticated download route, not lightbox', async ({ page }) => {
  await signIn(page, testUser.username, testUser.password);
  await openDesignWorkspace(page);

  const card = page.locator('#refImagesScrollTrack .ref-image-card', {
    hasText: 'E2E reference CAD.obj',
  });
  await expect(card).toBeVisible();

  const request = page.waitForEvent('popup', { timeout: 10000 });
  await card.click();
  const popup = await request;

  await expect(popup).toHaveURL(/\/design-images\/\d+\/download\/|\/media\//);
  await expect(page.locator('#interiorMediaPreviewModal')).not.toBeVisible();
  await popup.close();
});
