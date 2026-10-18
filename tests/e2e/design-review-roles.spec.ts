import { expect, test, type Page } from '@playwright/test';
import { mkdirSync } from 'fs';
import { join } from 'path';
import { runDjangoCode } from '../helpers/django';
import { routes, workflowUsers } from '../helpers/testData';

const password = 'FabroWorkflow!234';

test.beforeAll(() => {
  // Only database metadata is created in the disposable E2E database.
  runDjangoCode(`
from django.contrib.auth import get_user_model
from management.models import ApprovalRoles, PatternDesignImage, UserProfile, WorkflowRoles, YearRange
from management.services.design_approvals import submit_design_for_approval
User = get_user_model()
designer, _ = User.objects.get_or_create(username='fabro_e2e_review_designer')
designer.set_password('FabroWorkflow!234')
designer.save()
profile, _ = UserProfile.objects.get_or_create(user=designer)
profile.role = WorkflowRoles.FREELANCE_3D_DESIGNER
profile.save()
md, _ = User.objects.get_or_create(username='fabro_e2e_md')
md.set_password('FabroWorkflow!234')
md.save()
profile, _ = UserProfile.objects.get_or_create(user=md)
profile.role = WorkflowRoles.APPROVER
profile.approval_role = ApprovalRoles.MD
profile.save()
image, _ = PatternDesignImage.objects.get_or_create(
    vehicle=YearRange.objects.first(), title='E2E reviewer matrix.obj',
    defaults={'image': 'pattern_designs/e2e-reviewer-matrix.obj', 'uploaded_by': designer, 'approval_status': 'pending'},
)
submit_design_for_approval(image, designer)
`);
});

async function signIn(page: Page, username: string, userPassword = password) {
  await page.context().clearCookies();
  await page.goto(routes.login);
  await page.getByLabel('Username').fill(username);
  await page.getByLabel('Password').fill(userPassword);
  await page.getByRole('button', { name: /sign in/i }).click();
  await expect(page).not.toHaveURL(/\/login\//);
}

test('MD, ED, and CAD review one design independently and factory access is denied', async ({ page }) => {
  test.setTimeout(120_000);
  await signIn(page, workflowUsers.cad.username);
  const filesResponse = await page.request.get('/api/design-folders/?vehicle_id=1');
  expect(filesResponse.ok()).toBe(true);
  const files = (await filesResponse.json()).design_files as Array<{ id: number; title: string }>;
  const image = files.find((file) => file.title === 'E2E reviewer matrix.obj');
  expect(image).toBeTruthy();
  const detail = `/design-approvals/${image!.id}/`;

  for (const reviewer of [
    { username: 'fabro_e2e_md', stage: 'md', classification: 'major', comment: 'MD review complete' },
    { username: workflowUsers.ed.username, stage: 'ed', classification: 'minor', comment: 'ED review complete' },
    { username: workflowUsers.cad.username, stage: 'cad', classification: 'minor', comment: 'CAD review complete' },
  ]) {
    await signIn(page, reviewer.username);
    await page.goto(detail);
    const form = page.locator(`form:has(input[name="stage"][value="${reviewer.stage}"])`);
    await expect(form).toBeVisible();
    await form.locator('select[name="change_type"]').selectOption(reviewer.classification);
    await form.locator('textarea[name="comment"]').fill(reviewer.comment);
    await form.locator('button[name="decision"][value="approved"]').click();
    await expect(form).toHaveCount(0);
    await expect(page.getByText(reviewer.comment)).toBeVisible();
  }

  await expect(page.getByText('APPROVED', { exact: true })).toBeVisible();
  const evidenceDir = join('output', 'codex-full-debug', 'screenshots');
  mkdirSync(evidenceDir, { recursive: true });
  await page.screenshot({ path: join(evidenceDir, 'approved-design-review.png') });

  await signIn(page, 'fabro_e2e_review_designer');
  await page.goto(detail);
  for (const comment of ['MD review complete', 'ED review complete', 'CAD review complete']) {
    await expect(page.getByText(comment)).toBeVisible();
  }
  await signIn(page, workflowUsers.factory.username);
  const forbidden = await page.request.get(detail);
  expect(forbidden.status()).toBe(403);
});
