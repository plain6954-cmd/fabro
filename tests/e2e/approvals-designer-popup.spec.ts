import { expect, test, type Page } from '@playwright/test';
import { runDjangoCode } from '../helpers/django';
import { routes, workflowUsers } from '../helpers/testData';

const password = 'FabroWorkflow!234';
const firstTitle = 'E2E popup first.obj';
const secondTitle = 'E2E popup second.obj';

test.beforeAll(() => {
  // These metadata-only designs live in the disposable .e2e.sqlite3 database.
  runDjangoCode(`
from django.contrib.auth import get_user_model
from management.models import PatternDesignImage, UserProfile, WorkflowRoles, YearRange
from management.services.design_approvals import submit_design_for_approval
User = get_user_model()
for username, role in [('fabro_e2e_popup_designer', WorkflowRoles.FREELANCE_3D_DESIGNER),
                       ('fabro_e2e_popup_admin', WorkflowRoles.ADMIN)]:
    user, _ = User.objects.get_or_create(username=username)
    user.set_password('FabroWorkflow!234')
    user.save()
    profile, _ = UserProfile.objects.get_or_create(user=user)
    profile.role = role
    profile.save()
designer = User.objects.get(username='fabro_e2e_popup_designer')
for title in ['E2E popup first.obj', 'E2E popup second.obj']:
    image = PatternDesignImage.objects.create(
        vehicle=YearRange.objects.first(), title=title,
        image='pattern_designs/' + title.replace(' ', '-'),
        uploaded_by=designer, approval_status='pending',
    )
    submit_design_for_approval(image, designer)
`);
});

async function signIn(page: Page, username: string) {
  await page.context().clearCookies();
  await page.goto(routes.login);
  await page.getByLabel('Username').fill(username);
  await page.getByLabel('Password').fill(password);
  await page.getByRole('button', { name: /sign in/i }).click({ noWaitAfter: true });
  await expect(page).not.toHaveURL(/\/login\//, { timeout: 20_000 });
}

function contrast(foreground: string, background: string) {
  const luminance = (value: string) => {
    const channels = value.match(/[\d.]+/g)!.slice(0, 3).map(Number).map(channel => {
      const scaled = channel / 255;
      return scaled <= 0.04045 ? scaled / 12.92 : ((scaled + 0.055) / 1.055) ** 2.4;
    });
    return channels[0] * 0.2126 + channels[1] * 0.7152 + channels[2] * 0.0722;
  };
  const light = Math.max(luminance(foreground), luminance(background));
  const dark = Math.min(luminance(foreground), luminance(background));
  return (light + 0.05) / (dark + 0.05);
}

test('Designer Uploads popup records an explicit Admin MD opinion and keeps reviewers independent', async ({ page }) => {
  test.setTimeout(120_000);
  await signIn(page, 'fabro_e2e_popup_admin');
  await page.goto('/approvals/?stage=designer&status=my_pending');
  const first = page.locator('.approval-card').filter({ hasText: firstTitle });
  const second = page.locator('.approval-card').filter({ hasText: secondTitle });
  await first.getByRole('button', { name: 'Approve Design' }).click();
  const popup = page.locator('#designReviewModalOverlay');
  const confirm = popup.getByRole('button', { name: 'Confirm Decision' });
  const classification = popup.locator('#modalDesignChangeType');
  await expect(popup).toBeVisible();
  await expect(confirm).toBeDisabled();
  await expect(popup.getByRole('radio', { name: /MD/ })).not.toBeChecked();

  for (const light of [false, true]) {
    await page.evaluate(value => document.body.classList.toggle('light-mode', value), light);
    for (const element of ['select', 'option[value=""]', 'option[value="minor"]', 'option[value="major"]']) {
      const colors = await classification.evaluate((select, selector) => {
        const style = getComputedStyle(selector === 'select' ? select : select.querySelector(selector)!);
        return { color: style.color, background: style.backgroundColor };
      }, element);
      expect(contrast(colors.color, colors.background), `${light ? 'light' : 'dark'} ${element} contrast ${JSON.stringify(colors)}`).toBeGreaterThanOrEqual(4.5);
    }
  }
  await page.evaluate(() => document.body.classList.remove('light-mode'));
  await popup.getByRole('radio', { name: /MD/ }).check();
  await expect(popup.locator('#designReviewRoleNotice')).toHaveText('Reviewing on behalf of MD');
  await expect(confirm).toBeDisabled();
  await classification.selectOption('major');
  for (const light of [false, true]) {
    await page.evaluate(value => document.body.classList.toggle('light-mode', value), light);
    const colors = await classification.evaluate(select => {
      const style = getComputedStyle(select);
      return { color: style.color, background: style.backgroundColor };
    });
    expect(contrast(colors.color, colors.background), `${light ? 'light' : 'dark'} selected value contrast`).toBeGreaterThanOrEqual(4.5);
  }
  await page.evaluate(() => document.body.classList.remove('light-mode'));
  await expect(confirm).toBeEnabled();
  await Promise.all([page.waitForNavigation({ waitUntil: 'domcontentloaded' }), confirm.click()]);
  await expect(first).toHaveAttribute('data-md-status', 'approved');
  await expect(first).toHaveAttribute('data-cad-status', 'pending');
  await expect(first).toHaveAttribute('data-ed-status', 'pending');

  await first.getByRole('button', { name: 'Approve Design' }).click();
  await expect(popup.getByRole('radio', { name: /MD/ })).toBeDisabled();
  await expect(popup.getByRole('radio', { name: /CAD/ })).toBeEnabled();
  await popup.getByRole('button', { name: 'Cancel' }).click();
  await second.getByRole('button', { name: 'Decline' }).click();
  await expect(popup.getByRole('radio', { name: /CAD/ })).not.toBeChecked();
  await expect(classification).toHaveValue('');
  await expect(popup.locator('#modalDesignComment')).toHaveValue('');
  await popup.getByRole('radio', { name: /CAD/ }).check();
  await classification.selectOption('minor');
  await expect(confirm).toBeDisabled();
  await popup.locator('#modalDesignComment').fill('   ');
  await expect(confirm).toBeDisabled();
  await popup.locator('#modalDesignComment').fill('Needs adjustment');
  await expect(confirm).toBeEnabled();
  await page.setViewportSize({ width: 375, height: 667 });
  const bounds = await popup.locator('.decision-modal-content').boundingBox();
  expect(bounds).toBeTruthy();
  expect(bounds!.x).toBeGreaterThanOrEqual(0);
  expect(bounds!.x + bounds!.width).toBeLessThanOrEqual(375);
  expect(bounds!.height).toBeLessThanOrEqual(667);
  await page.setViewportSize({ width: 1366, height: 768 });
  await popup.getByRole('button', { name: 'Cancel' }).click();

  await signIn(page, workflowUsers.cad.username);
  await page.goto('/approvals/?stage=designer&status=my_pending');
  const cadCard = page.locator('.approval-card').filter({ hasText: firstTitle });
  const imageId = (await cadCard.getAttribute('id'))!.replace('card-design-', '');
  await cadCard.getByRole('button', { name: 'Decline' }).click();
  await expect(popup.locator('#designReviewRoleOptions')).toHaveCount(0);
  await expect(popup.locator('#designReviewRoleNotice')).toHaveText('Reviewing as CAD');
  const tampered = await page.evaluate(async id => {
    const response = await fetch(`/api/design-images/${id}/approve/`, {
      method: 'POST', credentials: 'same-origin',
      headers: { 'X-CSRFToken': (document.querySelector('[name=csrfmiddlewaretoken]') as HTMLInputElement).value },
      body: new URLSearchParams({ stage: 'ed', change_type: 'minor' }),
    });
    return response.status;
  }, imageId);
  expect(tampered).toBe(403);
  await classification.selectOption('major');
  await expect(confirm).toBeDisabled();
  await popup.locator('#modalDesignComment').fill('CAD requests changes');
  await Promise.all([page.waitForNavigation({ waitUntil: 'domcontentloaded' }), confirm.click()]);
  await page.goto('/approvals/?stage=designer&status=all');
  await expect(cadCard).toHaveAttribute('data-cad-status', 'rejected');
  await expect(cadCard).toHaveAttribute('data-ed-status', 'pending');

  await signIn(page, workflowUsers.ed.username);
  await page.goto('/approvals/?stage=designer&status=my_pending');
  const edCard = page.locator('.approval-card').filter({ hasText: firstTitle });
  await edCard.getByRole('button', { name: 'Approve Design' }).click();
  await expect(popup.locator('#designReviewRoleNotice')).toHaveText('Reviewing as ED');
  await classification.selectOption('minor');
  await Promise.all([page.waitForNavigation({ waitUntil: 'domcontentloaded' }), confirm.click()]);
  await page.goto('/approvals/?stage=designer&status=all');
  await expect(edCard).toHaveAttribute('data-ed-status', 'approved');
  await expect(edCard).toHaveAttribute('data-cad-status', 'rejected');
});
