import {expect, test, type Page} from '@playwright/test';
import {login, loginAs} from '../helpers/auth';
import {runDjangoCode} from '../helpers/django';

test.beforeAll(() => runDjangoCode(`
from django.contrib.auth import get_user_model
from management.models import WorkflowRoles, ApprovalRoles
from django.contrib.auth.models import Group, Permission
group,_=Group.objects.get_or_create(name='UCP file manager');group.permissions.add(Permission.objects.get(codename='delete_patterndesignimage'))
User=get_user_model()
for name, role, stage in [('ucp_browser_edit','factory_viewer',''),('ucp_browser_denied','approver','CAD')]:
    user,_=User.objects.get_or_create(username=name)
    user.email=name+'@example.com';user.set_password('UcpBrowser!369');user.save()
    profile=user.workflow_profile
    profile.role=role;profile.approval_role=stage
    profile.activity_permissions={'chat.view':'deny','reference.upload':'deny','design_approval.approve':'deny','design_approval.reject':'deny'} if name.endswith('denied') else {}
    profile.save()
from management.models import PatternDesignImage,YearRange
from management.services.design_approvals import submit_design_for_approval
from django.core.files.base import ContentFile
from unittest.mock import patch
import base64
owner,_=User.objects.get_or_create(username='ucp_browser_owner')
p=owner.workflow_profile;p.role='freelance_3d_designer';p.save()
image,created=PatternDesignImage.objects.get_or_create(title='UCP read-only fixture',defaults={'vehicle':YearRange.objects.first(),'uploaded_by':owner,'approval_status':'pending'})
if created:
    image.image.save('ucp-fixture.png',ContentFile(base64.b64decode('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+aH1cAAAAASUVORK5CYII=')))
    with patch('management.services.push_notifications.send_push_to_user'):
        submit_design_for_approval(image,owner)
`));

test.afterAll(() => runDjangoCode("from django.contrib.auth import get_user_model; get_user_model().objects.filter(username='ucp_browser_denied').update(is_active=False)"));

async function users(page: Page) {
    await login(page); await page.goto('/admin_panel/?section=users');
}
async function add(page: Page) {
    await page.locator('#tab-users button[onclick="openCreateUserModal()"]').click();
    await expect(page.locator('#editUserModal')).toHaveAttribute('aria-busy','false');
}
async function edit(page: Page, name = 'ucp_browser_edit') {
    await page.locator(`.erp-user-card[data-username="${name}"]`).click();
    await expect(page.locator('#editUserModal')).toHaveAttribute('aria-busy','false');
}
const choice = (page: Page, key: string) => page.locator(`[data-permission="${key}"]`);

test('Add and Edit use one full-screen panel preserving all supported user fields', async ({page}) => {
    await users(page); await add(page);
    await expect(page.locator('.user-control-panel')).toHaveCount(1);
    const box=await page.locator('#editUserModal').boundingBox();
    expect(box!.width).toBe(1366);expect(box!.height).toBe(768);expect(box!.x).toBe(0);expect(box!.y).toBe(0);
    await expect(page.locator('.ucp-category')).toHaveCount(18);
    for(const id of ['editUsername','editEmail','editFirstName','editLastName','editPhone','editRole','editCountry','editDepartment','ucpPhoto','editCanFactory','editIsStaff','editIsSuperuser','ucpActive','ucpGroups']) await expect(page.locator('#'+id)).toBeAttached();
    await expect(page.locator('#editUserPassword')).toHaveAttribute('name','password');
    await expect(page.locator('#editUserPassword')).toHaveAttribute('required','');
    await page.locator('#editUserModal .erp-modal-close').click();
    await edit(page);
    await expect(page.locator('#editUsername')).toHaveValue('ucp_browser_edit');
    await expect(page.locator('#editUserPassword')).toHaveValue('');
    await expect(page.locator('#editUserPassword')).not.toHaveAttribute('required');
});

test('role defaults, manual choices, cancel/confirm role switch and reset remain unsaved until Save', async ({page}) => {
    await users(page); await add(page);
    await expect(choice(page,'reference.upload')).not.toBeChecked();
    await expect(choice(page,'reference.upload')).toBeDisabled();
    await choice(page,'chat.send').uncheck();
    await expect(choice(page,'chat.send').locator('..')).toContainText('Override: Deny');
    page.once('dialog', dialog => dialog.dismiss());
    await page.locator('#editRole').selectOption('CAD');
    await expect(page.locator('#editRole')).toHaveValue('factory_viewer');
    await expect(choice(page,'chat.send')).not.toBeChecked();
    page.once('dialog', dialog => {expect(dialog.message()).toContain('replace unsaved permission');return dialog.accept();});
    await page.locator('#editRole').selectOption('CAD');
    await expect(choice(page,'reference.upload')).toBeChecked();
    await expect(choice(page,'chat.send')).toBeChecked();
    await expect(choice(page,'design_approval.approve')).toBeChecked();
    await choice(page,'chat.send').uncheck();
    page.once('dialog', dialog=>dialog.accept());await page.locator('[data-ucp-reset]').click();
    await expect(choice(page,'chat.send')).toBeChecked();
    await page.locator('#ucpSearch').fill('voice');
    await expect(page.locator('.ucp-activity:visible')).toHaveCount(1);
    await page.locator('#ucpSearch').fill('');
    await page.locator('[data-ucp-collapse]').click();
    await expect(page.locator('.ucp-category[open]')).toHaveCount(0);
    await page.locator('[data-ucp-expand]').click();
    await expect(page.locator('.ucp-category[open]')).toHaveCount(18);
    page.once('dialog',dialog=>dialog.dismiss());await page.locator('#editUserModal .erp-modal-close').click();
    await expect(page.locator('#editUserModal')).toBeVisible();
    page.once('dialog',dialog=>dialog.accept());await page.keyboard.press('Escape');
    await expect(page.locator('#editUserModal')).not.toBeVisible();
});

test('edit persists overrides and account details while blank password preserves the hash', async ({page}) => {
    await users(page); await edit(page);
    await page.locator('#editFirstName').fill('Updated');
    await choice(page,'chat.send').uncheck();
    const saved=page.waitForResponse(response=>response.url().endsWith('/admin-panel/users/save/'));
    await page.locator('#saveEditUserButton').click();expect((await saved).status()).toBe(200);
    await expect(page.locator('#editUserFeedback')).toContainText('saved successfully');
    await page.locator('#editUserModal .erp-modal-close').click();
    await edit(page);
    await expect(page.locator('#editFirstName')).toHaveValue('Updated');
    await expect(choice(page,'chat.send')).not.toBeChecked();
    await expect(choice(page,'chat.send').locator('..')).toContainText('Override: Deny');
    runDjangoCode("from django.contrib.auth import get_user_model; u=get_user_model().objects.get(username='ucp_browser_edit'); assert u.check_password('UcpBrowser!369'); assert u.workflow_profile.activity_permissions=={'chat.send':'deny'}; assert u.access_changes_received.exists()");
});

test('create user and duplicate-submit protection use the existing validation and password hashing', async ({page}) => {
    await users(page); await add(page);
    await page.locator('#editUsername').fill('ucp_browser_created');
    await page.locator('#editEmail').fill('created@example.com');
    await page.locator('#editUserPassword').fill('NewBrowser!368');
    await page.locator('#editUserPasswordConfirm').fill('NewBrowser!368');
    let calls=0;
    await page.route('**/admin-panel/users/save/',async route=>{calls++;await route.continue();});
    const saved=page.waitForResponse(response=>response.url().endsWith('/admin-panel/users/save/'));
    await page.locator('#saveEditUserButton').evaluate(button=>{(button as HTMLButtonElement).click();(button as HTMLButtonElement).click();});
    expect((await saved).status()).toBe(200);
    await expect(page.locator('#editUserFeedback')).toContainText('saved successfully');
    expect(calls).toBe(1);
    await page.locator('#editUserModal .erp-modal-close').click();
    await expect(page.locator('.erp-user-card[data-username="ucp_browser_created"]')).toBeAttached();
    runDjangoCode("from django.contrib.auth import get_user_model; u=get_user_model().objects.get(username='ucp_browser_created'); assert u.check_password('NewBrowser!368'); assert u.access_changes_received.count()==1");
});

test('protected admin activities remain checked and locked',async({page})=>{
    await users(page);await add(page);await page.locator('#editRole').selectOption('admin');
    for(const key of ['users.manage','users.permissions','erp.view','erp.sessions_terminate']) {
        await expect(choice(page,key)).toBeChecked();await expect(choice(page,key)).toBeDisabled();
    }
    await expect(choice(page,'users.manage').locator('..')).toContainText('Protected administrative access');
});

test('desktop tablet mobile independent scrolling and fixed controls retain the ERP theme',async({page})=>{
    await users(page);await add(page);
    for(const width of [1366,1024,768,390]) {
        await page.setViewportSize({width,height:844});
        if(width===390)await page.locator('#ucpPermissionsTab').click();
        const measure=await page.evaluate(()=>{
            const modal=document.querySelector('#editUserModal')!;
            const columns=document.querySelector('.ucp-columns')!;
            const left=document.querySelector('.ucp-details')!;
            const right=document.querySelector('.ucp-permissions')!;
            const footer=modal.querySelector('footer')!.getBoundingClientRect();
            const toolbar=modal.querySelector('header')!.getBoundingClientRect();
            const before=left.scrollTop;right.scrollTop=600;
            return {overflow:modal.scrollHeight-modal.clientHeight, width:modal.scrollWidth-innerWidth,
                leftStill:left.scrollTop===before, rightScroll:right.scrollTop, footerBottom:footer.bottom, headerTop:toolbar.top,
                ratio:left.getBoundingClientRect().width/columns.getBoundingClientRect().width,
                palette:getComputedStyle(modal.querySelector('.erp-modal-box')!).backgroundColor,
                inherited:getComputedStyle(document.documentElement).getPropertyValue('--erp-card')};
        });
        expect(measure.overflow).toBeLessThanOrEqual(1);expect(measure.width).toBeLessThanOrEqual(1);
        expect(measure.leftStill).toBe(true);expect(measure.rightScroll).toBeGreaterThan(0);
        expect(measure.footerBottom).toBeLessThanOrEqual(844);expect(measure.headerTop).toBeLessThanOrEqual(1);
        if(width>=1024)expect(measure.ratio).toBeCloseTo(.25,1);
        await expect(page.locator('#saveEditUserButton')).toBeVisible();
        if(width===1366||width===390)await page.screenshot({path:`output/user-control-${width===390?'mobile':'desktop'}.png`});
    }
    await page.locator('#ucpDetailsTab').click();await expect(page.locator('#editUsername')).toBeVisible();
    await page.locator('#editUsername').fill('draft remains');
    await page.locator('#ucpPermissionsTab').click();await page.locator('#ucpDetailsTab').click();
    await expect(page.locator('#editUsername')).toHaveValue('draft remains');
});

test('denied navigation and review controls stay hidden and direct calls fail',async({page})=>{
    await loginAs(page,{username:'ucp_browser_denied',password:'UcpBrowser!369'});
    await expect(page.locator('.navbar a[href="/chat/"]')).not.toBeVisible();
    expect((await page.request.get('/api/chat/users/')).status()).toBe(403);
    await page.goto('/car-details/');
    await expect(page.locator('#btnUploadRefImages')).not.toBeVisible();
    expect((await page.request.get('/admin-panel/users/control/')).status()).toBe(403);
    await page.goto('/approvals/?stage=designer&status=all&search=UCP');
    const details=page.locator('a[href*="/design-approvals/"]').filter({hasText:/View Details/}).first();
    await details.click();
    await expect(page.locator('.design-review-page')).toBeVisible();
    await expect(page.locator('.review-decision-form')).toHaveCount(0);
    const id=new URL(page.url()).pathname.split('/').filter(Boolean).pop();
    const csrf=(await page.context().cookies()).find(cookie=>cookie.name==='csrftoken')!.value;
    expect((await page.request.post(`/api/design-images/${id}/approve/`,{headers:{'X-CSRFToken':csrf},data:{stage:'cad',change_type:'minor'}})).status()).toBe(403);
});


test('staff and existing Django groups update eligible choices before the atomic save',async({page})=>{
    await users(page); await add(page);
    await expect(choice(page,'vehicle.create')).toBeDisabled();
    let updated=page.waitForResponse(response=>response.url().includes('/admin-panel/users/control/?'));
    await page.locator('#editIsStaff').check();await updated;
    await expect(page.locator('#editUserModal')).toHaveAttribute('aria-busy','false');
    await expect(choice(page,'vehicle.create')).toBeChecked();await expect(choice(page,'vehicle.create')).toBeEnabled();
    await expect(choice(page,'reference.delete_all')).toBeDisabled();
    updated=page.waitForResponse(response=>response.url().includes('/admin-panel/users/control/?'));
    await page.locator('#ucpGroups').selectOption({label:'UCP file manager'});await updated;
    await expect(page.locator('#editUserModal')).toHaveAttribute('aria-busy','false');
    await expect(choice(page,'reference.delete_all')).toBeEnabled();await expect(choice(page,'reference.delete_all')).toBeChecked();
    await choice(page,'reference.delete_all').uncheck();await choice(page,'chat.send').uncheck();
    await page.locator('#editUsername').fill('ucp_browser_group');await page.locator('#editEmail').fill('group@example.com');
    await page.locator('#editUserPassword').fill('NewGroup!368');await page.locator('#editUserPasswordConfirm').fill('NewGroup!368');
    const saved=page.waitForResponse(response=>response.url().endsWith('/admin-panel/users/save/'));
    await page.locator('#saveEditUserButton').click();expect((await saved).status()).toBe(200);
    await expect(page.locator('#editUserFeedback')).toContainText('saved successfully');
    runDjangoCode("from django.contrib.auth import get_user_model;u=get_user_model().objects.get(username='ucp_browser_group');assert u.is_staff;assert u.groups.filter(name='UCP file manager').exists();assert u.workflow_profile.activity_permissions=={'reference.delete_all':'deny','chat.send':'deny'}");
    updated=page.waitForResponse(response=>response.url().includes('/admin-panel/users/control/?'));
    await page.locator('#editIsStaff').uncheck();await updated;
    await expect(page.locator('#editUserModal')).toHaveAttribute('aria-busy','false');
    await expect(choice(page,'reference.delete_all')).not.toBeChecked();
    await expect(choice(page,'chat.send')).not.toBeChecked();
});
