import {expect, test, type Page} from '@playwright/test';
import {loginAs} from '../helpers/auth';
import {runDjangoCode} from '../helpers/django';

test.beforeAll(() => runDjangoCode(`
from django.contrib.auth import get_user_model
User=get_user_model()
for name,role,su in [('su_browser_actor','admin',True),('su_browser_admin','admin',False),('su_browser_target','factory_viewer',False),('su_browser_locked','admin',False)]:
    u,_=User.objects.get_or_create(username=name);u.email=name+'@example.com';u.is_superuser=su;u.is_staff=su;u.is_active=True;u.set_password('SuBrowser!369');u.save()
    p=u.workflow_profile;p.role=role;p.activity_permissions={};p.save()
`));
test.beforeEach(() => runDjangoCode(`
from django.contrib.auth import get_user_model
User=get_user_model()
for name in ['su_browser_actor','su_browser_admin','su_browser_target','su_browser_locked']:
    u=User.objects.get(username=name);p=u.workflow_profile;p.activity_permissions={};p.save()
`));
const choice=(page:Page,key:string)=>page.locator(`[data-permission="${key}"]`);
async function users(page:Page, actor='su_browser_actor') {
    await loginAs(page,{username:actor,password:'SuBrowser!369'});await page.goto('/admin_panel/?section=users');
}
async function edit(page:Page,name:string) {
    await page.locator(`.erp-user-card[data-username="${name}"]`).click();
    await expect(page.locator('#editUserModal')).toHaveAttribute('aria-busy','false');
}
async function save(page:Page) {
    const saved=page.waitForResponse(response=>response.url().endsWith('/admin-panel/users/save/')&&response.request().method()==='POST');
    await page.locator('#saveEditUserButton').click();expect((await saved).status()).toBe(200);
    await expect(page.locator('#editUserFeedback')).toContainText('saved successfully');
}

test('all 103 checkboxes are editable by Superuser and protected denials persist on reopen',async({page})=>{
    await users(page);await edit(page,'su_browser_locked');
    await expect(page.locator('[data-permission]')).toHaveCount(103);
    await expect(page.locator('[data-permission]:disabled')).toHaveCount(0);
    await choice(page,'erp.view').uncheck();await choice(page,'users.permissions').uncheck();await save(page);
    await page.locator('#editUserModal .erp-modal-close').click();await edit(page,'su_browser_locked');
    await expect(choice(page,'erp.view')).not.toBeChecked();await expect(choice(page,'users.permissions')).not.toBeChecked();
    runDjangoCode("from django.contrib.auth import get_user_model;from management.services.activity_permissions import granted;u=get_user_model().objects.get(username='su_browser_locked');assert u.workflow_profile.activity_permissions['erp.view']=='deny';assert not granted(u,'erp.view')");
    await choice(page,'erp.view').check();await choice(page,'users.permissions').check();await save(page);
    runDjangoCode("from django.contrib.auth import get_user_model;from management.services.activity_permissions import granted;u=get_user_model().objects.get(username='su_browser_locked');assert granted(u,'erp.view');assert granted(u,'users.permissions')");
});

test('explicit role-ineligible allows persist and nested dependencies enable and disable together',async({page})=>{
    await users(page);await edit(page,'su_browser_target');
    await choice(page,'design_approval.voice').check();
    for(const key of ['design_approval.voice','design_approval.comment','design_approval.view'])await expect(choice(page,key)).toBeChecked();
    await choice(page,'design_approval.view').uncheck();
    for(const key of ['design_approval.voice','design_approval.comment','design_approval.view'])await expect(choice(page,key)).not.toBeChecked();
    await choice(page,'users.permissions').check();await choice(page,'design_approval.voice').check();await save(page);
    await page.locator('#editUserModal .erp-modal-close').click();await edit(page,'su_browser_target');
    for(const key of ['users.permissions','design_approval.voice','design_approval.comment','design_approval.view'])await expect(choice(page,key)).toBeChecked();
    await expect(choice(page,'users.permissions').locator('..')).toContainText('business rules still apply');
    runDjangoCode("from django.contrib.auth import get_user_model;from management.services.activity_permissions import granted;u=get_user_model().objects.get(username='su_browser_target');assert u.workflow_profile.activity_permissions['users.permissions']=='allow';assert granted(u,'users.permissions');assert u.workflow_profile.role=='factory_viewer';assert not u.is_superuser");
});

test('own disabled administration recovers through the actual Profile link and permission-only UI',async({page})=>{
    await users(page);await edit(page,'su_browser_actor');
    for(const key of ['users.manage','erp.view','users.permissions'])await choice(page,key).uncheck();
    await save(page);await expect(page.locator('[data-ucp-recovery]')).toBeVisible();
    await expect(page.locator('#editUsername')).toBeDisabled();await expect(page.locator('#editIsSuperuser')).toBeDisabled();
    await expect(page.locator('[data-permission]:disabled')).toHaveCount(0);
    await page.locator('#editUserModal .erp-modal-close').click();await page.goto('/profile/');
    await page.getByTestId('recover-own-activity-access').click();
    await expect(page.locator('#editUserModal')).toBeVisible();await expect(page.locator('[data-ucp-recovery]')).toBeVisible();
    await expect(page.locator('.erp-user-card')).toHaveCount(1);
    const payload=page.waitForRequest(request=>request.url().endsWith('/admin-panel/users/save/')&&request.method()==='POST');
    for(const key of ['users.manage','erp.view','users.permissions'])await choice(page,key).check();await save(page);
    const body=(await payload).postData()!;
    expect(body).not.toContain('name="role"');expect(body).not.toContain('name="is_superuser"');expect(body).not.toContain('name="username"');
    await expect(page.locator('[data-ucp-recovery]')).toBeHidden();await expect(page.locator('#editUsername')).toBeEnabled();
    runDjangoCode("from django.contrib.auth import get_user_model;from management.services.activity_permissions import granted;u=get_user_model().objects.get(username='su_browser_actor');assert u.is_active and u.is_superuser;assert all(granted(u,k) for k in ['users.manage','erp.view','users.permissions'])");
});

test('ordinary Admin sees saved locked states and cannot erase Superuser-managed overrides',async({page})=>{
    runDjangoCode("from django.contrib.auth import get_user_model;User=get_user_model();p=User.objects.get(username='su_browser_locked').workflow_profile;p.activity_permissions={'erp.view':'deny'};p.save();p=User.objects.get(username='su_browser_target').workflow_profile;p.activity_permissions={'users.permissions':'allow'};p.save()");
    await users(page,'su_browser_admin');await edit(page,'su_browser_locked');
    await expect(choice(page,'erp.view')).not.toBeChecked();await expect(choice(page,'erp.view')).toBeDisabled();
    await expect(choice(page,'erp.view').locator('..')).toContainText('Superuser-managed: Deny');
    page.once('dialog',dialog=>dialog.accept());await page.locator('[data-ucp-reset]').click();
    await expect(choice(page,'erp.view')).not.toBeChecked();await choice(page,'chat.send').uncheck();await save(page);
    await page.locator('#editUserModal .erp-modal-close').click();await edit(page,'su_browser_target');
    await expect(choice(page,'users.permissions')).toBeChecked();await expect(choice(page,'users.permissions')).toBeDisabled();
    await choice(page,'chat.send').uncheck();await save(page);
    runDjangoCode("from django.contrib.auth import get_user_model;User=get_user_model();assert User.objects.get(username='su_browser_locked').workflow_profile.activity_permissions=={'erp.view':'deny','chat.send':'deny'};assert User.objects.get(username='su_browser_target').workflow_profile.activity_permissions=={'users.permissions':'allow','chat.send':'deny'}");
});
