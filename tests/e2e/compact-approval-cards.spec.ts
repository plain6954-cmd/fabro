import {expect, test, type Page} from '@playwright/test';
import {readFileSync, writeFileSync} from 'fs';
import {runDjangoCode} from '../helpers/django';
import {workflowUsers} from '../helpers/testData';
let ids: Record<string,number>;
test.beforeAll(()=>{
  runDjangoCode(`
import io, json
from pathlib import Path
from unittest.mock import patch
from PIL import Image, ImageDraw
from pypdf import PdfWriter
from django.conf import settings
from django.core.files.base import ContentFile
from django.contrib.auth import get_user_model
from management.models import Brand,Model,SubModel,YearRange,PatternDesignImage,WorkflowRoles
from management.services.design_approvals import submit_design_for_approval
from management.services.design_pdfs import design_file_storage
owner,_=get_user_model().objects.get_or_create(username='compact_cards_designer')
p=owner.workflow_profile;p.role=WorkflowRoles.FREELANCE_3D_DESIGNER;p.save()
brand,_=Brand.objects.get_or_create(name='VOLVO'); model,_=Model.objects.get_or_create(brand=brand,name='XC60')
sub,_=SubModel.objects.get_or_create(model=model,name='B5')
vehicle,_=YearRange.objects.get_or_create(sub_model=sub,year_start=2025,year_end=2026,defaults={'layout_code':'COMPACT-TEST'})
brand2,_=Brand.objects.get_or_create(name='North American Extended Vehicle Programme')
model2,_=Model.objects.get_or_create(brand=brand2,name='Long wheelbase passenger series with special interior configuration')
sub2,_=SubModel.objects.get_or_create(model=model2,name='Premium extended specification')
longvehicle,_=YearRange.objects.get_or_create(sub_model=sub2,year_start=2024,year_end=2027,defaults={'layout_code':'COMPACT-LONG'})
folder=Path(settings.MEDIA_ROOT)/'compact-card-fixtures';folder.mkdir(parents=True,exist_ok=True)
image=Image.new('RGB',(600,360),'#bcae9f'); draw=ImageDraw.Draw(image)
draw.rounded_rectangle((140,20,460,215),radius=50,fill='#5c514b',outline='#eee0d4',width=3)
draw.rounded_rectangle((100,220,500,340),radius=35,fill='#756258',outline='#eee0d4',width=3)
image.save(folder/'actual-seat.png')
writer=PdfWriter();writer.add_blank_page(width=500,height=700);data=io.BytesIO();writer.write(data)
name=design_file_storage('private_design_pdfs/compact-cards.pdf').save('private_design_pdfs/compact-cards.pdf',ContentFile(data.getvalue()))
PatternDesignImage.objects.filter(uploaded_by=owner).delete()
PatternDesignImage.objects.filter(uploaded_by__username='fabro_e2e_cad',title='Compact CAD uploader.png').delete()
ids={}
with patch('management.services.push_notifications.send_push_to_user'):
    for kind,title,file,v,by in [
        ('image','Compact seat image.png','compact-card-fixtures/actual-seat.png',vehicle,owner),
        ('pdf','Compact drawing.PDF',name,vehicle,owner),
        ('long','Compact '+('stitch_dimension_'*12)+'.png','compact-card-fixtures/actual-seat.png',longvehicle,owner),
        ('skipped','Compact CAD uploader.png','compact-card-fixtures/actual-seat.png',vehicle,get_user_model().objects.get(username='fabro_e2e_cad')),
    ]:
        row=PatternDesignImage.objects.create(vehicle=v,uploaded_by=by,title=title,image=file,file_size=2048)
        submit_design_for_approval(row,by);ids[kind]=row.pk
(settings.BASE_DIR/'output/compact-card-ids.json').write_text(json.dumps(ids))
`);
  ids=JSON.parse(readFileSync('output/compact-card-ids.json','utf8'));
});
async function open(page:Page){
  await page.goto('/login/');await page.getByLabel('Username').fill(workflowUsers.cad.username);
  await page.getByLabel('Password').fill(workflowUsers.cad.password);await page.getByRole('button',{name:/sign in/i}).click();
  await expect(page).not.toHaveURL(/\/login\//);
  await page.goto('/approvals/?stage=designer&status=all&search=Compact');
}
test('compact vehicle-first cards retain dynamic media, direct review and authenticated downloads',async({page})=>{
  const errors:string[]=[];page.on('pageerror',e=>errors.push(e.message));
  await open(page);
  const card=page.locator(`#card-design-${ids.image}`);
  await expect(card.getByRole('heading',{name:'VOLVO XC60 B5 (2025-2026)',exact:true})).toBeVisible();
  await expect(card.locator('.designer-filename')).toHaveText('Compact seat image.png');
  const img=card.locator('.designer-thumbnail img');
  await expect.poll(()=>img.evaluate((el:HTMLImageElement)=>el.naturalWidth)).toBe(600);
  await expect(card.locator('.approver-box')).toHaveCount(3);
  await expect(card.locator('.status-pending')).toHaveCount(3);
  const skipped=page.locator(`#card-design-${ids.skipped}`);
  await expect(skipped.locator('.status-skipped_uploader')).toContainText('Skipped — Uploader');
  await expect(skipped.getByRole('button',{name:'Approve Design',exact:true})).toHaveCount(0);
  const pdf=page.locator(`#card-design-${ids.pdf}`);
  await expect(pdf.locator('.designer-pdf-thumbnail')).toContainText('PDF');
  await expect(pdf.locator('.designer-thumbnail img')).toHaveCount(0);
  const download=await card.getByRole('link',{name:'Download',exact:true}).getAttribute('href');
  const response=await page.request.get(download!);
  expect(response.ok()).toBe(true);expect(response.headers()['content-type']).toContain('image');
  const pdfDownload=await pdf.getByRole('link',{name:'Download',exact:true}).getAttribute('href');
  expect((await page.request.get(pdfDownload!)).headers()['content-type']).toContain('application/pdf');
  await card.getByRole('button',{name:'Preview design Compact seat image.png',exact:true}).click();
  await expect(page.locator('#designComparisonViewer')).toBeVisible();
  await expect.poll(()=>page.locator('#designComparisonViewer [data-comparison-panel="upload"] [data-panel-image]').evaluate((el:HTMLImageElement)=>el.naturalWidth)).toBe(600);
  await page.getByRole('button',{name:'Close comparison viewer',exact:true}).click();
  await card.getByRole('link',{name:'View Details',exact:true}).click();
  await expect(page).toHaveURL(new RegExp(`/design-approvals/${ids.image}/\\?queue_status=all&queue_search=Compact`));
  await expect(page.locator('.design-review-page')).toBeVisible();
  await page.getByRole('link',{name:'Approvals Queue',exact:true}).click();
  await expect(page.locator('#approvals-search-input')).toHaveValue('Compact');
  await expect(page.locator('.designer-approval-card')).toHaveCount(4);
  expect(errors).toEqual([]);
});
test('desktop has three compact zones; long content wraps on tablet/mobile and failed thumbnails fall back',async({page})=>{
  await open(page);
  const normal=page.locator(`#card-design-${ids.image}`),long=page.locator(`#card-design-${ids.long}`);
  const metrics:unknown[]=[];
  for(const width of [1440,1366,1024,768,375,320]){
    await page.setViewportSize({width,height:1000});
    for(const light of [false,true]){
      await page.evaluate(value=>document.body.classList.toggle('light-mode',value),light);
      for(const card of [normal,long]){
        const metric=await card.evaluate(el=>{
          const r=el.getBoundingClientRect();const zones=Array.from(el.querySelectorAll('.designer-card-content > *')).map(z=>{const b=z.getBoundingClientRect();return {x:b.x,y:b.y,width:b.width,height:b.height};});
          const nodes=Array.from(el.querySelectorAll('.designer-vehicle-heading,.designer-filename,.designer-card-actions a,.designer-card-actions button'));
          return {height:r.height,width:r.width,x:r.x,zones,overflow:nodes.some(n=>n.scrollWidth>n.clientWidth+1),text:el.querySelector('h2')!.textContent};
        });
        expect(metric.x).toBeGreaterThanOrEqual(0);expect(metric.x+metric.width).toBeLessThanOrEqual(width+1);expect(metric.overflow).toBe(false);
        if(width>=1200){expect(Math.abs(metric.zones[0].y-metric.zones[1].y)).toBeLessThan(25);expect(metric.zones[2].x).toBeGreaterThan(metric.zones[1].x);}
        if(width<=640){expect(metric.zones[1].y).toBeGreaterThan(metric.zones[0].y);expect(metric.zones[2].y).toBeGreaterThan(metric.zones[1].y);}
        if(width===1366&&card===normal){expect(metric.height).toBeGreaterThanOrEqual(200);expect(metric.height).toBeLessThanOrEqual(250);}
        metrics.push({viewport:width,light,...metric});
      }
      const sizes=await normal.locator('.designer-card-actions > *').evaluateAll(nodes=>nodes.map(el=>el.getBoundingClientRect().height));
      expect(Math.max(...sizes)-Math.min(...sizes)).toBeLessThan(2);expect(Math.min(...sizes)).toBeGreaterThanOrEqual(width<=640?44:38);
      expect(await page.evaluate(()=>document.documentElement.scrollWidth-innerWidth)).toBeLessThanOrEqual(1);
    }
  }
  await page.setViewportSize({width:1366,height:1000});await page.evaluate(()=>document.body.classList.remove('light-mode'));
  await normal.screenshot({path:'output/compact-approval-card-desktop.png'});
  await page.route(`**/design-images/${ids.image}/download/`,route=>route.fulfill({status:404,body:'Missing'}));
  await page.reload();
  await expect(normal.locator('.designer-thumbnail')).toHaveClass(/is-unavailable/);
  await expect(normal.locator('.designer-thumbnail img')).toBeHidden();
  await expect(normal.locator('.designer-thumbnail-fallback')).toBeVisible();
  await expect(normal.locator('.designer-thumbnail-fallback')).toContainText('Compact seat image.png');
  writeFileSync('output/compact-card-metrics.json',JSON.stringify(metrics,null,2));
});
