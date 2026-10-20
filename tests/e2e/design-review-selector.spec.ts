import { expect, test } from '@playwright/test';
import { mkdirSync, writeFileSync } from 'fs';
import { join } from 'path';
import { runDjangoCode } from '../helpers/django';
import { workflowUsers } from '../helpers/testData';

const reportDir = join('output', 'design-review-verification');
const title = 'E2E optional remarks selector.obj';

test.beforeAll(() => {
  mkdirSync(reportDir, { recursive: true });
  runDjangoCode(`
from django.contrib.auth import get_user_model
from django.core.files.base import ContentFile
from management.models import PatternDesignImage, WorkflowRoles, YearRange
from management.services.design_approvals import submit_design_for_approval
designer = get_user_model().objects.create_user(username='selector_test_designer')
profile = designer.workflow_profile
profile.role = WorkflowRoles.FREELANCE_3D_DESIGNER
profile.save()
for title in ('${title}', 'E2E empty remarks.obj'):
    image = PatternDesignImage.objects.create(
        vehicle=YearRange.objects.first(), title=title,
        image=ContentFile(b'v 0 0 0', name='selector-test.obj'), uploaded_by=designer,
    )
    submit_design_for_approval(image, designer)
`);
});

test('review drawer glides, fits all target widths, and saves written and empty rejections', async ({ page }) => {
  test.setTimeout(90_000);
  const errors: string[] = [];
  page.on('pageerror', error => errors.push(error.message));
  page.on('console', message => {
    if (message.type() === 'error') errors.push(`${message.text()} ${message.location().url}`);
  });
  await page.emulateMedia({ reducedMotion: 'no-preference' });
  await page.goto('/login/');
  await page.getByLabel('Username').fill(workflowUsers.cad.username);
  await page.getByLabel('Password').fill('FabroWorkflow!234');
  await page.getByRole('button', { name: /sign in/i }).click();
  await expect(page).not.toHaveURL(/\/login\//);
  await page.goto('/car-details/?vehicle_id=1#design-options');
  await page.locator('#sidebarNav3DDesignBtn').click();
  await expect(page.locator('.fabro-design-tile', { hasText: title })).toBeVisible();
  await page.locator('#btnOpenTopApprovalWorkflow').click();
  const drawer = page.locator('#designApprovalDrawer');
  await expect(drawer).toHaveClass(/is-open/);
  const fileId = await page.locator('#drawerFileSelector option').filter({ hasText: title }).getAttribute('value');
  await page.locator('#drawerFileSelector').selectOption(fileId!);
  const minor = page.locator('#radioChangeTypeMinor');
  const major = page.locator('#radioChangeTypeMajor');
  const selector = page.getByRole('radiogroup', { name: 'Change Classification' });
  await minor.scrollIntoViewIfNeeded();
  await expect(minor).toBeChecked();
  await expect(page.locator('#designDrawerDecisionRemarks')).toHaveValue('');
  // Read multiple animation frames: the indicator must pass through an intermediate
  // position while both label rectangles remain fixed.
  const animation = await selector.evaluate(async element => {
    const radio = element.querySelector<HTMLInputElement>('input[value="major"]')!;
    const before = Array.from(element.querySelectorAll('label')).map(label => label.getBoundingClientRect().x);
    const samples: number[] = [];
    radio.click();
    const started = performance.now();
    while (performance.now() - started < 300) {
      await new Promise(requestAnimationFrame);
      samples.push(new DOMMatrixReadOnly(getComputedStyle(element, '::before').transform).m41);
    }
    return { samples, before, after: Array.from(element.querySelectorAll('label')).map(label => label.getBoundingClientRect().x) };
  });
  await expect(major).toBeChecked();
  expect(animation.before).toEqual(animation.after);
  const finalPosition = animation.samples.at(-1)!;
  expect(finalPosition).toBeGreaterThan(0);
  expect(animation.samples.some(position => position > 0 && position < finalPosition - 1)).toBe(true);
  await major.focus();
  await page.keyboard.press('ArrowLeft');
  await expect(minor).toBeChecked();
  expect(await page.locator('#lblChangeTypeMinor').evaluate(el => getComputedStyle(el).outlineStyle)).toBe('solid');
  // Rapid keyboard switching leaves native selection and the indicator in sync.
  await page.keyboard.press('ArrowRight');
  await page.keyboard.press('ArrowLeft');
  await page.keyboard.press('ArrowRight');
  await expect(major).toBeChecked();

  const layouts = [];
  for (const width of [320, 375, 768, 1024, 1440, 1920]) {
    await page.setViewportSize({ width, height: width < 768 ? 812 : 1080 });
    for (const light of [false, true]) {
      await page.evaluate(value => document.body.classList.toggle('light-mode', value), light);
      await selector.scrollIntoViewIfNeeded();
      const metrics = await selector.evaluate(element => {
        const group = element.getBoundingClientRect();
        const labels = Array.from(element.querySelectorAll('label')).map(label => {
          const rect = label.getBoundingClientRect();
          return { left: rect.left, right: rect.right, width: rect.width, scroll: label.scrollWidth };
        });
        const drawer = document.getElementById('designApprovalDrawer')!;
        return { viewport: innerWidth, pageWidth: document.documentElement.scrollWidth,
          drawerWidth: drawer.clientWidth, drawerScroll: drawer.scrollWidth,
          groupLeft: group.left, groupRight: group.right, labels };
      });
      layouts.push({ width, light, ...metrics });
      expect(metrics.pageWidth).toBeLessThanOrEqual(width + 1);
      expect(metrics.drawerScroll).toBeLessThanOrEqual(metrics.drawerWidth + 1);
      expect(metrics.groupLeft).toBeGreaterThanOrEqual(0);
      expect(metrics.groupRight).toBeLessThanOrEqual(width);
      expect(metrics.labels[0].right).toBeLessThan(metrics.labels[1].left);
      for (const label of metrics.labels) expect(label.scroll).toBeLessThanOrEqual(label.width + 1);
      if ((width === 320 && !light) || (width === 375 && light) || (width === 1440 && !light)) {
        await page.screenshot({ path: join(reportDir, `review-${width}-${light ? 'light' : 'dark'}.png`) });
      }
    }
  }
  await page.emulateMedia({ reducedMotion: 'reduce' });
  // The portal's global reduced-motion rule uses an effectively instant 0.01ms.
  expect(await selector.evaluate(el => parseFloat(getComputedStyle(el, '::before').transitionDuration))).toBeLessThanOrEqual(0.001);
  await minor.check();
  expect(await selector.evaluate(el => new DOMMatrixReadOnly(getComputedStyle(el, '::before').transform).m41)).toBe(0);
  await major.check();
  await expect(major).toBeChecked();
  const remarks = '  Match the seam\n  and retain these spaces.  ';
  await page.locator('#designDrawerDecisionRemarks').fill(remarks);
  // The hidden Color Approval field must never be read instead of design remarks.
  await expect(page.locator('#drawerDecisionRemarks')).toHaveValue('');
  const saved = page.waitForResponse(response => /\/api\/design-images\/\d+\/reject\//.test(response.url()) && response.request().method() === 'POST');
  await page.locator('#drawerBtnReject').click();
  const response = await saved;
  expect(response.status()).toBe(200);
  expect(response.request().postDataJSON().comment).toBe(remarks);
  expect((await response.json()).cad_change_type).toBe('major');
  await expect(page.locator('#drawerCadStatusBadge')).toHaveText('REJECTED');
  await expect(page.locator('#drawerCadChangeTypeBadge')).toContainText('Major Change');
  expect(await page.locator('#drawerCadRemarks').textContent()).toBe(`"${remarks}"`);
  await expect(page.locator('#drawerDecisionBox')).toBeHidden();
  await drawer.locator('.drawer-close-btn').click();
  await expect(drawer).not.toHaveClass(/is-open/);
  await page.locator('#btnOpenTopApprovalWorkflow').click();
  await page.locator('#drawerFileSelector').selectOption(fileId!);
  await expect(page.locator('#drawerCadChangeTypeBadge')).toContainText('Major Change');
  await page.screenshot({ path: join(reportDir, 'saved-major-rejection.png') });
  const emptyFileId = await page.locator('#drawerFileSelector option').filter({ hasText: 'E2E empty remarks.obj' }).getAttribute('value');
  await page.locator('#drawerFileSelector').selectOption(emptyFileId!);
  await expect(minor).toBeChecked();
  await expect(page.locator('#designDrawerDecisionRemarks')).toHaveValue('');
  const emptySaved = page.waitForResponse(response => response.url().endsWith(`/api/design-images/${emptyFileId}/reject/`));
  await page.locator('#drawerBtnReject').click();
  const emptyResponse = await emptySaved;
  expect(emptyResponse.status()).toBe(200);
  expect(emptyResponse.request().postDataJSON().comment).toBe('');
  expect((await emptyResponse.json()).cad_change_type).toBe('minor');
  await expect(page.locator('#drawerCadStatusBadge')).toHaveText('REJECTED');
  writeFileSync(join(reportDir, 'layout-and-animation.json'), JSON.stringify({ layouts, animation, errors }, null, 2));
  expect(errors).toEqual([]);
});
