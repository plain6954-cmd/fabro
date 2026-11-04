import {expect, test, type Page, type BrowserContext} from '@playwright/test';
import {readFileSync} from 'fs';
import {login, loginAs} from '../helpers/auth';
import {runDjangoCode} from '../helpers/django';

let ids: Record<string, number>;
const keys = ['reference.delete_own','reference.delete_all','design.delete_own','design.delete_all','measurement.upload','vehicle.create','vehicle.edit','complaint.export','chat.send'];
test.beforeAll(() => {
    runDjangoCode(`
import json,base64
from pathlib import Path
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group,Permission
from django.core.files.base import ContentFile
from django.utils import timezone
from unittest.mock import patch
from management.services.design_approvals import submit_design_for_approval
from management.models import PatternDesignImage,YearRange
User=get_user_model()
user,_=User.objects.get_or_create(username='live_access_designer')
user.email='live@example.com';user.is_active=True;user.is_staff=True;user.set_password('LiveAccess!369');user.save()
p=user.workflow_profile;p.role='freelance_3d_designer';p.activity_permissions={};p.save()
group,_=Group.objects.get_or_create(name='Live eligible reference manager')
group.permissions.add(Permission.objects.get(codename='delete_patterndesignimage'));user.groups.add(group)
operator,_=User.objects.get_or_create(username='live_access_operator');operator.email='live-operator@example.com';operator.set_password('LiveAccess!369');operator.save()
p=operator.workflow_profile;p.role='factory_executive';p.activity_permissions={'complaint.export':'deny'};p.save()
other,_=User.objects.get_or_create(username='live_access_other')
vehicle=YearRange.objects.first()
ids={'user':user.pk,'vehicle':vehicle.pk}
for key,title,owner,protected,reference in [('own','Live own reference',user,False,True),('other','Live other reference',other,False,True),('protected','Live protected reference',user,True,True),('disposable','Live disposable reference',user,False,True),('design','Live own design',user,False,False)]:
    image,_=PatternDesignImage.objects.get_or_create(title=title,defaults={'vehicle':vehicle,'uploaded_by':owner,'is_reference':reference,'approval_status':'pending'})
    if not image.image:
        image.image.save(key+'.png',ContentFile(base64.b64decode('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+aH1cAAAAASUVORK5CYII=')))
    if protected:image.approved_at=timezone.now();image.save()
    ids[key]=image.pk
Path('output/live-access-fixture.json').write_text(json.dumps(ids))
review,_=PatternDesignImage.objects.get_or_create(title='Live review design',defaults={'vehicle':vehicle,'uploaded_by':user,'approval_status':'pending','image':PatternDesignImage.objects.get(pk=ids['design']).image.name})
with patch('management.services.push_notifications.send_push_to_user'):
    if not review.approval_requests.exists():submit_design_for_approval(review,user)
ids['review']=review.pk
Path('output/live-access-fixture.json').write_text(json.dumps(ids))
`);
    ids = JSON.parse(readFileSync('output/live-access-fixture.json','utf8'));
});
test.beforeEach(() => runDjangoCode(`
from django.contrib.auth import get_user_model
u=get_user_model().objects.get(username='live_access_designer');u.is_active=True;u.save()
p=u.workflow_profile;p.activity_permissions={key:'deny' for key in ${JSON.stringify(keys)}};p.save()
u=get_user_model().objects.get(username='live_access_operator');p=u.workflow_profile;p.activity_permissions={'complaint.export':'deny'};p.save()
u=get_user_model().objects.get(username='fabro_e2e_cad');p=u.workflow_profile;p.activity_permissions={'design_approval.approve':'deny','design_approval.reject':'deny'};p.save()
`));
test.afterAll(() => runDjangoCode(`
from django.contrib.auth import get_user_model
from management.models import PatternDesignImage,ActivityLog
u=get_user_model().objects.get(username='fabro_e2e_cad');p=u.workflow_profile;p.activity_permissions={};p.save()
# Remove only this spec's synthetic records so pending-review counters in the
# existing Control Tower specs stay deterministic when run together.
PatternDesignImage.objects.filter(pk__in=${JSON.stringify(['own','other','protected','disposable','design','review'].map(key=>ids[key]))}).delete()
ActivityLog.objects.filter(user_id=${ids.user},object_type='Design Image',object_name__startswith='Live review design').delete()
`));

async function admin(page: Page) {
    await login(page); await page.goto('/admin_panel/?section=users');
}
async function save(page: Page, changes: Record<string, boolean>, username='live_access_designer') {
    await page.locator(`.erp-user-card[data-username="${username}"]`).click();
    await expect(page.locator('#editUserModal')).toHaveAttribute('aria-busy','false');
    for (const [key, checked] of Object.entries(changes)) await page.locator(`[data-permission="${key}"]`).setChecked(checked);
    const response = page.waitForResponse(r => r.url().endsWith('/admin-panel/users/save/') && r.request().method() === 'POST');
    await page.locator('#saveEditUserButton').click(); expect((await response).status()).toBe(200);
    await expect(page.locator('#editUserFeedback')).toContainText('saved successfully');
    await page.locator('#editUserModal .erp-modal-close').click();
    return Date.now();
}
async function designer(context: BrowserContext, path = '/car-details/', username='live_access_designer') {
    const page = await context.newPage();
    await page.goto('/login/'); await page.getByLabel('Username').fill(username);
    await page.getByLabel('Password').fill('LiveAccess!369');
    await page.getByRole('button',{name:/sign in/i}).click(); await page.waitForURL(url=>!url.pathname.startsWith('/login'));
    await page.goto(path); return page;
}
async function workspace(page: Page) {
    await page.evaluate(id => { (window as any).openVehicleDesignSettings(String(id),'Live access vehicle'); (window as any).switchSidebarSection('3d-design'); },ids.vehicle);
    await expect(page.locator('.ref-image-card').filter({hasText:'Live own reference'})).toBeVisible();
}
const ref = (page: Page, title: string) => page.locator('.ref-image-card').filter({hasText:title}).locator('.tiny-pic-delete-btn');

test('Admin Save grants and revokes own reference Delete across independent devices without reload', async ({browser,page}) => {
    await admin(page);
    const first = await browser.newContext(), second = await browser.newContext();
    try {
        const a = await designer(first), b = await designer(second); await workspace(a); await workspace(b);
        await a.evaluate(() => { (window as any).__liveDocument = 'unchanged'; });
        await expect(ref(a,'Live own reference')).toHaveCount(0); await expect(ref(b,'Live own reference')).toHaveCount(0);
        const grant = await save(page,{'reference.delete_own':true});
        await expect(ref(a,'Live own reference')).toBeVisible({timeout:8000});
        await expect(ref(b,'Live own reference')).toBeVisible({timeout:8000});
        const grantMs = Date.now()-grant;
        for(const target of [a,b]) { await expect(ref(target,'Live other reference')).toHaveCount(0); await expect(ref(target,'Live protected reference')).toHaveCount(0); }
        const revoke = await save(page,{'reference.delete_own':false});
        await expect(ref(a,'Live own reference')).not.toBeVisible({timeout:8000}); await expect(ref(b,'Live own reference')).not.toBeVisible({timeout:8000});
        console.log(`LIVE_LATENCY grant=${grantMs}ms revoke=${Date.now()-revoke}ms (two independent contexts)`);
        expect(await a.evaluate(() => (window as any).__liveDocument)).toBe('unchanged');
        const csrf = (await first.cookies()).find(c => c.name === 'csrftoken')!.value;
        expect((await first.request.post(`/api/design-images/${ids.own}/delete/`,{headers:{'X-CSRFToken':csrf}})).status()).toBe(403);
    } finally {await first.close();await second.close();}
});

test('live grants retain protected/foreign files and eligible delete really succeeds',async({browser,page})=>{
    await admin(page); const context=await browser.newContext();
    try {
        const target=await designer(context);await workspace(target);
        await save(page,{'reference.delete_own':true});await expect(ref(target,'Live disposable reference')).toBeVisible({timeout:8000});
        target.once('dialog',dialog=>dialog.accept());await ref(target,'Live disposable reference').click();
        await expect(target.locator('.ref-image-card').filter({hasText:'Live disposable reference'})).toHaveCount(0);
        await expect(ref(target,'Live protected reference')).toHaveCount(0);await expect(ref(target,'Live other reference')).toHaveCount(0);
    }finally{await context.close();}
});

test('other categories update in place and new same-account tabs receive revocation',async({browser,page})=>{
    await admin(page);const context=await browser.newContext(), operator=await browser.newContext();
    try{
        const target=await designer(context);await workspace(target);
        const vehicle=target.locator('.pattern-add-btn').first(),upload=target.locator('#btnDesignerUploadFile');
        await expect(vehicle).toHaveJSProperty('hidden',true);await expect(upload).toBeVisible();
        await save(page,{'vehicle.create':true,'measurement.upload':true,'design.delete_own':true,'complaint.export':true,'chat.send':true});
        // Pattern actions intentionally sit behind the open Design workspace.
        await expect(vehicle).toHaveJSProperty('hidden',false,{timeout:8000});
        await expect(target.locator(`[data-file-id="${ids.design}"] .tile-delete-x-btn`)).toBeVisible();
        await target.evaluate(()=> (window as any).switchSidebarSection('measurements'));
        await expect(target.locator('#scannedPatternDropzone')).toBeVisible();
        const complaints=await designer(operator,'/complaints/','live_access_operator');
        await expect(complaints.locator('[data-activity="complaint.export"]').first()).toBeHidden();
        await save(page,{'complaint.export':true},'live_access_operator');
        await expect(complaints.locator('[data-activity="complaint.export"]').first()).toBeVisible();
        const chat=await context.newPage();await chat.goto('/chat/');
        await expect(chat.locator('[data-activity="chat.send"]').first()).toBeVisible();
        await save(page,{'vehicle.create':false,'measurement.upload':false,'design.delete_own':false,'complaint.export':false,'chat.send':false});
        await save(page,{'complaint.export':false},'live_access_operator');
        await expect(vehicle).toHaveJSProperty('hidden',true,{timeout:8000});await expect(target.locator('#scannedPatternDropzone')).toBeHidden();
        await expect(complaints.locator('[data-activity="complaint.export"]').first()).toBeHidden();
        await expect(chat.locator('[data-activity="chat.send"]').first()).toBeHidden();
    }finally{await context.close();await operator.close();}
});

test('offline recovery, foreground return and rapid successive saves converge without navigation',async({browser,page})=>{
    await admin(page);const context=await browser.newContext();
    try{
        const target=await designer(context);await workspace(target);const original=target.url();
        await context.setOffline(true);await save(page,{'reference.delete_own':true});await target.waitForTimeout(2200);
        await context.setOffline(false);await expect(ref(target,'Live own reference')).toBeVisible({timeout:10000});
        await save(page,{'reference.delete_own':false});await save(page,{'reference.delete_own':true});await save(page,{'reference.delete_own':false});
        await expect(ref(target,'Live own reference')).not.toBeVisible({timeout:8000});
        await target.evaluate(()=>{Object.defineProperty(document,'hidden',{configurable:true,value:true});document.dispatchEvent(new Event('visibilitychange'));});
        await save(page,{'reference.delete_own':true});
        await target.evaluate(()=>{Object.defineProperty(document,'hidden',{configurable:true,value:false});document.dispatchEvent(new Event('visibilitychange'));});
        await expect(ref(target,'Live own reference')).toBeVisible({timeout:8000});expect(target.url()).toBe(original);
    }finally{await context.close();}
});

test('whole section revocation shows a safe state, restores without reload and deactivation blocks stale actions',async({browser,page})=>{
    await admin(page);const context=await browser.newContext();
    try{
        const target=await designer(context,'/chat/');await target.evaluate(()=>{(window as any).__liveDocument='retained';});
        await save(page,{'chat.view':false});await expect(target.locator('#fabro-access-changed')).toBeVisible({timeout:8000});
        await save(page,{'chat.view':true});await expect(target.locator('#fabro-access-changed')).toHaveCount(0,{timeout:8000});
        expect(await target.evaluate(()=>(window as any).__liveDocument)).toBe('retained');
        await page.locator('.erp-user-card[data-username="live_access_designer"]').click();await expect(page.locator('#editUserModal')).toHaveAttribute('aria-busy','false');
        await page.locator('#ucpActive').uncheck();await page.locator('#saveEditUserButton').click();await expect(page.locator('#editUserFeedback')).toContainText('saved successfully');
        await expect(target.locator('#fabro-access-changed')).toContainText('session is no longer available',{timeout:8000});
    }finally{await context.close();}
});

test('live CAD decision grants preserve remarks and cannot reveal other reviewer stages',async({browser,page})=>{
    await admin(page);const context=await browser.newContext();
    try{
        const target=await context.newPage();await loginAs(target,{username:'fabro_e2e_cad',password:'FabroWorkflow!234'});
        await target.goto(`/design-approvals/${ids.review}/`);
        const form=target.locator('#cadReviewForm'),approve=form.locator('[value="approved"]');
        await expect(form).toBeHidden();await expect(approve).toBeHidden();
        await save(page,{'design_approval.approve':true},'fabro_e2e_cad');
        await expect(approve).toBeVisible({timeout:8000});await expect(target.locator('#edReviewForm, #mdReviewForm')).toHaveCount(0);
        await form.locator('textarea').fill('Retain my unsaved live review remark');
        await save(page,{'design_approval.approve':false},'fabro_e2e_cad');
        await expect(approve).toBeHidden({timeout:8000});await expect(form.locator('textarea')).toHaveValue('Retain my unsaved live review remark');
    }finally{await context.close();}
});

test('failed Admin save does not propagate unsaved choices or reload the designer',async({browser,page})=>{
    await admin(page);const context=await browser.newContext();
    try{
        const target=await designer(context);await workspace(target);
        const before=await target.evaluate(()=>(window as any).fabroActivityAccess.version);
        await page.locator('.erp-user-card[data-username="live_access_designer"]').click();await expect(page.locator('#editUserModal')).toHaveAttribute('aria-busy','false');
        await page.locator('[data-permission="reference.delete_own"]').check();
        await page.locator('#editUsername').fill('live_access_other');
        const response=page.waitForResponse(r=>r.url().endsWith('/admin-panel/users/save/')&&r.request().method()==='POST');
        await page.locator('#saveEditUserButton').click();expect((await response).status()).toBe(400);
        await target.waitForTimeout(2300);await expect(ref(target,'Live own reference')).toHaveCount(0);
        expect(await target.evaluate(()=>(window as any).fabroActivityAccess.version)).toBe(before);
        page.once('dialog',dialog=>dialog.accept());await page.locator('#editUserModal .erp-modal-close').click();
    }finally{await context.close();}
});
