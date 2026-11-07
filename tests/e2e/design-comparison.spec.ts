import {expect,test,type Page} from '@playwright/test';
import {readFileSync} from 'fs';
import {runDjangoCode} from '../helpers/django';
import {workflowUsers} from '../helpers/testData';
import {mockReviewRecorder} from '../helpers/mockReviewRecorder';
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
from django.utils import timezone
from datetime import timedelta
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
(settings.BASE_DIR/'output/comparison-workspace-voice.wav').write_bytes(out.getvalue())
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
 # Latest by upload time, deliberately different from the highest file ID.
 PatternDesignImage.objects.filter(pk=ids['upload']).update(uploaded_at=timezone.now()+timedelta(seconds=1))
 unrelated,_=PatternDesignImage.objects.get_or_create(vehicle=other_vehicle,title='Unrelated reference.png',is_reference=True,defaults={'image':'comparison-browser/reference.png','uploaded_by':cad,'approval_status':'approved'});ids['unrelated']=unrelated.pk
empty_vehicle,_=YearRange.objects.get_or_create(sub_model=sub,year_start=2022,year_end=2023,defaults={'layout_code':'COMPARISON-EMPTY'})
ids['empty_vehicle']=empty_vehicle.pk
with patch('management.services.push_notifications.send_push_to_user'):
 for key,title,path in [('empty','Empty reference upload.png','comparison-browser/designer.png'),('emptypdf','Empty reference upload.pdf',PatternDesignImage.objects.get(pk=ids['uploadpdf']).image.name)]:
  record,created=PatternDesignImage.objects.get_or_create(vehicle=empty_vehicle,title=title,is_reference=False,defaults={'image':path,'uploaded_by':owner,'approval_status':'pending'})
  if created:submit_design_for_approval(record,owner)
  ids[key]=record.pk
reference_only,_=YearRange.objects.get_or_create(sub_model=sub,year_start=2018,year_end=2019,defaults={'layout_code':'COMPARISON-REFERENCE-ONLY'})
ids['reference_only_vehicle']=reference_only.pk
for key,original in [('onlyref','ref2'),('onlyrefpdf','refpdf')]:
 source=PatternDesignImage.objects.get(pk=ids[original])
 record,_=PatternDesignImage.objects.get_or_create(vehicle=reference_only,title=source.title,is_reference=True,defaults={'image':source.image.name,'thumbnail':source.thumbnail.name,'uploaded_by':cad,'approval_status':'approved'})
 ids[key]=record.pk
hidden,_=PatternDesignImage.objects.get_or_create(vehicle=other_vehicle,title='Private reference.png',is_reference=True,defaults={'image':'comparison-browser/reference.png','uploaded_by':cad,'approval_status':'pending'})
ids['hidden_reference']=hidden.pk
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
 await expect(dialog.locator('.comparison-approval-document')).toContainText('Current CAD seam feedback');
 await expect(dialog.locator('.comparison-approval-document')).toContainText('Minor Change');
 const currentVoice=dialog.locator('[data-history-cycle="2"] .review-voice-bubble');await expect(currentVoice).toHaveCount(1);
 await currentVoice.locator('.voice-play').click();await expect(currentVoice.locator('audio')).toHaveJSProperty('paused',false);
 await dialog.locator('[data-history-cycle="1"] summary').click();
 await expect(dialog.locator('.comparison-approval-document')).toContainText('Earlier CAD seam feedback');
 await expect(dialog.locator('.workspace-history-note')).toBeVisible();
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
 await left.getByRole('button',{name:'Focus this panel',exact:true}).click();await expect(right).not.toBeVisible();
 expect((await dialog.locator('[data-comparison-carousel="reference"]').boundingBox())!.width).toBeCloseTo((await left.boundingBox())!.width,0);
 await expect(dialog.locator('[data-comparison-approval]')).toBeVisible();await page.keyboard.press('Escape');await expect(right).toBeVisible();await expect(dialog).toBeVisible();
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
 await dialog.getByRole('button',{name:'Close comparison viewer',exact:true}).click();expect(errors).toEqual([]);
});
test('keyboard, mobile approval switching, fullscreen fallback and touch pinch',async({page})=>{
 await open(page);const dialog=viewer(page),left=panel(page,'reference'),right=panel(page,'upload');
 const strip=dialog.locator('[data-comparison-carousel="reference"] [data-carousel-strip]');await strip.focus();await strip.press('ArrowRight');await expect(left.locator('[data-panel-file]')).toHaveText('Reference detail.png');await expect(right.locator('[data-panel-file]')).toHaveText('Designer seat.png');
 const before=await right.locator('[data-panel-file]').textContent();
 for(const width of [768,375,320]){
  await page.setViewportSize({width,height:900});await expect(dialog).toBeVisible();
  expect(await dialog.evaluate(el=>el.scrollWidth-innerWidth)).toBeLessThanOrEqual(1);
  const bounds=await dialog.boundingBox();expect(bounds!.width).toBe(width);expect(bounds!.height).toBe(900);
  if(width<650){await dialog.getByRole('button',{name:'Reference',exact:true}).click();await expect(left).toBeVisible();await expect(right).not.toBeVisible();await dialog.getByRole('button',{name:'Designer',exact:true}).click();await expect(right).toBeVisible();}
  await dialog.getByRole('button',{name:'Approval',exact:true}).click();await expect(dialog.locator('[data-comparison-approval]')).toBeVisible();
  await dialog.getByRole('button',{name:'Designer',exact:true}).click();
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
 await page.getByRole('button',{name:'Compare files',exact:true}).click();await expect(dialog).toBeVisible();await expect(panel(page,'upload').locator('[data-panel-file]')).toHaveText('Designer seat.png');await choose(page,'upload','Designer variant.png');await expect(panel(page,'upload').locator('[data-panel-file]')).toHaveText('Designer variant.png');await page.evaluate(id=>(window as any).load3DDesignWorkspace(id),ids.vehicle);await page.keyboard.press('Escape');
 await expect(page.locator('#designApprovalDrawer')).toHaveClass(/is-open/);await expect(page.locator('#designDrawerDecisionRemarks')).toHaveValue('Preserve unsent drawer remarks');expect(await page.locator('#designApprovalDrawer .drawer-body').evaluate(el=>el.scrollTop)).toBe(scroll);expect(errors).toEqual([]);
});
test('another designer cannot open pending context, or obtain hidden references/remarks by changing IDs',async({page})=>{
 await login(page,'comparison_browser_other');expect((await page.request.get(`/api/design-images/${ids.upload}/comparison/`)).status()).toBe(404);expect((await page.request.get(`/design-images/${ids.upload}/comparison-file/`)).status()).toBe(404);
 const response=await page.request.get(`/api/design-images/${ids.ref}/comparison/`);expect(response.status()).toBe(200);
 const data=await response.json();expect(data.uploads).toEqual([]);expect(data.references.map((file:any)=>file.id)).not.toContain(ids.hidden_reference);
 expect((await page.request.get(`/api/design-images/${ids.hidden_reference}/comparison/`)).status()).toBe(404);
 expect((await page.request.get(`/design-images/${ids.hidden_reference}/comparison-file/`)).status()).toBe(404);
});

for(const [key,title,media] of [['ref2','Reference detail.png','img'],['refpdf','Reference dimension.pdf','canvas']]){
 test(`reference thumbnail ${key} opens the exact file in comparison with latest upload and remarks`,async({page})=>{
  const errors:string[]=[];page.on('pageerror',error=>errors.push(error.message));await login(page);
  await page.goto(`/car-details/?vehicle_id=${ids.vehicle}#design-options`);await page.locator('#sidebarNav3DDesignBtn').click();
  const thumb=page.locator('#refImagesScrollTrack').getByRole('button',{name:`Preview ${title}`,exact:true});
  await thumb.click();const dialog=viewer(page),left=panel(page,'reference'),right=panel(page,'upload');
  await expect(dialog).toBeVisible();await expect(left.locator('[data-panel-file]')).toHaveText(title);await expect(left.locator(media)).toBeVisible();
  await expect(dialog.locator(`[data-comparison-carousel="reference"] button[aria-pressed="true"]`)).toHaveAttribute('aria-label',title);
  await expect(right.locator('[data-panel-file]')).toHaveText('Designer seat.png');await expect(right.locator('img')).toBeVisible();
  await expect(dialog.locator('.comparison-approval-document')).toContainText('Current CAD seam feedback');
  await expect(dialog.locator('[data-history-cycle="2"] .workspace-cycle-statuses')).toContainText('ED');await expect(dialog.locator('[data-history-cycle="2"] .workspace-cycle-statuses')).toContainText('MD');
  for(const selector of ['#designImageViewer','#designPdfViewer','#designImagePreviewOverlay','#interiorMediaPreviewModal'])await expect(page.locator(selector)).not.toBeVisible();
  await choose(page,'reference','Reference seat.png');await expect(left.locator('img')).toBeVisible();await expect(right.locator('[data-panel-file]')).toHaveText('Designer seat.png');
  await choose(page,'upload','Designer dimension.pdf');await expect(right.locator('canvas')).toBeVisible();await expect(left.locator('[data-panel-file]')).toHaveText('Reference seat.png');
  await choose(page,'reference','Reference dimension.pdf');await expect(left.locator('canvas')).toBeVisible();
  await left.getByRole('button',{name:'Next PDF page',exact:true}).click();await expect(left.locator('[data-pdf-counter]')).toHaveText('2 / 3');await expect(right.locator('[data-pdf-counter]')).toHaveText('1 / 4');
  await page.keyboard.press('Escape');await expect(dialog).not.toBeVisible();await expect(thumb).toBeFocused();
  // Keyboard activation uses the same entry and restores focus; mobile starts on the clicked reference.
  await page.setViewportSize({width:375,height:900});await thumb.press('Enter');await expect(dialog).toBeVisible();await expect(left).toBeVisible();await expect(right).not.toBeVisible();await expect(left.locator('[data-panel-file]')).toHaveText(title);
  await page.keyboard.press('Escape');expect(errors).toEqual([]);
 });
}

test('reference image and PDF still open comparison when no designer upload exists',async({page})=>{
 await login(page);await page.goto(`/car-details/?vehicle_id=${ids.reference_only_vehicle}#design-options`);await page.locator('#sidebarNav3DDesignBtn').click();
 for(const [title,media] of [['Reference detail.png','img'],['Reference dimension.pdf','canvas']]){
  await page.locator('#refImagesScrollTrack').getByRole('button',{name:`Preview ${title}`,exact:true}).click();
  const dialog=viewer(page),left=panel(page,'reference'),right=panel(page,'upload');
  await expect(dialog).toBeVisible();await expect(left.locator('[data-panel-file]')).toHaveText(title);await expect(left.locator(media)).toBeVisible();
  await expect(right.locator('[data-panel-message]')).toHaveText('No designer uploads available');await expect(right.locator('[data-panel-counter]')).toHaveText('0 / 0');
  await expect(right.getByRole('button',{name:'Next file',exact:true})).toBeDisabled();
  await expect(page.locator('#interiorMediaPreviewModal')).not.toBeVisible();await expect(page.locator('#designPdfViewer')).not.toBeVisible();
  await left.getByRole('button',{name:'Next file',exact:true}).click();await expect(left.locator('[data-panel-file]')).not.toHaveText(title);await expect(right.locator('[data-panel-message]')).toHaveText('No designer uploads available');
  await page.keyboard.press('Escape');await expect(dialog).not.toBeVisible();
 }
});


test('actual Pattern Master designer thumbnails open comparison in grid and list, never a legacy modal',async({page})=>{
 const errors:string[]=[];page.on('pageerror',error=>errors.push(error.message));await login(page);
 await page.goto(`/car-details/?vehicle_id=${ids.vehicle}#design-options`);await page.locator('#sidebarNav3DDesignBtn').click();
 await expect(page.locator(`.fabro-design-tile[data-file-id="${ids.upload}"]`)).toBeAttached();
 expect(await page.evaluate(()=>typeof (window as any).openDesignComparison)).toBe('function');
 await expect(page.locator('script[src*="pattern_3d_design.js"]')).toHaveAttribute('src',/\?v=20261107-latest-version/);
 const dialog=viewer(page),left=panel(page,'reference'),right=panel(page,'upload');
 await page.locator('#design3DFilesSearch').fill('Designer');
 for(const mode of ['grid','list']){
  await page.locator(mode==='grid'?'#design3DGridBtn':'#design3DListBtn').click();
  const thumb=page.locator(`.fabro-design-tile[data-file-id="${ids.upload}"] [data-design-image-id]`);
  const manifest=page.waitForResponse(response=>response.url().includes(`/api/design-images/${ids.upload}/comparison/`));
  await thumb.click();expect((await manifest).status()).toBe(200);
  await expect(dialog).toBeVisible();await expect(left).toBeVisible();await expect(right).toBeVisible();
  await expect(right.locator('[data-panel-file]')).toHaveText('Designer seat.png');
  await expect(left.locator('[data-panel-image]')).toBeVisible();await expect(right.locator('[data-panel-image]')).toBeVisible();
  await expect(page.locator('#designImageViewer')).not.toBeVisible();await expect(page.locator('#designPdfViewer')).not.toBeVisible();await expect(page.locator('#designImagePreviewOverlay')).not.toBeVisible();
  await expect(dialog.locator('.comparison-toolbar')).toBeVisible();await expect(dialog.locator('.comparison-information')).toContainText('Dynamic Model');
  await expect(dialog.locator('[data-comparison-carousel="reference"]')).toBeVisible();await expect(dialog.locator('[data-comparison-carousel="upload"]')).toBeVisible();
  await choose(page,'reference','Reference dimension.pdf');await expect(left.locator('canvas')).toBeVisible();await expect(right.locator('[data-panel-file]')).toHaveText('Designer seat.png');
  await choose(page,'upload','Designer dimension.pdf');await expect(right.locator('canvas')).toBeVisible();await expect(left.locator('canvas')).toBeVisible();
  await right.getByRole('button',{name:'Next PDF page',exact:true}).click();await expect(right.locator('[data-pdf-counter]')).toHaveText('2 / 4');
  await dialog.getByRole('button',{name:'Close comparison viewer',exact:true}).click();await expect(dialog).not.toBeVisible();await expect(thumb).toBeFocused();
  await expect(page.locator('#design3DFilesSearch')).toHaveValue('Designer');await expect(page.locator('#design3DListBtn')).toHaveClass(mode==='list'?/active/:/^(?!.*active)/);
  const pdfThumb=page.locator(`.fabro-design-tile[data-file-id="${ids.uploadpdf}"] [data-design-pdf-id]`);
  await pdfThumb.click();await expect(dialog).toBeVisible();await expect(right.locator('[data-panel-file]')).toHaveText('Designer seat.png');await choose(page,'upload','Designer dimension.pdf');await expect(right.locator('[data-panel-file]')).toHaveText('Designer dimension.pdf');await expect(right.locator('canvas')).toBeVisible();await expect(page.locator('#designPdfViewer')).not.toBeVisible();
  await page.keyboard.press('Escape');await expect(dialog).not.toBeVisible();
 }
 expect(errors).toEqual([]);
});
test('actual gallery thumbnail with no reference files keeps comparison and image/PDF designer navigation functional',async({page})=>{
 await login(page);await page.goto(`/car-details/?vehicle_id=${ids.empty_vehicle}#design-options`);await page.locator('#sidebarNav3DDesignBtn').click();
 const dialog=viewer(page),left=panel(page,'reference'),right=panel(page,'upload');
 await page.locator(`.fabro-design-tile[data-file-id="${ids.empty}"] [data-design-image-id]`).click();
 await expect(dialog).toBeVisible();await expect(dialog.locator('[data-comparison-carousel="reference"] [data-carousel-count]')).toHaveText('(0)');
 await expect(left.locator('[data-panel-message]')).toHaveText('No authorized reference files in this context.');await expect(right.locator('[data-panel-file]')).toHaveText('Empty reference upload.pdf');await expect(right.locator('canvas')).toBeVisible();await choose(page,'upload','Empty reference upload.png');await expect(right.locator('[data-panel-image]')).toBeVisible();
 await expect(page.locator('#designImageViewer')).not.toBeVisible();await expect(page.locator('#designPdfViewer')).not.toBeVisible();
 await choose(page,'upload','Empty reference upload.pdf');await expect(right.locator('canvas')).toBeVisible();await expect(right.locator('[data-pdf-counter]')).toHaveText('1 / 4');
 await expect(left.locator('[data-panel-counter]')).toHaveText('0 / 0');await page.keyboard.press('Escape');await expect(dialog).not.toBeVisible();
});

test.beforeAll(()=>{
 runDjangoCode(`
import json
from pathlib import Path
from unittest.mock import patch
from PIL import Image
from django.conf import settings
from django.contrib.auth import get_user_model
from management.models import ApprovalRoles, PatternDesignImage, WorkflowRoles, YearRange
from management.services.design_approvals import submit_design_for_approval, record_design_review_decision
ids=json.loads((settings.BASE_DIR/'output/comparison-browser-ids.json').read_text())
User=get_user_model();owner=User.objects.get(username='comparison_browser_owner');cad=User.objects.get(username='fabro_e2e_cad');ed=User.objects.get(username='fabro_e2e_ed')
md,_=User.objects.get_or_create(username='fabro_e2e_md');md.set_password('FabroWorkflow!234');md.save();p=md.workflow_profile;p.role=WorkflowRoles.APPROVER;p.approval_role=ApprovalRoles.MD;p.save()
sub=YearRange.objects.get(pk=ids['vehicle']).sub_model
variants,_=YearRange.objects.get_or_create(sub_model=sub,year_start=2014,year_end=2015,defaults={'layout_code':'COMPARE-FORMATS'})
single,_=YearRange.objects.get_or_create(sub_model=sub,year_start=2016,year_end=2017,defaults={'layout_code':'COMPARE-SINGLE'})
ids['formats_vehicle']=variants.pk;ids['single_vehicle']=single.pk
target=Path(settings.MEDIA_ROOT)/'comparison-browser'
with patch('management.services.push_notifications.send_push_to_user'):
 for reference in (True,False):
  for ext in ('png','jpg','webp'):
   name=('Reference' if reference else 'Designer')+' format.'+ext
   Image.new('RGB',(600,400),'#b8a797').save(target/name)
   file,created=PatternDesignImage.objects.get_or_create(vehicle=variants,title=name,is_reference=reference,defaults={'image':'comparison-browser/'+name,'uploaded_by':cad if reference else owner,'approval_status':'approved' if reference else 'pending'})
   if created and not reference:
    submit_design_for_approval(file,owner)
    if ext=='webp':
     for reviewer,status,classification in ((cad,'approved','minor'),(ed,'rejected','major'),(md,'approved','minor')):
      record_design_review_decision(file,reviewer,status,reviewer.username+' format feedback',change_type=classification)
   ids[('formatref_' if reference else 'formatupload_')+ext]=file.pk
 for reference in (True,False):
  file,created=PatternDesignImage.objects.get_or_create(vehicle=single,is_reference=reference,defaults={'title':'Single reference.png' if reference else 'Single upload.png','image':'comparison-browser/reference.png','uploaded_by':cad,'approval_status':'approved' if reference else 'pending'})
  if created and not reference:submit_design_for_approval(file,cad)
  ids['single_ref' if reference else 'single_upload']=file.pk
admin,_=User.objects.get_or_create(username='comparison_browser_admin');admin.set_password('FabroWorkflow!234');admin.save()
p=admin.workflow_profile;p.role=WorkflowRoles.ADMIN;p.save()
review_vehicle,_=YearRange.objects.get_or_create(sub_model=sub,year_start=2010,year_end=2011,defaults={'layout_code':'COMPARE-REVIEWS'})
ids['review_vehicle']=review_vehicle.pk
with patch('management.services.push_notifications.send_push_to_user'):
 for key,title,path in [('review_primary','Workspace primary.png','comparison-browser/designer.png'),('review_sibling','Workspace sibling.pdf',PatternDesignImage.objects.get(pk=ids['uploadpdf']).image.name)]:
  file,created=PatternDesignImage.objects.get_or_create(vehicle=review_vehicle,title=title,defaults={'image':path,'uploaded_by':owner})
  if created:
   submit_design_for_approval(file,owner)
   if key=='review_primary':
    record_design_review_decision(file,cad,'rejected','Original cycle: correct the seam.'+chr(10)+(('Recorded fitment feedback.'+chr(10))*14),change_type='major')
    submit_design_for_approval(file,owner,is_resubmission=True)
  ids[key]=file.pk
 PatternDesignImage.objects.get_or_create(vehicle=review_vehicle,is_reference=True,title='Workspace reference.png',defaults={'image':'comparison-browser/reference.png','uploaded_by':cad,'approval_status':'approved'})
(settings.BASE_DIR/'output/comparison-browser-ids.json').write_text(json.dumps(ids))
`);
 ids=JSON.parse(readFileSync('output/comparison-browser-ids.json','utf8'));
});

test('PNG JPEG and WebP reference/designer thumbnails reuse comparison in both gallery modes',async({page})=>{
 const errors:string[]=[];page.on('pageerror',error=>errors.push(error.message));await login(page);
 await page.goto(`/car-details/?vehicle_id=${ids.formats_vehicle}#design-options`);await page.locator('#sidebarNav3DDesignBtn').click();
 const dialog=viewer(page),left=panel(page,'reference'),right=panel(page,'upload');
 for(const mode of ['grid','list']){
  await page.locator(mode==='grid'?'#design3DGridBtn':'#design3DListBtn').click();
  for(const ext of ['png','jpg','webp'])for(const reference of [true,false]){
   const source=reference?page.locator('#refImagesScrollTrack').getByRole('button',{name:`Preview Reference format.${ext}`,exact:true}):page.locator(`.fabro-design-tile[data-file-id="${ids['formatupload_'+ext]}"] [data-design-image-id]`);
   await source.click();await expect(dialog).toBeVisible();
   await expect(right.locator('[data-panel-file]')).toHaveText('Designer format.webp');
   if(!reference)await choose(page,'upload',`Designer format.${ext}`);
   await expect((reference?left:right).locator('[data-panel-file]')).toHaveText(`${reference?'Reference':'Designer'} format.${ext}`);
   for(const p of [left,right]){
    await expect(p.locator('[data-panel-image]')).toBeVisible();
    expect(await p.locator('img').evaluate((img:HTMLImageElement)=>({ratio:img.naturalWidth/img.naturalHeight,fit:getComputedStyle(img).objectFit}))).toEqual({ratio:1.5,fit:'contain'});
   }
   await expect(dialog.locator('[data-comparison-information]')).toContainText('Dynamic Model');
   for(const selector of ['#designImageViewer','#designPdfViewer','#interiorMediaPreviewModal','#designImagePreviewOverlay'])await expect(page.locator(selector)).not.toBeVisible();
   await expect(page.locator('#designApprovalDrawer')).not.toHaveClass(/is-open/);
   if(reference){
    await expect(right.locator('[data-panel-file]')).toHaveText('Designer format.webp');
    for(const [role,status,classification] of [['CAD','approved','Minor'],['ED','rejected','Major'],['MD','approved','Minor']]){
     const card=dialog.locator(`[data-reviewer-stage="${role}"]`);
     await expect(card.locator('.review-status')).toHaveClass(new RegExp(status));
     await expect(card).toContainText(`fabro_e2e_${role.toLowerCase()} format feedback`);await expect(card).toContainText(`${classification} Change`);
     await expect(card.locator('.workspace-event-meta')).toContainText(/\d{4} \d{2}:\d{2}/);
    }
    await choose(page,'upload','Designer format.png');await expect(dialog.locator('.comparison-approval-document:visible')).not.toContainText('format feedback');
   }
   await page.keyboard.press('Escape');await expect(dialog).not.toBeVisible();
   await expect(source).toBeFocused();
  }
 }
 expect(errors).toEqual([]);
});

test('comparison controls and metadata fit all requested desktop tablet and mobile viewports',async({page})=>{
 await login(page);await page.goto(`/car-details/?vehicle_id=${ids.formats_vehicle}#design-options`);await page.locator('#sidebarNav3DDesignBtn').click();
 await page.locator('#refImagesScrollTrack').getByRole('button',{name:'Preview Reference format.webp',exact:true}).click();
 const dialog=viewer(page),left=panel(page,'reference'),right=panel(page,'upload');
 for(const [width,height] of [[1920,1080],[1440,900],[1366,768],[1024,768],[768,1024],[390,844]]){
  await page.setViewportSize({width,height});
  const box=(await dialog.boundingBox())!;expect([box.x,box.y,box.width,box.height]).toEqual([0,0,width,height]);
  expect(await dialog.evaluate(el=>el.scrollWidth-innerWidth)).toBeLessThanOrEqual(1);
  for(const selector of ['.comparison-toolbar','.comparison-information','.comparison-carousels']){
   const bounds=(await dialog.locator(selector).boundingBox())!;expect(bounds.y).toBeGreaterThanOrEqual(0);expect(bounds.y+bounds.height).toBeLessThanOrEqual(height+1);
  }
  for(const side of ['reference','upload']){
   if(width<650)await dialog.getByRole('button',{name:side==='reference'?'Reference':'Designer',exact:true}).click();
   const p=side==='reference'?left:right;await expect(p).toBeVisible();
   const stage=(await p.locator('[data-panel-stage]').boundingBox())!;expect(stage.height).toBeGreaterThan(100);expect(stage.width).toBeGreaterThan(100);
   await p.getByRole('button',{name:'Zoom in',exact:true}).click();await expect(p.locator('[data-panel-zoom]')).toHaveText('125%');
   await dialog.getByRole('button',{name:'Fit Both',exact:true}).click();await expect(p.locator('[data-panel-zoom]')).toHaveText('100%');
   const carousel=dialog.locator(`[data-comparison-carousel="${side}"]`);await expect(carousel.locator('button[aria-pressed="true"]')).toHaveCount(1);
   expect(await carousel.locator('[data-carousel-strip]').evaluate(el=>getComputedStyle(el).maskImage)).toContain('linear-gradient');
  }
  const close=dialog.getByRole('button',{name:'Close comparison viewer',exact:true});
  expect(await close.evaluate(el=>{const r=el.getBoundingClientRect();return el.contains(document.elementFromPoint(r.x+r.width/2,r.y+r.height/2));})).toBe(true);
  expect(await page.evaluate(()=>document.body.style.position)).toBe('fixed');
  if(width===1920||width===390)await page.screenshot({path:`output/design-comparison-${width===1920?'desktop':'mobile'}.png`});
 }
 await page.keyboard.press('Escape');await expect(dialog).not.toBeVisible();expect(await page.evaluate(()=>document.body.style.position)).toBe('');
});

test('single-file controls stay disabled and gallery synchronization preserves an open comparison',async({page})=>{
 test.setTimeout(45000);await login(page);await page.goto(`/car-details/?vehicle_id=${ids.single_vehicle}#design-options`);await page.locator('#sidebarNav3DDesignBtn').click();
 await page.locator('#refImagesScrollTrack').getByRole('button',{name:'Preview Single reference.png',exact:true}).click();
 const dialog=viewer(page),left=panel(page,'reference'),right=panel(page,'upload');
 for(const p of [left,right]){await expect(p.locator('[data-panel-counter]')).toHaveText('1 / 1');for(const name of ['Previous file','Next file'])await expect(p.getByRole('button',{name,exact:true})).toBeDisabled();}
 await expect(dialog.locator('.workspace-cycle-statuses .review-status.skipped_uploader')).toHaveClass(/skipped_uploader/);
 await right.getByRole('button',{name:'Zoom in',exact:true}).click();
 runDjangoCode(`from management.models import PatternDesignImage; PatternDesignImage.objects.filter(pk=${ids.single_upload}).update(title='Single upload updated.png')`);
 await expect(page.locator(`.fabro-design-tile[data-file-id="${ids.single_upload}"] .tile-title`)).toHaveText('Single upload updated.png',{timeout:20000});
 await expect(dialog).toBeVisible();await expect(right.locator('[data-panel-file]')).toHaveText('Single upload updated.png');await expect(right.locator('[data-panel-zoom]')).toHaveText('125%');
 await expect(left.locator('[data-panel-file]')).toHaveText('Single reference.png');await page.keyboard.press('Escape');
});

async function reviewWorkspace(page:Page,username=workflowUsers.cad.username){
 await login(page,username);await page.goto(`/car-details/?vehicle_id=${ids.review_vehicle}#design-options`);await page.locator('#sidebarNav3DDesignBtn').click();
 await page.locator(`.fabro-design-tile[data-file-id="${ids.review_primary}"] [data-design-image-id]`).click();
 await expect(panel(page,'upload').locator('[data-panel-file]')).toHaveText('Workspace sibling.pdf');
 await choose(page,'upload','Workspace primary.png');
 const root=viewer(page).locator(`.comparison-approval-document[data-design-id="${ids.review_primary}"]`);await expect(root).toBeAttached();return root;
}

test('integrated workspace aligns three columns and has exactly one continuous approval scroll area',async({page})=>{
 const root=await reviewWorkspace(page),dialog=viewer(page),approval=dialog.locator('[data-comparison-approval]');
 const errors:string[]=[];page.on('pageerror',error=>errors.push(error.message));
 for(const [width,height] of [[1920,1080],[1366,768],[1024,768],[390,844]]){
  await page.setViewportSize({width,height});
  if(width<900)await dialog.getByRole('button',{name:'Approval',exact:true}).click();
  await expect(approval).toBeVisible();await approval.evaluate(el=>{el.scrollTop=0;});
  const fixed=['.comparison-toolbar','.comparison-carousels','.comparison-information'];
  if(width>=900)fixed.push('[data-comparison-panel="reference"]','[data-comparison-panel="upload"]');
  const before=await Promise.all(fixed.map(selector=>dialog.locator(selector).boundingBox()));
  const headingBefore=(await root.locator('.workspace-approval-heading').boundingBox())!;
  if(width>=900){
   const left=(await panel(page,'reference').boundingBox())!,center=(await panel(page,'upload').boundingBox())!,right=(await approval.boundingBox())!;
   for(const [side,box] of [['reference',left],['upload',center]] as const){const selector=(await dialog.locator(`[data-comparison-carousel="${side}"]`).boundingBox())!;expect(Math.abs(selector.x-box.x)).toBeLessThan(1);expect(Math.abs(selector.width-box.width)).toBeLessThan(1);}
   expect(center.x+center.width).toBeLessThan(right.x);expect(Math.abs(right.y-left.y)).toBeLessThan(1);expect(Math.abs(right.height-left.height)).toBeLessThan(1);
  }
  await root.locator('[data-history-cycle="1"] summary').click();
  if(!await root.locator('[data-history-cycle="1"]').getAttribute('open'))await root.locator('[data-history-cycle="1"]').evaluate(el=>{(el as HTMLDetailsElement).open=true;});
  const box=(await approval.boundingBox())!;await page.mouse.move(box.x+box.width/2,box.y+box.height-30);await page.mouse.wheel(0,1600);
  await expect.poll(()=>approval.evaluate(el=>el.scrollTop)).toBeGreaterThan(100);
  expect((await root.locator('.workspace-approval-heading').boundingBox())!.y).toBeLessThan(headingBefore.y-100);
  expect(await Promise.all(fixed.map(selector=>dialog.locator(selector).boundingBox()))).toEqual(before);
  expect(await dialog.evaluate(el=>({vertical:el.scrollHeight-el.clientHeight,top:el.scrollTop,horizontal:el.scrollWidth-el.clientWidth}))).toEqual({vertical:0,top:0,horizontal:0});
  expect(await root.locator('.workspace-history').evaluate(el=>getComputedStyle(el).overflowY)).toBe('visible');
  expect(await root.locator('.review-matrix').evaluate(el=>getComputedStyle(el).position)).not.toBe('sticky');
  await approval.evaluate(el=>{el.scrollTop=el.scrollHeight;});await expect(root.locator('.workspace-history-note').last()).toBeVisible();
  await approval.evaluate(el=>{el.scrollTop=0;});
  if(width===1920||width===390)await page.screenshot({path:`output/design-comparison-${width===1920?'desktop':'mobile'}.png`});
 }
 // Emulate the reduced visual viewport available above a mobile keyboard.
 await page.setViewportSize({width:390,height:500});await root.locator('#cadCommentInput').focus();
 await root.locator('#cadCommentInput').fill('Keyboard remains usable');await expect(root.locator('#cadCommentInput')).toBeInViewport();
 expect(await dialog.evaluate(el=>el.scrollHeight-el.clientHeight)).toBe(0);
 page.once('dialog',dialog=>dialog.accept());await page.keyboard.press('Escape');await expect(viewer(page)).not.toBeVisible();expect(errors).toEqual([]);
});

for(const [username,heading,stage] of [[workflowUsers.cad.username,'CAD Approval','cad'],[workflowUsers.ed.username,'ED Approval','ed'],['fabro_e2e_md','MD Approval','md'],['comparison_browser_owner','Approval Details',''],[workflowUsers.om.username,'Approval Details','']]){
 test(`integrated workspace gives ${username} the authorized role-specific controls`,async({page})=>{
  const root=await reviewWorkspace(page,username);
  await expect(root.getByRole('heading',{name:heading,exact:true})).toBeVisible();await expect(root.locator('[role="tablist"]')).toHaveCount(0);
  await expect(root.locator('.review-decision-form')).toHaveCount(stage?1:0);
  if(stage){await expect(root.locator(`#${stage}ReviewForm`)).toBeVisible();await expect(root.locator('[name="change_type"]')).toHaveValue('minor');}
  await expect(root.locator('[data-history-cycle="1"]')).not.toHaveAttribute('open');await expect(root.locator('[data-history-cycle="2"]')).toHaveAttribute('open');
  await root.locator('[data-history-cycle="1"] summary').click();await expect(root.locator('.workspace-history')).toContainText('Original cycle: correct the seam.');
  await choose(page,'upload','Workspace sibling.pdf');const next=viewer(page).locator('.comparison-approval-document:visible');
  await expect(next.locator('.workspace-design-name')).toHaveText('Workspace sibling.pdf');await expect(next.locator('.workspace-history')).not.toContainText('Original cycle:');
 });
}

test('integrated Admin preserves drafts by file and stage and uses the existing POST workflow once',async({page})=>{
 const root=await reviewWorkspace(page,'comparison_browser_admin'),dialog=viewer(page);
 await expect(root.getByRole('heading',{name:'Design Approval Management',exact:true})).toBeVisible();await expect(root.locator('[data-review-panel]:visible')).toHaveCount(0);
 await root.locator('#review-tab-cad').click();await root.locator('#cadCommentInput').fill('Admin CAD draft');await root.locator('#cadChangeType').selectOption('major');
 await root.locator('#review-tab-ed').click();await root.locator('#edCommentInput').fill('Admin ED draft');
 await choose(page,'upload','Workspace sibling.pdf');const sibling=dialog.locator(`.comparison-approval-document[data-design-id="${ids.review_sibling}"]`);await sibling.locator('#review-tab-cad').click();await sibling.locator('#cadCommentInput').fill('Sibling draft stays separate');
 await choose(page,'upload','Workspace primary.png');await expect(root.locator('#edCommentInput')).toHaveValue('Admin ED draft');await root.locator('#review-tab-cad').click();await expect(root.locator('#cadCommentInput')).toHaveValue('Admin CAD draft');await expect(root.locator('#cadChangeType')).toHaveValue('major');
 page.once('dialog',dialog=>dialog.dismiss());await page.keyboard.press('Escape');await expect(dialog).toBeVisible();
 let release!:()=>void;const gate=new Promise<void>(resolve=>{release=resolve;});
 await page.route(`**/design-approvals/${ids.review_primary}/?workspace=comparison`,async route=>{if(route.request().method()==='POST')await gate;await route.continue();});
 let submissions=0;page.on('request',request=>{if(request.method()==='POST'&&request.url().includes(`/design-approvals/${ids.review_primary}/`))submissions++;});
 const response=page.waitForResponse(response=>response.request().method()==='POST'&&response.url().includes(`/design-approvals/${ids.review_primary}/`));
 await root.locator('#cadReviewForm button[value="approved"]').click();await expect(root.locator('#cadReviewForm button[value="approved"]')).toBeDisabled();
 await root.locator('#cadReviewForm').evaluate(form=>(form as HTMLFormElement).requestSubmit(form.querySelector('button[value="approved"]') as HTMLButtonElement));
 release();expect((await response).status()).toBe(302);await expect(root.locator('[data-workspace-feedback]')).toContainText('recorded');
  await expect(dialog).toHaveAttribute('data-review-saving','false');
 await expect(root.locator('#review-tab-cad')).toBeDisabled();await expect(root.locator('#review-cad')).toHaveAttribute('data-stage-status','approved');await root.locator('#review-tab-ed').click();await expect(root.locator('#edCommentInput')).toHaveValue('Admin ED draft');
 await expect(root.locator('[data-history-cycle="2"] .workspace-event-comment')).toContainText('Admin CAD draft');
 await expect(root.locator('[data-history-cycle="2"] .workspace-event-meta')).toContainText('comparison_browser_admin');expect(submissions).toBe(1);
 // A cancelled decline preserves the draft; a confirmed decline uses the same form route.
 page.once('dialog',dialog=>dialog.dismiss());await root.locator('#edReviewForm button[value="rejected"]').click();await expect(root.locator('#edReviewForm')).toBeVisible();expect(submissions).toBe(1);
 page.once('dialog',dialog=>dialog.accept());await root.locator('#edReviewForm button[value="rejected"]').click();await expect(root.locator('#review-tab-ed')).toBeDisabled();
 await expect(root.locator('.workspace-approval-heading .review-status')).toHaveText('Changes Required');expect(submissions).toBe(2);
  await expect(dialog).toHaveAttribute('data-review-saving','false');
 await choose(page,'upload','Workspace sibling.pdf');await expect(sibling.locator('#cadCommentInput')).toHaveValue('Sibling draft stays separate');
 page.once('dialog',dialog=>dialog.accept());await page.keyboard.press('Escape');await expect(dialog).not.toBeVisible();
 await page.goto(`/car-details/?vehicle_id=${ids.single_vehicle}#design-options`);await page.locator('#sidebarNav3DDesignBtn').click();
 await page.locator(`.fabro-design-tile[data-file-id="${ids.single_upload}"] [data-design-image-id]`).click();
 const skipped=dialog.locator(`.comparison-approval-document[data-design-id="${ids.single_upload}"]`);
 await expect(skipped.locator('#review-tab-cad')).toBeDisabled();await expect(skipped.locator('#cadReviewForm')).toHaveCount(0);await expect(skipped.locator('#review-tab-ed')).toBeEnabled();
 await skipped.locator('#review-tab-cad').evaluate(el=>(el as HTMLButtonElement).click());await expect(skipped.locator('[data-review-panel]:visible')).toHaveCount(0);
});

test('integrated voice draft survives file switching and submits through the existing review form',async({page})=>{
 await mockReviewRecorder(page,Array.from(readFileSync('output/comparison-workspace-voice.wav')));
 await reviewWorkspace(page);await choose(page,'upload','Workspace sibling.pdf');
 const dialog=viewer(page),root=dialog.locator(`.comparison-approval-document[data-design-id="${ids.review_sibling}"]`),form=root.locator('#cadReviewForm');
 await form.locator('[data-voice-action="record"]').click();await expect(form.locator('[data-voice-recording]')).toBeVisible();
 await form.locator('[data-voice-action="stop"]').click();await expect(form.locator('[data-voice-preview]')).toBeVisible();
 await choose(page,'upload','Workspace primary.png');await choose(page,'upload','Workspace sibling.pdf');await expect(form.locator('[data-voice-preview]')).toBeVisible();
 expect(await form.locator('[name="voice_note"]').evaluate((input:HTMLInputElement)=>input.files!.length)).toBe(1);
 page.once('dialog',dialog=>dialog.dismiss());await page.keyboard.press('Escape');await expect(dialog).toBeVisible();
 await form.locator('button[value="approved"]').click();await expect(form).toHaveCount(0);await expect(root.locator('[data-workspace-feedback]')).toContainText('recorded');
  await expect(dialog).toHaveAttribute('data-review-saving','false');
 const bubble=root.locator('.workspace-history .review-voice-bubble');await expect(bubble).toHaveCount(1);await bubble.getByRole('button',{name:'Play voice note',exact:true}).click();await expect(bubble.locator('audio')).toHaveJSProperty('paused',false);
 await bubble.locator('audio').evaluate(el=>{const a=el as HTMLAudioElement;a.currentTime=1;a.dispatchEvent(new Event('timeupdate'));});
  await expect.poll(()=>bubble.locator('input[type="range"]').inputValue()).not.toBe('0');
 await choose(page,'upload','Workspace primary.png');await expect(dialog.locator(`.comparison-approval-document[data-design-id="${ids.review_primary}"] .workspace-history .review-voice-bubble`)).toHaveCount(0);
 expect(await page.evaluate(()=>(window as any).__voice.stopped)).toBe(1);await page.keyboard.press('Escape');await expect(dialog).not.toBeVisible();
});

test('live history revocation and grant preserve an unsaved comparison review draft',async({page})=>{
 await reviewWorkspace(page,'comparison_browser_admin');await choose(page,'upload','Workspace sibling.pdf');
 const root=viewer(page).locator(`.comparison-approval-document[data-design-id="${ids.review_sibling}"]`);
 const actor=await page.evaluate(()=>JSON.parse(document.getElementById('fabro-activity-sync')!.textContent!).user_id);
 await root.locator('#review-tab-ed').click();await root.locator('#edCommentInput').fill('Keep this draft through access changes');
 try {
  runDjangoCode(`from management.models import UserProfile; UserProfile.objects.filter(user_id=${actor}).update(activity_permissions={'design_approval.history':'deny'})`);
  await expect(root.locator('.workspace-history')).not.toBeVisible({timeout:8000});
  runDjangoCode(`from management.models import UserProfile; UserProfile.objects.filter(user_id=${actor}).update(activity_permissions={})`);
  await expect(root.locator('.workspace-history')).toBeVisible({timeout:8000});
  await expect(root.locator('.workspace-history .workspace-upload-event')).toBeVisible();
  await expect(root.locator('[data-history-cycle="1"]')).toBeVisible();
  await expect(root.locator('#edCommentInput')).toHaveValue('Keep this draft through access changes');
  page.once('dialog',dialog=>dialog.accept());await page.keyboard.press('Escape');
 } finally {
  runDjangoCode(`from management.models import UserProfile; UserProfile.objects.filter(user_id=${actor}).update(activity_permissions={})`);
 }
});
