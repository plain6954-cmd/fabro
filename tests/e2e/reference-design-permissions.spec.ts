import { expect, test, type Page } from '@playwright/test';
import { readFileSync } from 'fs';
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
    if (user.reference) {
      await expect(page.locator('#btnUploadRefImages')).toHaveText('');
      await expect(page.locator('#btnUploadRefImages')).toHaveAttribute('aria-label', 'Upload Reference Files');
      await expect(page.locator('#btnUploadRefImages')).toHaveAttribute('title', 'Upload Reference Files');
    }
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

test('all 3D upload actions share compact red plus geometry and retain their real file pickers', async ({page}) => {
  test.setTimeout(60_000);
  const image=readFileSync('media/pattern_designs/2026/10/test_designer_fix.png');
  async function checkButtons(ids:string[]) {
    for(const width of [1366,390]) {
      await page.setViewportSize({width,height:900});
      for(const light of [false,true]) {
        await page.evaluate(value=>document.body.classList.toggle('light-mode',value),light);
        const styles=[];
        for(const id of ids) {
          const button=page.locator(`#${id}`);
          await button.scrollIntoViewIfNeeded();await page.mouse.move(0,0);await expect(button).toHaveText('');
          await expect(button.locator('i.fa-plus[aria-hidden="true"]')).toHaveCount(1);
          expect(await button.getAttribute('title')).toBe(await button.getAttribute('aria-label'));
          const metric=await button.evaluate(el=>{const r=el.getBoundingClientRect(),i=el.querySelector('i')!.getBoundingClientRect(),s=getComputedStyle(el);return {width:r.width,height:r.height,radius:s.borderRadius,bg:s.backgroundColor,color:getComputedStyle(el.querySelector('i')!).color,left:r.left,right:r.right,dx:Math.abs(r.x+r.width/2-i.x-i.width/2),dy:Math.abs(r.y+r.height/2-i.y-i.height/2)};});
          expect(metric.width).toBe(40);expect(metric.height).toBe(40);expect(metric.radius).toBe('6px');expect(metric.color).toBe('rgb(255, 255, 255)');
          expect(metric.left).toBeGreaterThanOrEqual(0);expect(metric.right).toBeLessThanOrEqual(width);expect(metric.dx).toBeLessThan(1);expect(metric.dy).toBeLessThan(1);
          await button.hover();const hover=await button.evaluate(el=>getComputedStyle(el).backgroundColor);
          await button.focus();await button.press('ArrowLeft');await expect(button).toHaveCSS('outline-style','solid');
          styles.push({background:metric.bg,hover});
        }
        expect(styles.every(style=>JSON.stringify(style)===JSON.stringify(styles[0]))).toBe(true);
      }
    }
  }
  async function upload(id:string,name:string,reference:boolean) {
    const choosing=page.waitForEvent('filechooser');await page.locator(`#${id}`).click();const picker=await choosing;expect(picker.isMultiple()).toBe(true);
    const saved=page.waitForResponse(response=>response.request().method()==='POST'&&response.url().includes('/api/vehicles/1/design-images/upload/'));
    await picker.setFiles({name,mimeType:'image/png',buffer:image});const response=await saved;expect(response.status()).toBe(200);expect((await response.json()).status).toBe('success');
    const data=await (await page.request.get('/api/design-folders/?vehicle_id=1')).json();
    expect(data[reference?'reference_images':'design_files'].some((file:any)=>file.title===name)).toBe(true);
  }
  await signIn(page,'fabro_e2e_ref_cad');await openDesignWorkspace(page);
  await checkButtons(['btnUploadRefImages','btnUpload3DDesigns']);
  await upload('btnUploadRefImages','E2E compact reference.png',true);
  await upload('btnUpload3DDesigns','E2E compact designer.png',false);
  await signIn(page,'fabro_e2e_ref_designer');await openDesignWorkspace(page);
  await expect(page.locator('#btnUploadRefImages')).toHaveCount(0);
  await expect(page.locator('#btnDesignerUploadFile')).toHaveAttribute('title','Upload 3D Design File');
  await checkButtons(['btnDesignerUploadFile','btnUpload3DDesigns']);
  await upload('btnDesignerUploadFile','E2E compact designer workspace.png',false);
});
