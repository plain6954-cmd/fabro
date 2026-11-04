import { expect, test, type Page } from '@playwright/test';
import { readFileSync } from 'fs';
import { runDjangoCode } from '../helpers/django';
import { workflowUsers } from '../helpers/testData';
import { mockReviewRecorder } from '../helpers/mockReviewRecorder';

let ids: Record<string, number>;
let wav: number[];
test.beforeAll(() => {
  runDjangoCode(`
import io, json, math, wave
from array import array
from pathlib import Path
from shutil import copyfile
from unittest.mock import patch
from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from management.models import PatternDesignImage, WorkflowRoles, YearRange
from management.services.design_approvals import submit_design_for_approval
from management.services.design_review_voice import record_design_review_with_voice
user, _ = get_user_model().objects.get_or_create(username='voice_browser_designer')
user.set_password('FabroWorkflow!234'); user.save()
p=user.workflow_profile; p.role=WorkflowRoles.FREELANCE_3D_DESIGNER; p.save()
output=io.BytesIO()
with wave.open(output, 'wb') as target:
    target.setnchannels(1); target.setsampwidth(2); target.setframerate(16000)
    target.writeframes(array('h', (int(8000*math.sin(n/15)) for n in range(64000))).tobytes())
(settings.BASE_DIR/'output/voice-browser.wav').write_bytes(output.getvalue())
ids={}
target=Path(settings.MEDIA_ROOT)/'voice-review-fixture'
target.mkdir(parents=True,exist_ok=True)
copyfile(settings.BASE_DIR/'media/pattern_designs/2026/10/test_designer_fix.png',target/'existing.png')
with patch('management.services.push_notifications.send_push_to_user'):
    for name in ['native', 'drawer', 'cancel', 'denied']:
        image=PatternDesignImage.objects.create(vehicle=YearRange.objects.first(), uploaded_by=user,
            image='voice-review-fixture/existing.png', title='E2E voice '+name+'.png')
        submit_design_for_approval(image,user); ids[name]=image.pk
        if name=='native':
            ed=get_user_model().objects.get(username='fabro_e2e_ed')
            record_design_review_with_voice(image,ed,'approved',change_type='minor',stage='ed',
                voice_note=SimpleUploadedFile('note.wav',output.getvalue()))
(settings.BASE_DIR/'output/voice-browser-ids.json').write_text(json.dumps(ids))
`);
  ids = JSON.parse(readFileSync('output/voice-browser-ids.json', 'utf8'));
  wav = Array.from(readFileSync('output/voice-browser.wav'));
});

async function login(page: Page, username = workflowUsers.cad.username) {
  await page.goto('/login/');
  await page.getByLabel('Username').fill(username);
  await page.getByLabel('Password').fill('FabroWorkflow!234');
  await page.getByRole('button', { name: /sign in/i }).click();
  await expect(page).not.toHaveURL(/\/login\//);
}

const mockRecorder = (page:Page) => mockReviewRecorder(page, wav);

const mic = (page: Page) => page.locator('#cadReviewForm [data-voice-action="record"]');
async function record(page: Page, root = page.locator('#cadReviewForm')) {
  await root.locator('[data-voice-action="record"]').click();
  await expect(root.locator('[data-voice-recording]')).toBeVisible();
  await root.locator('[data-voice-action="stop"]').click();
  await expect(root.locator('[data-voice-preview]')).toBeVisible();
}

test('native recording, live state, preview, voice-only submit, private history and real playback', async ({ page }) => {
  const errors: string[]=[]; page.on('pageerror', err => errors.push(err.message));
  await mockRecorder(page); await login(page);
  await page.goto(`/design-approvals/${ids.native}/`);
  expect(await page.evaluate(() => (window as any).__voice.calls)).toBe(0);
  await mic(page).click();
  await expect(page.locator('[data-voice-recording]:visible')).toBeVisible();
  await expect(page.locator('[data-voice-timer]:visible')).toHaveText('0:01', { timeout: 3000 });
  expect(await page.evaluate(() => (window as any).__voice.mime)).toContain('mp4');
  await page.locator('#cadReviewForm [data-voice-action="stop"]').click();
  const preview=page.locator('#cadReviewForm .review-voice-bubble');
  await expect(preview).toBeVisible();
  await page.locator('#review-tab-ed').click();
  await expect(preview).toBeHidden();
  await page.locator('#review-tab-cad').click();
  await expect(preview).toBeVisible();
  expect(await page.locator('#cadReviewForm input[name="voice_note"]').evaluate((el: HTMLInputElement) => el.files!.length)).toBe(1);
  expect(await page.evaluate(() => (window as any).__voice.stopped)).toBe(1);
  await preview.getByRole('button', {name:'Play voice note',exact:true}).click();
  await expect(preview.locator('audio')).toHaveJSProperty('paused',false);
  await expect.poll(() => preview.locator('input[type="range"]').inputValue()).not.toBe('0');
  await preview.getByRole('button',{name:'Pause voice note',exact:true}).click();
  await expect(preview.locator('audio')).toHaveJSProperty('paused',true);
  await preview.locator('input[type="range"]').fill('500');
  await expect.poll(() => preview.locator('audio').evaluate(el => (el as HTMLAudioElement).currentTime)).toBeGreaterThan(1.8);
  await page.locator('#cadReviewForm button[value="approved"]').click();
  await expect(page.locator('#cadReviewForm')).toHaveCount(0);
  await page.locator('.review-history summary').click();
  const bubbles=page.locator('.review-history .review-voice-bubble');
  await expect(bubbles).toHaveCount(2);
  await expect(page.locator('#review-cad .voice-message-meta')).toContainText('fabro_e2e_cad');
  const first=bubbles.nth(0),second=bubbles.nth(1);
  await first.getByRole('button',{name:'Play voice note',exact:true}).click();
  await expect(first.locator('audio')).toHaveJSProperty('paused',false);
  await second.getByRole('button',{name:'Play voice note',exact:true}).click();
  await expect(second.locator('audio')).toHaveJSProperty('paused',false);
  await expect(first.locator('audio')).toHaveJSProperty('paused',true);
  await second.locator('input[type="range"]').fill('600');
  await expect.poll(() => second.locator('audio').evaluate(el => (el as HTMLAudioElement).currentTime)).toBeGreaterThan(2);
  await second.locator('audio').evaluate(el => { const a=el as HTMLAudioElement; a.pause(); a.currentTime=1; a.dispatchEvent(new Event('timeupdate')); });
  await expect(second.locator('input[type="range"]')).toHaveValue('250');
  expect(errors).toEqual([]);
});

test('cancel, re-record, discard, oversize, timer limit and navigation release resources', async ({page}) => {
  await mockRecorder(page); await login(page); await page.goto(`/design-approvals/${ids.cancel}/`);
  const root=page.locator('#cadReviewForm');
  await mic(page).click(); await root.locator('[data-voice-action="cancel"]').click();
  await expect(root.locator('[data-voice-preview]')).not.toBeVisible();
  expect(await page.evaluate(() => (window as any).__voice.stopped)).toBe(1);
  await record(page); await record(page);
  expect(await root.locator('input[name="voice_note"]').evaluate((el: HTMLInputElement)=>el.files!.length)).toBe(1);
  await root.locator('[data-voice-action="discard"]').click();
  expect(await root.locator('input[name="voice_note"]').evaluate((el: HTMLInputElement)=>el.files!.length)).toBe(0);
  await page.evaluate(()=>{(window as any).__voice.oversize=true;});
  await mic(page).click(); await root.locator('[data-voice-action="stop"]').click();
  await expect(root.locator('[data-voice-error]')).toContainText('5 MB');
  await page.evaluate(()=>{(window as any).__voice.oversize=false;});
  await page.clock.install();
  await mic(page).click(); await page.clock.runFor(60100);
  await expect(root.locator('[data-voice-preview]')).toBeVisible();
  await mic(page).click();
  const before=await page.evaluate(()=>(window as any).__voice.stopped);
  await page.evaluate(()=>window.dispatchEvent(new Event('pagehide')));
  expect(await page.evaluate(()=>(window as any).__voice.stopped)).toBe(before+1);
  await expect(root.locator('[data-voice-recording]')).not.toBeVisible();
});

test('denied permission and unsupported browsers keep text reviews usable; pending permission is cleaned',async({page})=>{
  await mockRecorder(page); await login(page); await page.goto(`/design-approvals/${ids.denied}/`);
  const root=page.locator('#cadReviewForm');
  await page.evaluate(()=>{(window as any).__voice.denied=true;});
  await mic(page).click();
  await expect(root.locator('[data-voice-error]')).toContainText('permission was denied');
  await page.evaluate(()=>{(window as any).__voice.denied=false;(window as any).__voice.pending=true;});
  await mic(page).click();
  await expect.poll(()=>page.evaluate(()=>(window as any).__voice.calls)).toBe(2);
  await page.evaluate(()=>{window.dispatchEvent(new Event('pagehide'));(window as any).__voice.resolve();});
  await expect.poll(()=>page.evaluate(()=>(window as any).__voice.stopped)).toBe(1);
  await root.locator('textarea').fill('Text remains available');
  await root.locator('button[value="approved"]').click();
  await expect(page.locator('#review-cad')).toContainText('Text remains available');
  await page.addInitScript(()=>{(window as any).MediaRecorder=undefined;});
  await page.goto(`/design-approvals/${ids.cancel}/`);
  await expect(mic(page)).toBeDisabled();
  await page.evaluate(()=>window.dispatchEvent(new Event('pagehide')));
  await expect(mic(page)).toBeDisabled();
  await expect(page.locator('#cadCommentInput')).toBeEditable();
});

test('drawer multipart review, microphone close cleanup, responsive preview and background sync preserve draft',async({page})=>{
  test.setTimeout(90_000);
  const errors:string[]=[];page.on('pageerror',err=>errors.push(err.message));
  await mockRecorder(page); await login(page); await page.goto('/car-details/?vehicle_id=1#design-options');
  await page.locator('#sidebarNav3DDesignBtn').click();
  await expect(page.locator(`.fabro-design-tile[data-file-id="${ids.drawer}"]`)).toBeVisible();
  await page.evaluate(id=>(window as any).openApprovalDrawer(id),ids.drawer);
  const root=page.locator('#drawerDecisionBox');
  await root.locator('[data-voice-action="record"]').click();
  await page.evaluate(()=>(window as any).closeApprovalDrawer());
  expect(await page.evaluate(()=>(window as any).__voice.stopped)).toBe(1);
  await page.evaluate(id=>(window as any).openApprovalDrawer(id),ids.drawer);
  await record(page,root);
  await page.locator('#designDrawerDecisionRemarks').fill('Drawer combined voice and text');
  const draft=await root.locator('input[name="voice_note"]').evaluate((el:HTMLInputElement)=>el.files![0].size);
  await page.waitForResponse(resp=>resp.url().includes('gallery_sync=1')&&resp.status()===304,{timeout:20000});
  await expect(page.locator('#designDrawerDecisionRemarks')).toHaveValue('Drawer combined voice and text');
  expect(await root.locator('input[name="voice_note"]').evaluate((el:HTMLInputElement)=>el.files![0].size)).toBe(draft);
  for(const width of [375,768,1366]){
    await page.setViewportSize({width,height:900});
    const fits=await root.locator('.review-voice-bubble').evaluate(el=>{
      const r=el.getBoundingClientRect();return r.width>0&&r.right<=innerWidth+1&&r.left>=0;
    });expect(fits).toBe(true);
  }
  const request=page.waitForRequest(req=>req.url().includes(`/api/design-images/${ids.drawer}/approve/`));
  await page.locator('#drawerBtnApprove').click();
  expect((await request).headers()['content-type']).toContain('multipart/form-data');
  await expect(page.locator('#drawerCadRemarks')).toContainText('Drawer combined voice and text');
  await expect(page.locator('#drawerHistoryTimeline .review-voice-bubble')).toHaveCount(1);
  expect(errors).toEqual([]);
});
