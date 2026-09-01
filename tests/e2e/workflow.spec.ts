import { expect, test } from '@playwright/test';
import { loginAs } from '../helpers/auth';
import { attachPageDiagnostics, expectNoDjangoError } from '../helpers/assertions';
import { routes, workflowUsers } from '../helpers/testData';
import { searchComplaints } from '../helpers/navigation';

const workflowDescription = 'E2E complete approval and closure workflow';

async function openSeededComplaint(page) {
  await page.goto(routes.complaints);
  await searchComplaints(page, workflowDescription, 'description');
  const row = page.locator('tbody tr').first();
  await expect(row).toBeVisible();
  return row;
}

test('factory review, parallel approvals, green light and final close work end to end', async ({ page }) => {
  test.setTimeout(90_000);
  const diagnostics = attachPageDiagnostics(page);

  await loginAs(page, workflowUsers.factory);
  let row = await openSeededComplaint(page);
  await row.locator('.action-btn.review').click({ force: true });
  await page.getByLabel(/Real reason behind defect/i).fill('The stitching guide was offset during production.');
  await page.getByLabel(/Factory action plan/i).fill('Correct the guide, verify CAD, and issue a replacement batch.');
  await page.getByLabel(/Factory priority/i).selectOption('medium');
  await page.getByRole('button', { name: /Submit for Approval/i }).click({ force: true });
  await expect(page.getByRole('heading', { name: /Complaint Management/i })).toBeVisible();

  for (const [role, credentials] of Object.entries({
    PM: workflowUsers.pm,
    OM: workflowUsers.om,
    CAD: workflowUsers.cad,
    ED: workflowUsers.ed
  })) {
    await loginAs(page, credentials);
    await page.goto('/approvals/');
    await expect(page.getByRole('heading', { name: /Approvals Workspace/i })).toBeVisible();
    await page.getByRole('link', { name: /Full Review Page/i }).first().click();
    await page.getByLabel('Approve').check();
    await page.getByLabel(/Review comment/i).fill(`${role} approves the verified factory action plan.`);
    await page.getByRole('button', { name: /Submit Review/i }).click();
    await expect(page.getByRole('heading', { name: /Approvals Workspace/i })).toBeVisible();
  }

  await loginAs(page, workflowUsers.factory);
  row = await openSeededComplaint(page);
  await expect(row.locator('.action-btn.execute')).toBeVisible();
  await row.locator('.action-btn.execute').click({ force: true });
  await expect(page.locator('.green-light').getByText(/Green Light/i)).toBeVisible();
  await page.getByRole('button', { name: /Proceed With Action Plan/i }).click();

  await page.getByRole('button', { name: /Submit Execution For Verification/i }).click();
  await expect(page.getByText(/Execution Verification In Progress/i)).toBeVisible();

  for (const [role, credentials] of Object.entries({
    PM: workflowUsers.pm,
    OM: workflowUsers.om,
    CAD: workflowUsers.cad,
    ED: workflowUsers.ed
  })) {
    await loginAs(page, credentials);
    await page.goto('/approvals/?stage=verification&status=active');
    await expect(page.getByRole('heading', { name: /Approvals Workspace/i })).toBeVisible();
    await page.getByRole('link', { name: /Full Review Page/i }).first().click();
    await page.getByLabel(/Execution Is Correct/i).check();
    await page.getByLabel(/Review comment/i).fill(`${role} verified the completed execution.`);
    await page.getByRole('button', { name: /Submit Review/i }).click();
    await expect(page.getByRole('heading', { name: /Approvals Workspace/i })).toBeVisible();
  }

  await loginAs(page, workflowUsers.factory);
  row = await openSeededComplaint(page);
  await row.locator('.action-btn.execute').click({ force: true });
  await page.getByLabel(/CAD Updated Date/i).fill(new Date().toISOString().slice(0, 10));
  await page.getByLabel(/New Production Container Number/i).fill('E2E-CONTAINER-READY');
  await page.getByRole('button', { name: /Save Updates And Close Case/i }).click();
  await expect(page.getByRole('heading', { name: /Complaint Management/i })).toBeVisible();

  row = await openSeededComplaint(page);
  await expect(row.locator('.status-badge.status-closed')).toHaveText(/Closed/);
  await expectNoDjangoError(page);
  await diagnostics.assertClean();
});
