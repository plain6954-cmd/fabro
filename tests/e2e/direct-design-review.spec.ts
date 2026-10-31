import { expect, test, type Page } from '@playwright/test';
import { readFileSync } from 'fs';
import { runDjangoCode } from '../helpers/django';
import { workflowUsers } from '../helpers/testData';

let ids: Record<string, number>;
test.beforeAll(() => {
  runDjangoCode(`
import io, json
from pathlib import Path
from unittest.mock import patch
from PIL import Image, ImageDraw
from pypdf import PdfWriter
from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.files.base import ContentFile
from management.models import PatternDesignImage, PatternDesignFolder, WorkflowRoles, YearRange
from management.services.design_approvals import submit_design_for_approval
from management.services.design_pdfs import design_file_storage
user,_=get_user_model().objects.get_or_create(username='direct_review_designer')
user.set_password('FabroWorkflow!234'); user.save()
p=user.workflow_profile; p.role=WorkflowRoles.FREELANCE_3D_DESIGNER; p.save()
admin,_=get_user_model().objects.get_or_create(username='direct_review_admin')
admin.set_password('FabroWorkflow!234'); admin.save()
p=admin.workflow_profile; p.role=WorkflowRoles.ADMIN; p.save()
vehicle=YearRange.objects.first()
folder=PatternDesignFolder.objects.create(vehicle=vehicle,name='Direct review test')
target=Path(settings.MEDIA_ROOT)/'direct-review'; target.mkdir(parents=True,exist_ok=True)
image=Image.new('RGB',(960,640),'#b1a7a1'); draw=ImageDraw.Draw(image)
draw.rounded_rectangle((250,65,710,390),radius=80,fill='#625956',outline='#eee1d5',width=4)
draw.rounded_rectangle((200,400,760,580),radius=55,fill='#736761',outline='#eee1d5',width=4)
for y in range(125,380,55): draw.line((280,y,680,y),fill='#aea198',width=3)
image.save(target/'Seat drawing.png')
writer=PdfWriter(); writer.add_blank_page(width=600,height=800); writer.add_blank_page(width=600,height=800)
blob=io.BytesIO(); writer.write(blob)
name=design_file_storage('private_design_pdfs/direct-review.pdf').save('private_design_pdfs/direct-review.pdf',ContentFile(blob.getvalue()))
ids={}
with patch('management.services.push_notifications.send_push_to_user'):
    for title,file in [('image','direct-review/Seat drawing.png'),('pdf',name),('admin','direct-review/Seat drawing.png')]:
        record=PatternDesignImage.objects.create(folder=folder,vehicle=vehicle,uploaded_by=user,
            title='E2E direct review '+title+('.pdf' if title=='pdf' else '.png'),image=file,file_size=len(blob.getvalue()) if title=='pdf' else (target/'Seat drawing.png').stat().st_size)
        submit_design_for_approval(record,user); ids[title]=record.pk
    cad=get_user_model().objects.get(username='fabro_e2e_cad')
    record=PatternDesignImage.objects.create(vehicle=vehicle,uploaded_by=cad,title='E2E direct skipped.png',image='direct-review/Seat drawing.png')
    submit_design_for_approval(record,cad); ids['skipped']=record.pk
(settings.BASE_DIR/'output/direct-review-ids.json').write_text(json.dumps(ids))
`);
  ids=JSON.parse(readFileSync('output/direct-review-ids.json','utf8'));
});
async function login(page: Page, username=workflowUsers.cad.username, password=workflowUsers.cad.password){
  await page.goto('/login/');await page.getByLabel('Username').fill(username);await page.getByLabel('Password').fill(password);
  await page.getByRole('button',{name:/sign in/i}).click();await expect(page).not.toHaveURL(/\/login\//);
}

test('one click opens selected review, safe queue state survives refresh and canonical Back',async({page})=>{
  const errors:string[]=[]; page.on('pageerror',err=>errors.push(err.message));
  await login(page);await page.goto('/approvals/?stage=designer&status=all&search=E2E+direct+review+image');
  const card=page.locator(`#card-design-${ids.image}`);
  await card.getByRole('link',{name:'View Details',exact:true}).click();
  await expect(page).toHaveURL(new RegExp(`/design-approvals/${ids.image}/\\?queue_status=all&queue_search=`));
  await expect(page.locator('.design-review-page')).toBeVisible();
  await expect(page.locator('dialog[open]')).toHaveCount(0);
  await expect(page.getByText('3D Pattern Design Approvals',{exact:true})).toHaveCount(0);
  await expect(page.locator('.design-identity')).toContainText('S0001');
  const image=page.locator('[data-review-image]');
  await expect(image).toHaveAttribute('src',`/design-images/${ids.image}/download/`);
  await expect.poll(()=>image.evaluate((el:HTMLImageElement)=>el.naturalWidth)).toBe(960);
  await page.reload();
  await page.getByRole('link',{name:'Approvals Queue',exact:true}).click();
  await expect(page).toHaveURL(/\/approvals\/\?stage=designer&status=all&search=E2E\+direct\+review\+image/);
  await expect(page.locator('.stage-selector-tabs a.active')).toContainText('Designer Uploads');
  await expect(page.locator('input[name="search"]:visible')).toHaveValue('E2E direct review image');
  await page.goto(`/design-approvals/${ids.image}/?next=https://evil.example/`);
  await page.getByRole('link',{name:'Approvals Queue',exact:true}).click();
  await expect(page).toHaveURL(/\/approvals\/\?stage=designer&status=active$/);
  await page.goto('/design-approvals/?tab=all&search=E2E+direct');
  await expect(page).toHaveURL(/\/approvals\/\?stage=designer&status=all&search=E2E\+direct$/);
  expect(errors).toEqual([]);
});

test('review tabs retain draft and role permissions; desktop and mobile layout fit actual content',async({page})=>{
  const errors:string[]=[];page.on('pageerror',err=>errors.push(err.message));
  await login(page);await page.goto(`/design-approvals/${ids.image}/`);
  await expect(page.locator('#review-tab-cad')).toHaveAttribute('aria-selected','true');
  await expect(page.locator('#review-cad')).toBeVisible();
  await expect(page.locator('#review-ed')).toBeHidden();
  await page.locator('#cadCommentInput').fill('Keep the exact CAD draft');
  await page.locator('#review-tab-ed').click();
  await expect(page.locator('#review-ed')).toBeVisible();
  await expect(page.locator('#edReviewForm')).toHaveCount(0);
  await page.locator('#review-tab-ed').press('ArrowLeft');
  await expect(page.locator('#cadCommentInput')).toHaveValue('Keep the exact CAD draft');
  for(const width of [320,375,768,1366]){
    await page.setViewportSize({width,height:900});
    expect(await page.evaluate(()=>document.documentElement.scrollWidth-innerWidth)).toBeLessThanOrEqual(1);
    const preview=await page.locator('.review-preview-panel').boundingBox();
    const review=await page.locator('.review-workspace').boundingBox();
    if(width>900){expect(Math.abs(preview!.y-review!.y)).toBeLessThan(2);expect(preview!.width/(preview!.width+review!.width)).toBeCloseTo(0.55,1);}
    else expect(review!.y).toBeGreaterThan(preview!.y);
  }
  await page.setViewportSize({width:1440,height:1000});await page.evaluate(()=>scrollTo(0,0));
  await page.screenshot({path:'output/direct-review-desktop.png'});
  await page.setViewportSize({width:375,height:900});await page.evaluate(()=>scrollTo(0,0));
  await page.screenshot({path:'output/direct-review-mobile.png'});
  await page.locator('#cadChangeType').selectOption('major');
  await page.locator('#cadReviewForm button[value="approved"]').click();
  await expect(page.locator('#review-tab-cad .review-status')).toHaveText('Approved');
  await expect(page.locator('#review-cad')).toContainText('Keep the exact CAD draft');
  await expect(page.locator('#review-cad')).toContainText('Major Change');
  await expect(page.locator('#review-tab-ed .review-status')).toHaveText('Pending');
  expect(errors).toEqual([]);
});

test('inline PDF uses private PDF.js loader and existing full-screen page and zoom controls',async({page})=>{
  const errors:string[]=[];page.on('pageerror',err=>errors.push(err.message));
  await login(page);await page.goto(`/design-approvals/${ids.pdf}/`);
  const canvas=page.locator('[data-review-pdf-canvas]');
  await expect(canvas).toBeVisible();
  expect(await canvas.evaluate((el:HTMLCanvasElement)=>el.width)).toBeGreaterThan(100);
  await page.getByRole('button',{name:'Full-screen PDF preview',exact:true}).click();
  await expect(page.locator('#designPdfViewer')).toBeVisible();
  await expect(page.locator('#designPdfCounter')).toHaveText('1 / 2');
  await page.getByRole('button',{name:'Next page',exact:true}).click();
  await expect(page.locator('#designPdfCounter')).toHaveText('2 / 2');
  await page.getByRole('button',{name:'Zoom PDF in',exact:true}).click();
  await expect(page.locator('#designPdfZoom')).toHaveText('125%');
  await page.keyboard.press('Escape');
  await expect(page.locator('#designPdfViewer')).not.toBeVisible();
  await expect(canvas).toBeVisible();
  const invalid=await page.evaluate(async()=>{try{await (window as any).fabroCreateDesignPdfTask({original_url:'https://evil.example/private.pdf'});return false;}catch{return true;}});
  expect(invalid).toBe(true);expect(errors).toEqual([]);
});

test('Admin deliberately selects a reviewer and uploader stage stays skipped',async({page})=>{
  await login(page,'direct_review_admin','FabroWorkflow!234');await page.goto(`/design-approvals/${ids.admin}/`);
  await expect(page.locator('[data-review-panel]:visible')).toHaveCount(0);
  await expect(page.locator('[data-review-select-prompt]')).toBeVisible();
  await page.locator('#review-tab-md').click();
  await expect(page.locator('#mdReviewForm')).toBeVisible();
  await page.locator('#mdCommentInput').fill('MD admin review');
  await page.locator('#mdReviewForm button[value="approved"]').click();
  await expect(page.locator('#review-tab-md .review-status')).toHaveText('Approved');
  await expect(page.locator('#review-tab-cad .review-status')).toHaveText('Pending');
  await page.goto(`/design-approvals/${ids.skipped}/`);
  await expect(page.locator('#review-tab-cad .review-status')).toContainText('Skipped');
  await page.locator('#review-tab-cad').click();
  await expect(page.locator('#cadReviewForm')).toHaveCount(0);
});

test('missing and denied preview show recoverable errors; read-only users cannot submit',async({page})=>{
  await login(page,workflowUsers.om.username,workflowUsers.om.password);
  await page.route(`**/design-images/${ids.image}/download/`,route=>route.fulfill({status:403,body:'Forbidden'}));
  await page.goto(`/design-approvals/${ids.image}/`);
  await expect(page.locator('[data-review-error]')).toBeVisible();
  await expect(page.locator('.review-decision-form')).toHaveCount(0);
  await page.unroute(`**/design-images/${ids.image}/download/`);
  await page.getByRole('button',{name:'Retry preview',exact:true}).click();
  await expect(page.locator('[data-review-error]')).toBeHidden();
  await page.route(`**/design-images/${ids.pdf}/download/`,route=>route.fulfill({status:404,body:'Missing'}));
  await page.goto(`/design-approvals/${ids.pdf}/`);
  await expect(page.locator('[data-review-error]')).toBeVisible();
  await page.unroute(`**/design-images/${ids.pdf}/download/`);
  await page.getByRole('button',{name:'Retry preview',exact:true}).click();
  await expect(page.locator('[data-review-pdf-canvas]')).toBeVisible();
});
