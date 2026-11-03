import {expect,test,type Page} from '@playwright/test';
import {readFileSync} from 'fs';
import {runDjangoCode} from '../helpers/django';
let ids:Record<string,number>;
test.beforeAll(()=>{
  runDjangoCode(`
import json
from pathlib import Path
from unittest.mock import patch
from PIL import Image
from django.conf import settings
from django.contrib.auth import get_user_model
from management.models import PatternDesignImage, WorkflowRoles, ApprovalRoles, YearRange
from management.services.design_approvals import submit_design_for_approval,record_design_review_decision
User=get_user_model()
for name,role,approval in [('form_style_admin',WorkflowRoles.ADMIN,''),('form_style_designer',WorkflowRoles.FREELANCE_3D_DESIGNER,''),('form_style_md',WorkflowRoles.APPROVER,ApprovalRoles.MD)]:
    user,_=User.objects.get_or_create(username=name);user.set_password('FabroWorkflow!234');user.save()
    p=user.workflow_profile;p.role=role;p.approval_role=approval;p.save()
folder=Path(settings.MEDIA_ROOT)/'form-style-test';folder.mkdir(parents=True,exist_ok=True)
Image.new('RGB',(320,200),'#897c76').save(folder/'actual.png')
cad=User.objects.get(username='fabro_e2e_cad');md=User.objects.get(username='form_style_md')
designer=User.objects.get(username='form_style_designer');vehicle=YearRange.objects.first()
ids={}
with patch('management.services.push_notifications.send_push_to_user'):
    image=PatternDesignImage.objects.create(vehicle=vehicle,uploaded_by=cad,title='E2E review form skipped.png',image='form-style-test/actual.png')
    submit_design_for_approval(image,cad);record_design_review_decision(image,md,'approved',change_type='minor');ids['skipped']=image.pk
    image=PatternDesignImage.objects.create(vehicle=vehicle,uploaded_by=designer,title='E2E review form cycles.png',image='form-style-test/actual.png')
    submit_design_for_approval(image,designer);record_design_review_decision(image,cad,'rejected',change_type='major')
    submit_design_for_approval(image,designer,is_resubmission=True);ids['cycles']=image.pk
(settings.BASE_DIR/'output/review-form-style-ids.json').write_text(json.dumps(ids))
`);
  ids=JSON.parse(readFileSync('output/review-form-style-ids.json','utf8'));
});
async function open(page:Page,id:number){
  await page.goto('/login/');await page.getByLabel('Username').fill('form_style_admin');
  await page.getByLabel('Password').fill('FabroWorkflow!234');await page.getByRole('button',{name:/sign in/i}).click();
  await expect(page).not.toHaveURL(/\/login\//);await page.goto('/car-details/?vehicle_id=1#design-options');
  await page.locator('#sidebarNav3DDesignBtn').click();
  await expect(page.locator(`.fabro-design-tile[data-file-id="${id}"]`)).toBeAttached();
  await page.evaluate(file=>(window as any).openApprovalDrawer(file),id);
  await expect(page.locator('#designApprovalDrawer')).toHaveClass(/is-open/);
}
test('drawer segments retain disabled roles and align classification, remarks, mic and actions at all widths',async({page})=>{
  const errors:string[]=[];page.on('pageerror',error=>errors.push(error.message));
  await open(page,ids.skipped);
  const selector=page.locator('#drawerReviewRoleSelector');
  const cad=selector.locator('[data-stage="cad"]'),ed=selector.locator('[data-stage="ed"]'),md=selector.locator('[data-stage="md"]');
  await expect(cad).toBeDisabled();await expect(md).toBeDisabled();await expect(ed).toBeEnabled();
  await expect(cad).toContainText('Skipped — Uploader');await expect(md).toContainText('completed');
  await expect(selector.locator('[aria-pressed="true"]')).toHaveCount(0);
  await ed.click();await expect(ed).toHaveAttribute('aria-pressed','true');
  expect(await ed.evaluate(el=>getComputedStyle(el).borderColor)).not.toBe(await cad.evaluate(el=>getComputedStyle(el).borderColor));
  await page.evaluate(()=>document.querySelector<HTMLButtonElement>('#drawerReviewRoleSelector [data-stage="cad"]')!.click());
  await expect(ed).toHaveAttribute('aria-pressed','true');
  await expect(page.locator('#radioChangeTypeMinor')).toBeChecked();
  await page.locator('#radioChangeTypeMajor').check();await expect(page.locator('#radioChangeTypeMajor')).toBeChecked();
  for(const width of [320,375,768,1366]){
    await page.setViewportSize({width,height:960});
    for(const light of [false,true]){
      await page.evaluate(value=>document.body.classList.toggle('light-mode',value),light);
      await selector.scrollIntoViewIfNeeded();
      const stages=await selector.locator('button').evaluateAll(buttons=>buttons.map(button=>{const r=button.getBoundingClientRect();const s=getComputedStyle(button);return {height:r.height,bg:s.backgroundColor,radius:s.borderRadius,right:r.right,left:r.left};}));
      expect(Math.max(...stages.map(x=>x.height))-Math.min(...stages.map(x=>x.height))).toBeLessThan(2);
      for(const stage of stages){expect(stage.bg).not.toBe('rgb(255, 255, 255)');expect(parseFloat(stage.radius)).toBeGreaterThanOrEqual(6);expect(stage.right).toBeLessThanOrEqual(width);expect(stage.left).toBeGreaterThanOrEqual(0);}
      const labels=await page.locator('#drawerDecisionBox .change-type-option').evaluateAll(nodes=>nodes.map(n=>n.getBoundingClientRect().height));
      expect(Math.abs(labels[0]-labels[1])).toBeLessThan(2);expect(labels[0]).toBeGreaterThanOrEqual(44);
      await page.locator('#designDrawerDecisionRemarks').focus();
      await expect(page.locator('#designDrawerDecisionRemarks')).toHaveCSS('border-color','rgb(193, 154, 170)');
      await expect.poll(()=>page.locator('#designDrawerDecisionRemarks').evaluate(el=>getComputedStyle(el).boxShadow)).toContain('2px');
      const remark=await page.locator('#designDrawerDecisionRemarks').evaluate(el=>{const s=getComputedStyle(el);return {shadow:s.boxShadow,border:s.borderColor};});
      expect(remark.shadow).toContain('2px');expect(remark.shadow).not.toContain('4px');expect(remark.border).toBe('rgb(193, 154, 170)');
      const alignment=await page.locator('#drawerDecisionBox .review-remarks-input').evaluate(el=>{const field=el.querySelector('textarea')!.getBoundingClientRect(),mic=el.querySelector('[data-voice-action="record"]')!.getBoundingClientRect();return {dy:Math.abs(field.y-mic.y),size:mic.width};});
      expect(alignment.dy).toBeLessThan(2);expect(alignment.size).toBe(42);
      const actions=await page.locator('.drawer-decision-actions button').evaluateAll(nodes=>nodes.map(n=>n.getBoundingClientRect().height));
      expect(Math.abs(actions[0]-actions[1])).toBeLessThan(2);expect(actions[0]).toBeGreaterThanOrEqual(44);
      expect(await page.locator('#designApprovalDrawer').evaluate(el=>el.scrollWidth-el.clientWidth)).toBeLessThanOrEqual(1);
      expect(await page.evaluate(()=>document.documentElement.scrollWidth-innerWidth)).toBeLessThanOrEqual(1);
    }
  }
  await page.setViewportSize({width:1366,height:1000});await page.evaluate(()=>document.body.classList.remove('light-mode'));
  await page.locator('#drawerDecisionBox').scrollIntoViewIfNeeded();await page.locator('#drawerDecisionBox').screenshot({path:'output/design-review-form-fixed.png'});
  expect(errors).toEqual([]);
});
test('history cycles keep ordering and approval submits with existing stage, classification and loading behavior',async({page})=>{
  await open(page,ids.cycles);
  const cycles=page.locator('#drawerHistoryTimeline .drawer-history-cycle');
  await expect(cycles).toHaveCount(2);await expect(cycles.nth(0)).toContainText('Cycle #2');await expect(cycles.nth(1)).toContainText('Cycle #1');
  await expect(cycles.nth(1).locator('[data-review-status="rejected"]')).toContainText('CAD');
  await page.locator('#drawerReviewRoleSelector [data-stage="cad"]').click();
  await page.locator('#radioChangeTypeMajor').check();await page.locator('#designDrawerDecisionRemarks').fill('Keep original submission behavior');
  let release!:()=>void;const gate=new Promise<void>(resolve=>{release=resolve;});
  await page.route(`**/api/design-images/${ids.cycles}/approve/`,async route=>{await gate;await route.continue();});
  const response=page.waitForResponse(r=>r.url().includes(`/api/design-images/${ids.cycles}/approve/`));
  await page.locator('#drawerBtnApprove').click();await expect(page.locator('#drawerBtnApprove')).toBeDisabled();await expect(page.locator('#drawerBtnReject')).toBeDisabled();
  release();const saved=await response;expect(saved.status()).toBe(200);expect(saved.request().postDataJSON().stage).toBe('cad');expect(saved.request().postDataJSON().change_type).toBe('major');
  await expect(page.locator('#drawerCadStatusBadge')).toHaveText('APPROVED');
  await expect(page.locator('#drawerCadRemarks')).toContainText('Keep original submission behavior');
  await expect(page.locator('#drawerHistoryTimeline .drawer-history-cycle')).toHaveCount(2);
  await page.locator('#drawerReviewRoleSelector [data-stage="cad"]').isDisabled().then(value=>expect(value).toBe(true));
  await expect(page.locator('#drawerReviewRoleSelector [data-stage="ed"]')).toBeEnabled();
});

test('drawer stage toggling keeps each reviewer text and classification draft without submitting',async({page})=>{
 await open(page,ids.cycles);
 const mutations:string[]=[];page.on('request',request=>{if(request.method()==='POST')mutations.push(request.url());});
 const stage=(role:string)=>page.locator(`#drawerReviewRoleSelector [data-stage="${role}"]`);
 const remarks=page.locator('#designDrawerDecisionRemarks');
 // CAD may already be completed by the preceding isolated submission test; ED and MD remain pending.
 await stage('ed').click();await remarks.fill('  Unsaved ED draft\nkeep exact spacing  ');await page.locator('#radioChangeTypeMajor').check();
 await stage('ed').click();await expect(remarks).toHaveValue('  Unsaved ED draft\nkeep exact spacing  ');await expect(page.locator('#radioChangeTypeMajor')).toBeChecked();
 await stage('md').click();await expect(remarks).toHaveValue('');await expect(page.locator('#radioChangeTypeMinor')).toBeChecked();await remarks.fill('Separate MD draft');
 await stage('ed').click();await expect(remarks).toHaveValue('  Unsaved ED draft\nkeep exact spacing  ');await expect(page.locator('#radioChangeTypeMajor')).toBeChecked();
 await stage('md').click();await expect(remarks).toHaveValue('Separate MD draft');await expect(page.locator('#radioChangeTypeMinor')).toBeChecked();
 await page.getByRole('button',{name:'Compare files',exact:true}).click();await expect(page.locator('#designComparisonViewer')).toBeVisible();await page.keyboard.press('Escape');
 await expect(remarks).toHaveValue('Separate MD draft');
 await page.evaluate(id=>(window as any).selectDrawerFile(id),ids.skipped);await expect(remarks).toHaveValue('');await expect(page.locator('#radioChangeTypeMinor')).toBeChecked();
 expect(mutations).toEqual([]);
});
