import { expect, test } from '@playwright/test';
import { runDjangoCode } from '../helpers/django';
import { routes } from '../helpers/testData';

test.beforeAll(() => {
  // Metadata-only fixtures in the disposable E2E database; no browser file uploads.
  runDjangoCode(`
from django.contrib.auth import get_user_model
from management.models import PatternDesignImage, UserProfile, WorkflowRoles, YearRange
from management.services.design_approvals import record_design_review_decision, submit_design_for_approval
User = get_user_model()
for username in ('fabro_e2e_own_designer', 'fabro_e2e_other_designer'):
    user, _ = User.objects.get_or_create(username=username)
    user.set_password('FabroWorkflow!234')
    user.save()
    profile, _ = UserProfile.objects.get_or_create(user=user)
    profile.role = WorkflowRoles.FREELANCE_3D_DESIGNER
    profile.save()
owner = User.objects.get(username='fabro_e2e_own_designer')
other = User.objects.get(username='fabro_e2e_other_designer')
cad = User.objects.get(username='fabro_e2e_cad')
ed = User.objects.get(username='fabro_e2e_ed')
md = User.objects.create_user(username='fabro_e2e_access_md')
md_profile = md.workflow_profile
md_profile.role = WorkflowRoles.APPROVER
md_profile.approval_role = 'MD'
md_profile.save()
def design(title, designer, image_id=None):
    image = PatternDesignImage.objects.create(
        id=image_id, vehicle=YearRange.objects.first(), title=title,
        image='pattern_designs/' + title.replace(' ', '-'),
        uploaded_by=designer, approval_status='pending',
    )
    submit_design_for_approval(image, designer)
    return image
design('E2E own pending design', owner)
partial = design('E2E own partial design', owner)
record_design_review_decision(partial, cad, 'approved', 'CAD partial note', change_type='minor')
rejected = design('E2E own rejected design', owner)
record_design_review_decision(rejected, cad, 'approved', 'CAD fit approved', change_type='minor')
record_design_review_decision(rejected, ed, 'rejected', 'ED seam needs revision', change_type='major')
record_design_review_decision(rejected, md, 'approved', 'MD opinion complete', change_type='minor')
approved = design('E2E own approved design', owner)
for reviewer, role in ((cad, 'cad'), (ed, 'ed'), (md, 'md')):
    record_design_review_decision(approved, reviewer, 'approved', stage=role, change_type='minor')
revised = design('E2E own revised design', owner)
record_design_review_decision(revised, ed, 'rejected', 'Previous revision note', change_type='major')
submit_design_for_approval(revised, owner, is_resubmission=True)
design('E2E other private design', other, 991001)
`);
});

test('designer Approvals navigation shows only own uploads and review feedback', async ({ page }) => {
  await page.goto(routes.login);
  await page.getByLabel('Username').fill('fabro_e2e_own_designer');
  await page.getByLabel('Password').fill('FabroWorkflow!234');
  await page.getByRole('button', { name: /sign in/i }).click({ noWaitAfter: true });
  await expect(page).not.toHaveURL(/\/login\//, { timeout: 20_000 });

  const approvalsLink = page.locator('.nav-links').getByRole('link', { name: /Approvals/ });
  await expect(approvalsLink).toBeVisible();
  await approvalsLink.click();
  await expect(page).toHaveURL(/\/approvals\/\?stage=designer&status=all/);
  await expect(page.locator('.stage-selector-tabs a')).toHaveCount(1);
  await expect(page.locator('.stage-selector-tabs')).toContainText('Designer Uploads');
  await expect(page.locator('.approval-card')).toHaveCount(5);
  for (const title of ['E2E own pending design', 'E2E own partial design', 'E2E own rejected design',
                       'E2E own approved design', 'E2E own revised design']) {
    await expect(page.locator('.approval-card').filter({ hasText: title })).toBeVisible();
  }
  await expect(page.getByText('E2E other private design')).toHaveCount(0);
  await expect(page.locator('.approval-card').getByRole('button', { name: 'Approve Design' })).toHaveCount(0);
  await expect(page.locator('.approval-card').getByRole('button', { name: 'Decline' })).toHaveCount(0);

  const rejectedCard = page.locator('.approval-card').filter({ hasText: 'E2E own rejected design' });
  await rejectedCard.locator('a[href^="/design-approvals/"]').click();
  await expect(page.locator('#review-cad')).toContainText('CAD fit approved');
  await expect(page.locator('#review-ed')).toContainText('ED seam needs revision');
  await expect(page.locator('#review-ed')).toContainText('Major Change');
  await expect(page.locator('#review-ed')).toContainText(/[A-Z][a-z]{2} \d{1,2}, \d{4} \d{2}:\d{2}/);
  await expect(page.locator('#review-md')).toContainText('MD opinion complete');
  await expect(page.getByRole('button', { name: 'Resubmit for Review' })).toBeVisible();

  await page.goto('/approvals/');
  const revisedCard = page.locator('.approval-card').filter({ hasText: 'E2E own revised design' });
  await revisedCard.locator('a[href^="/design-approvals/"]').click();
  await expect(page.getByText('Revision History')).toBeVisible();

  expect((await page.request.get('/design-approvals/991001/')).status()).toBe(403);
  for (const stage of ['plan', 'verification', 'colors']) {
    expect((await page.request.get(`/approvals/?stage=${stage}`)).status()).toBe(403);
  }
});
