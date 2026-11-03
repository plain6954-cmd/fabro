import {expect,test,type Page} from '@playwright/test';
import {readFileSync} from 'fs';
import {runDjangoCode} from '../helpers/django';
import {workflowUsers} from '../helpers/testData';
let ids:Record<string,number>;
test.beforeAll(()=>{
 runDjangoCode(`
import io,json,math,wave
from array import array
from pathlib import Path
from unittest.mock import patch
from PIL import Image,ImageDraw
from pypdf import PdfWriter
from django.conf import settings
from django.core.files.base import ContentFile
from django.core.files.uploadedfile import SimpleUploadedFile
from django.contrib.auth import get_user_model
from management.models import Brand,Model,SubModel,YearRange,PatternDesignImage,WorkflowRoles
from management.services.design_approvals import submit_design_for_approval
from management.services.design_review_voice import record_design_review_with_voice
from management.services.design_pdfs import design_file_storage
User=get_user_model()
for username in ['comparison_browser_owner','comparison_browser_other']:
 user,_=User.objects.get_or_create(username=username);user.set_password('FabroWorkflow!234');user.save()
 p=user.workflow_profile;p.role=WorkflowRoles.FREELANCE_3D_DESIGNER;p.save()
owner=User.objects.get(username='comparison_browser_owner');cad=User.objects.get(username='fabro_e2e_cad')
brand,_=Brand.objects.get_or_create(name='Comparison Browser Brand');model,_=Model.objects.get_or_create(brand=brand,name='Dynamic Model');sub,_=SubModel.objects.get_or_create(model=model,name='Touring')
vehicle,_=YearRange.objects.get_or_create(sub_model=sub,year_start=2025,year_end=2026,defaults={'layout_code':'COMPARISON-BROWSER'})
other_vehicle,_=YearRange.objects.get_or_create(sub_model=sub,year_start=2020,year_end=2021,defaults={'layout_code':'COMPARISON-OTHER'})
target=Path(settings.MEDIA_ROOT)/'comparison-browser';target.mkdir(parents=True,exist_ok=True)
for name,color in [('reference','#b8a797'),('designer','#bbaaac')]:
 img=Image.new('RGB',(600,400),color);draw=ImageDraw.Draw(img)
 draw.rounded_rectangle((160,25,440,245),radius=45,fill='#645755',outline='#e8d7d2',width=4)
 draw.rounded_rectangle((120,255,480,370),radius=35,fill='#786a66',outline='#e8d7d2',width=4)
 draw.text((20,20),name,fill='#32262a');img.save(target/(name+'.png'));img.thumbnail((90,60));img.save(target/(name+'-thumb.png'))
out=io.BytesIO()
with wave.open(out,'wb') as audio:
 audio.setnchannels(1);audio.setsampwidth(2);audio.setframerate(16000);audio.writeframes(array('h',(int(8000*math.sin(n/14)) for n in range(48000))).tobytes())
ids={'vehicle':vehicle.pk}
with patch('management.services.push_notifications.send_push_to_user'):
 for key,title,ref,kind in [('ref','Reference seat.png',True,'image'),('ref2','Reference detail.png',True,'image'),('refpdf','Reference dimension.pdf',True,'pdf'),('refobj','Reference pattern.obj',True,'cad'),('upload','Designer seat.png',False,'image'),('upload2','Designer variant.png',False,'image'),('uploadpdf','Designer dimension.pdf',False,'pdf'),('uploadobj','Designer pattern.obj',False,'cad')]:
  record,created=PatternDesignImage.objects.get_or_create(vehicle=vehicle,title=title,is_reference=ref,defaults={'uploaded_by':cad if ref else owner,'approval_status':'approved' if ref else 'pending','file_size':2048})
  if created:
   if kind=='image':
    name='reference' if ref else 'designer';record.image='comparison-browser/'+name+'.png';record.thumbnail='comparison-browser/'+name+'-thumb.png'
   elif kind=='pdf':
    writer=PdfWriter()
    for n in range(3 if ref else 4):writer.add_blank_page(width=500,height=700)
    data=io.BytesIO();writer.write(data)
    record.image=design_file_storage('private_design_pdfs/comparison-'+key+'.pdf').save('private_design_pdfs/comparison-'+key+'.pdf',ContentFile(data.getvalue()))
   else:
    (target/(key+'.obj')).write_bytes(b'v 0 0 0');record.image='comparison-browser/'+key+'.obj'
   record.save()
   if not ref:
    submit_design_for_approval(record,owner)
    if key=='upload':
     record_design_review_with_voice(record,cad,'rejected','Earlier CAD seam feedback',stage='cad',change_type='major',voice_note=SimpleUploadedFile('voice.wav',out.getvalue()))
     submit_design_for_approval(record,owner,is_resubmission=True)
     record_design_review_with_voice(record,cad,'approved','Current CAD seam feedback',stage='cad',change_type='minor',voice_note=SimpleUploadedFile('voice.wav',out.getvalue()))
  ids[key]=record.pk
 unrelated,_=PatternDesignImage.objects.get_or_create(vehicle=other_vehicle,title='Unrelated reference.png',is_reference=True,defaults={'image':'comparison-browser/reference.png','uploaded_by':cad,'approval_status':'approved'});ids['unrelated']=unrelated.pk
(settings.BASE_DIR/'output/comparison-browser-ids.json').write_text(json.dumps(ids))
`);
 ids=JSON.parse(readFileSync('output/comparison-browser-ids.json','utf8'));
});
async function login(page:Page,username=workflowUsers.cad.username){
 await page.goto('/login/');await page.getByLabel('Username').fill(username);await page.getByLabel('Password').fill('FabroWorkflow!234');await page.getByRole('button',{name:/sign in/i}).click();await expect(page).not.toHaveURL(/\/login\//);
}
const viewer=(page:Page)=>page.locator('#designComparisonViewer');
const panel=(page:Page,side:string)=>viewer(page).locator(`[data-comparison-panel="${side}"]`);
async function open(page:Page){
 await login(page);await page.goto('/approvals/?stage=designer&status=all&search=Designer+seat');
 await page.locator(`#card-design-${ids.upload} [data-design-comparison]`).click();await expect(viewer(page)).toBeVisible();
 await expect(panel(page,'upload').locator('[data-panel-image]')).toBeVisible();
}
async function choose(page:Page,side:string,title:string){await viewer(page).locator(`[data-comparison-carousel="${side}"]`).getByRole('button',{name:title,exact:true}).click();}

test('body-level full viewport overlay preserves queue, private sets, remarks, voice, and direct review',async({page})=>{
 const errors:string[]=[];page.on('pageerror',e=>errors.push(e.message));
 await open(page);const dialog=viewer(page);
 expect(await dialog.evaluate(el=>el.parentElement===document.body)).toBe(true);
 const bounds=await dialog.boundingBox();expect(bounds!.x).toBe(0);expect(bounds!.y).toBe(0);expect(bounds!.width).toBe(1366);expect(bounds!.height).toBe(768);
 expect(await page.evaluate(()=>document.body.style.position)).toBe('fixed');
 await expect(dialog.locator('[data-comparison-carousel="reference"] [data-carousel-count]')).toHaveText('(4)');
 await expect(dialog.locator('[data-comparison-carousel="upload"] [data-carousel-count]')).toHaveText('(4)');
 await expect(dialog).not.toContainText('Unrelated reference');
 await expect(dialog.locator('[data-comparison-reviewers]')).toContainText('Current CAD seam feedback');
 await expect(dialog.locator('[data-comparison-reviewers]')).toContainText('Minor Change');
 await expect(dialog.locator('.review-voice-bubble')).toHaveCount(1);
 await dialog.locator('.voice-play').click();await expect(dialog.locator('audio')).toHaveJSProperty('paused',false);
 await dialog.locator('[data-comparison-cycle]').selectOption('1');
 await expect(dialog.locator('[data-comparison-reviewers]')).toContainText('Earlier CAD seam feedback');
 await expect(dialog.locator('[data-comparison-history-note]')).toBeVisible();
 await expect(dialog.locator('[data-comparison-information]')).toContainText('Revision: 2');
 await dialog.getByRole('button',{name:'Close comparison viewer',exact:true}).click();
 await expect(dialog).not.toBeVisible();await expect(page.locator('#approvals-search-input')).toHaveValue('Designer seat');
 expect(await page.evaluate(()=>document.body.style.position)).toBe('');
 await page.locator(`#card-design-${ids.upload}`).getByRole('link',{name:'View Details',exact:true}).click();
 await expect(page).toHaveURL(new RegExp(`/design-approvals/${ids.upload}/`));
 await page.getByRole('button',{name:'Compare files',exact:true}).click();await expect(dialog).toBeVisible();
 await page.keyboard.press('Escape');await expect(dialog).not.toBeVisible();await expect(page.locator('.design-review-page')).toBeVisible();
 await page.goto(`/design-approvals/${ids.uploadpdf}/`);
 await page.getByRole('button',{name:'Full-screen PDF preview',exact:true}).click();await expect(page.locator('#designPdfViewer')).toBeVisible();
 await page.evaluate(id=>(window as any).openDesignComparison(id),ids.uploadpdf);await expect(dialog).toBeVisible();
 expect(await page.evaluate(()=>document.elementFromPoint(30,30)?.closest('#designComparisonViewer')!==null)).toBe(true);
 await dialog.getByRole('button',{name:'Close comparison viewer',exact:true}).click();await expect(page.locator('#designPdfViewer')).toBeVisible();
 await page.keyboard.press('Escape');await expect(page.locator('#designPdfViewer')).not.toBeVisible();
 expect(errors).toEqual([]);
});
test('independent carousel, image zoom/pan, focused view, Fit Both, safe fallback and download',async({page})=>{
 await open(page);const dialog=viewer(page),left=panel(page,'reference'),right=panel(page,'upload');
 await choose(page,'reference','Reference detail.png');await expect(left.locator('[data-panel-file]')).toHaveText('Reference detail.png');await expect(right.locator('[data-panel-file]')).toHaveText('Designer seat.png');
 await left.getByRole('button',{name:'Zoom in',exact:true}).click();await expect(left.locator('[data-panel-zoom]')).toHaveText('125%');await expect(right.locator('[data-panel-zoom]')).toHaveText('100%');
 await left.getByRole('button',{name:'Zoom in',exact:true}).click();
 const box=(await left.locator('[data-panel-stage]').boundingBox())!;await page.mouse.move(box.x+box.width/2,box.y+box.height/2);await page.mouse.down();await page.mouse.move(box.x+box.width/2+70,box.y+box.height/2,{steps:3});await page.mouse.up();
 expect(await left.locator('img').evaluate(el=>new DOMMatrixReadOnly(getComputedStyle(el).transform).m41)).toBeGreaterThan(0);
 await right.getByRole('button',{name:'Zoom in',exact:true}).click();await dialog.getByRole('button',{name:'Fit Both',exact:true}).click();await expect(left.locator('[data-panel-zoom]')).toHaveText('100%');await expect(right.locator('[data-panel-zoom]')).toHaveText('100%');
 await left.getByRole('button',{name:'Focus this panel',exact:true}).click();await expect(right).not.toBeVisible();await page.keyboard.press('Escape');await expect(right).toBeVisible();await expect(dialog).toBeVisible();
 const strip=dialog.locator('[data-comparison-carousel="reference"] [data-carousel-strip]');expect(await strip.evaluate(el=>getComputedStyle(el).maskImage)).toContain('linear-gradient');
 await choose(page,'upload','Designer pattern.obj');await expect(right.locator('[data-panel-fallback]')).toBeVisible();await expect(right.locator('[data-fallback-title]')).toHaveText('Designer pattern.obj');
 const download=await right.locator('[data-fallback-download]').getAttribute('href');const response=await page.request.get(download!);expect(response.ok()).toBe(true);expect(response.headers()['content-disposition']).toContain('attachment');
 const count=await left.locator('[data-panel-counter]').textContent();await right.getByRole('button',{name:'Next file',exact:true}).click();expect(await left.locator('[data-panel-counter]').textContent()).toBe(count);
 await dialog.getByRole('button',{name:'Close comparison viewer',exact:true}).click();
});
test('image/PDF combinations and two PDFs have independent page, zoom, and file selection',async({page})=>{
 const errors:string[]=[];page.on('pageerror',e=>errors.push(e.message));await open(page);const left=panel(page,'reference'),right=panel(page,'upload'),dialog=viewer(page);
 await choose(page,'reference','Reference dimension.pdf');await expect(left.locator('canvas')).toBeVisible();await expect(right.locator('img')).toBeVisible();await expect(left.locator('[data-pdf-counter]')).toHaveText('1 / 3');
 await choose(page,'upload','Designer dimension.pdf');await expect(right.locator('canvas')).toBeVisible();await expect(right.locator('[data-pdf-counter]')).toHaveText('1 / 4');
 const leftFile=await left.locator('[data-panel-counter]').textContent(),rightFile=await right.locator('[data-panel-counter]').textContent();
 await left.getByRole('button',{name:'Next PDF page',exact:true}).click();await expect(left.locator('[data-pdf-counter]')).toHaveText('2 / 3');await expect(right.locator('[data-pdf-counter]')).toHaveText('1 / 4');
 await right.focus();await right.press('PageDown');await expect(right.locator('[data-pdf-counter]')).toHaveText('2 / 4');
 await right.getByRole('button',{name:'Zoom in',exact:true}).click();await expect(right.locator('[data-panel-zoom]')).toHaveText('125%');await expect(left.locator('[data-panel-zoom]')).toHaveText('100%');
 expect(await left.locator('[data-panel-counter]').textContent()).toBe(leftFile);expect(await right.locator('[data-panel-counter]').textContent()).toBe(rightFile);
 await choose(page,'reference','Reference seat.png');await expect(left.locator('img')).toBeVisible();await expect(right.locator('canvas')).toBeVisible();await expect(right.locator('[data-pdf-counter]')).toHaveText('2 / 4');
 await choose(page,'upload','Designer variant.png');await expect(right.locator('img')).toBeVisible();await expect(left.locator('img')).toBeVisible();
 await choose(page,'reference','Reference dimension.pdf');await choose(page,'upload','Designer dimension.pdf');await expect(left.locator('canvas')).toBeVisible();await expect(right.locator('canvas')).toBeVisible();
 await page.setViewportSize({width:1600,height:1000});await page.screenshot({path:'output/design-comparison-desktop.png'});
 await dialog.getByRole('button',{name:'Close comparison viewer',exact:true}).click();expect(errors).toEqual([]);
});
test('keyboard, mobile switching, fullscreen fallback, touch pinch and independent remarks collapse',async({page})=>{
 await open(page);const dialog=viewer(page),left=panel(page,'reference'),right=panel(page,'upload');
 const strip=dialog.locator('[data-comparison-carousel="reference"] [data-carousel-strip]');await strip.focus();await strip.press('ArrowRight');await expect(left.locator('[data-panel-file]')).toHaveText('Reference detail.png');await expect(right.locator('[data-panel-file]')).toHaveText('Designer seat.png');
 const before=await right.locator('[data-panel-file]').textContent();
 for(const width of [768,375,320]){
  await page.setViewportSize({width,height:900});await expect(dialog).toBeVisible();
  expect(await dialog.evaluate(el=>el.scrollWidth-innerWidth)).toBeLessThanOrEqual(1);
  const bounds=await dialog.boundingBox();expect(bounds!.width).toBe(width);expect(bounds!.height).toBe(900);
  if(width<650){await dialog.getByRole('button',{name:'Reference',exact:true}).click();await expect(left).toBeVisible();await expect(right).not.toBeVisible();await dialog.getByRole('button',{name:'Designer',exact:true}).click();await expect(right).toBeVisible();}
  if(await dialog.getAttribute('data-remarks-collapsed')!=='true')await dialog.getByRole('button',{name:'Toggle approver remarks',exact:true}).click();
  await dialog.getByRole('button',{name:'Toggle approver remarks',exact:true}).click();await expect(dialog.locator('.comparison-remarks-content')).toBeVisible();await dialog.getByRole('button',{name:'Toggle approver remarks',exact:true}).click();
 }
 expect(await right.locator('[data-panel-file]').textContent()).toBe(before);
 await dialog.getByRole('button',{name:'Reference',exact:true}).click();
 await left.getByRole('button',{name:'Focus this panel',exact:true}).click();
 await dialog.getByRole('button',{name:'Designer',exact:true}).click();await expect(right).toBeVisible();await expect(left).not.toBeVisible();
 await choose(page,'reference','Reference seat.png');await expect(left).toBeVisible();await expect(right).not.toBeVisible();
 await choose(page,'upload','Designer seat.png');await expect(right).toBeVisible();await expect(left).not.toBeVisible();
 const box=(await right.locator('[data-panel-stage]').boundingBox())!;const cx=box.x+box.width/2,cy=box.y+box.height/2;
 const cdp=await page.context().newCDPSession(page);await cdp.send('Emulation.setTouchEmulationEnabled',{enabled:true});
 await cdp.send('Input.dispatchTouchEvent',{type:'touchStart',touchPoints:[{x:cx-20,y:cy,id:1},{x:cx+20,y:cy,id:2}]});await cdp.send('Input.dispatchTouchEvent',{type:'touchMove',touchPoints:[{x:cx-45,y:cy,id:1},{x:cx+45,y:cy,id:2}]});await cdp.send('Input.dispatchTouchEvent',{type:'touchEnd',touchPoints:[]});await expect(right.locator('[data-panel-zoom]')).not.toHaveText('100%');
 await cdp.send('Emulation.setTouchEmulationEnabled',{enabled:false});await cdp.detach();
 await dialog.getByRole('button',{name:'Close comparison viewer',exact:true}).focus();for(let n=0;n<12;n++)await page.keyboard.press('Tab');expect(await page.evaluate(()=>document.getElementById('designComparisonViewer')!.contains(document.activeElement))).toBe(true);
 const fullscreen=dialog.getByRole('button',{name:'Toggle browser fullscreen',exact:true});if(await fullscreen.isEnabled()){await fullscreen.click();await expect(dialog).toBeVisible();if(await page.evaluate(()=>!!document.fullscreenElement))await page.keyboard.press('Escape');}
 await page.keyboard.press('Escape');await expect(dialog).not.toBeVisible();
});
test('rapid PDF switching, failures, repeated close cleanup and drawer entry preserve underlying drafts',async({page})=>{
 const errors:string[]=[];page.on('pageerror',e=>errors.push(e.message));await open(page);const dialog=viewer(page),left=panel(page,'reference');
 await page.route(`**/design-images/${ids.refpdf}/comparison-file/`,route=>route.fulfill({status:503,body:'unavailable'}));
 await choose(page,'reference','Reference dimension.pdf');await expect(left.locator('[data-panel-message]')).toContainText('File unavailable');await page.unroute(`**/design-images/${ids.refpdf}/comparison-file/`);await left.getByRole('button',{name:'Retry',exact:true}).click();await expect(left.locator('canvas')).toBeVisible();
 for(let n=0;n<3;n++){
  await choose(page,'reference','Reference dimension.pdf');await choose(page,'reference','Reference seat.png');await expect(left.locator('img')).toBeVisible();await dialog.getByRole('button',{name:'Close comparison viewer',exact:true}).click();
  expect(await dialog.locator('img[data-panel-image]').evaluateAll(nodes=>nodes.every(el=>!el.hasAttribute('src')))).toBe(true);expect(await dialog.locator('[data-file-index]').count()).toBe(0);
  await page.locator(`#card-design-${ids.upload} [data-design-comparison]`).click();await expect(panel(page,'upload').locator('img')).toBeVisible();
 }
 await page.keyboard.press('Escape');await page.goto(`/car-details/?vehicle_id=${ids.vehicle}#design-options`);await page.locator('#sidebarNav3DDesignBtn').click();await expect(page.locator(`.fabro-design-tile[data-file-id="${ids.upload2}"]`)).toBeAttached();await page.evaluate(id=>(window as any).openApprovalDrawer(id),ids.upload2);
 await page.locator('#designDrawerDecisionRemarks').fill('Preserve unsent drawer remarks');await page.getByRole('button',{name:'Compare files',exact:true}).scrollIntoViewIfNeeded();
 const scroll=await page.locator('#designApprovalDrawer .drawer-body').evaluate(el=>el.scrollTop);
 await page.getByRole('button',{name:'Compare files',exact:true}).click();await expect(dialog).toBeVisible();await expect(panel(page,'upload').locator('[data-panel-file]')).toHaveText('Designer variant.png');await page.keyboard.press('Escape');
 await expect(page.locator('#designApprovalDrawer')).toHaveClass(/is-open/);await expect(page.locator('#designDrawerDecisionRemarks')).toHaveValue('Preserve unsent drawer remarks');expect(await page.locator('#designApprovalDrawer .drawer-body').evaluate(el=>el.scrollTop)).toBe(scroll);expect(errors).toEqual([]);
});
test('another designer cannot open pending context, or obtain hidden references/remarks by changing IDs',async({page})=>{
 await login(page,'comparison_browser_other');expect((await page.request.get(`/api/design-images/${ids.upload}/comparison/`)).status()).toBe(404);expect((await page.request.get(`/design-images/${ids.upload}/comparison-file/`)).status()).toBe(404);
});
