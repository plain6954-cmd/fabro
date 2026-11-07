"""Latest-version status is read-only and retains existing workflow authorization."""
from datetime import timedelta
import io
from unittest.mock import patch

from django.contrib.auth.models import User
from django.core.files.uploadedfile import SimpleUploadedFile
from django.db import connection
from django.test import RequestFactory, TestCase
from django.test.utils import CaptureQueriesContext
from django.urls import reverse
from django.utils import timezone
from PIL import Image

from management.models import (Brand, Model, SubModel, YearRange, WorkflowRoles, MasterSetting,
    PatternDesignImage, PatternDesignFolder, PatternDesignApproval, Notification, ActivityLog)
from management.services.design_approvals import record_design_review_decision, submit_design_for_approval
from management.services.design_status import final_outcome, status_context, vehicle_identity


class DesignStatusTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.designer=cls.account('status-designer',WorkflowRoles.FREELANCE_3D_DESIGNER)
        cls.other=cls.account('status-other',WorkflowRoles.FREELANCE_3D_DESIGNER)
        cls.reviewers={role:cls.account('status-'+role.lower(),WorkflowRoles.APPROVER,role) for role in ('CAD','ED','MD','OM')}
        cls.brand=Brand.objects.create(name='Status & Brand')
        cls.model=Model.objects.create(brand=cls.brand,name='Actual Model')
        cls.variant=SubModel.objects.create(model=cls.model,name='N1')

    @classmethod
    def account(cls,name,role,stage=''):
        user=User.objects.create_user(name)
        person=user.workflow_profile;person.role=role;person.approval_role=stage;person.save()
        return user

    def setUp(self):
        self.client.force_login(self.reviewers['CAD'])
        push=patch('management.services.push_notifications.send_push_to_user')
        self.push=push.start();self.addCleanup(push.stop)

    def pattern(self,**extra):
        return YearRange.objects.create(sub_model=self.variant,br='Hybrid',year_start=2024,year_end=2026,
            number_of_seats=5,number_of_doors=4,**extra)

    def design(self,vehicle=None,*,owner=None,reference=False,folder=None,when=None,title='Designer.png',submit=True):
        image=PatternDesignImage.objects.create(vehicle=vehicle,folder=folder,uploaded_by=owner or self.designer,
            is_reference=reference,image='status-fixtures/'+title,title=title,approval_status='approved' if reference else 'pending')
        if not reference and submit:submit_design_for_approval(image,image.uploaded_by)
        if when:PatternDesignImage.objects.filter(pk=image.pk).update(uploaded_at=when)
        image.refresh_from_db();return image

    def decide(self,image,stage,decision='approved'):
        return record_design_review_decision(image,self.reviewers[stage],decision,'Recorded '+stage,change_type='minor')

    def context(self,user=None,**params):
        request=RequestFactory().get('/car-details/',dict(subwindow='3d-status',**params))
        request.user=user or self.reviewers['CAD']
        return status_context(request)

    def versions(self):
        vehicle=self.pattern(); now=timezone.now()
        first=self.design(vehicle,when=now-timedelta(days=2),title='Version1.png')
        for stage in ('CAD','ED','MD'):self.decide(first,stage)
        second=self.design(vehicle,when=now-timedelta(days=1),title='Version2.png')
        self.decide(second,'CAD','rejected')
        latest=self.design(vehicle,when=now,title='Version3.png')
        return vehicle,first,second,latest

    def test_three_version_manifest_and_status_use_current_file_and_cycle(self):
        vehicle,approved,rejected,pending=self.versions()
        response=self.client.get(reverse('design_comparison_manifest',args=[approved.pk]))
        self.assertEqual(response.status_code,200)
        data=response.json()
        self.assertEqual(data['latest_upload_id'],pending.pk)
        outcomes={row['id']:row['approval_status'] for row in data['uploads']}
        self.assertEqual(outcomes,{approved.pk:'approved',rejected.pk:'rejected',pending.pk:'pending'})
        row=self.context()['status_rows'][0]
        self.assertEqual((row['image'].pk,row['image'].uploaded_at,row['uploader'],row['outcome'],row['priority']),
                         (pending.pk,pending.uploaded_at,self.designer.username,'pending',0))
        self.assertEqual([stage['status'] for stage in row['stages']],['pending']*3)
        self.assertTrue(all(stage['date'] is None for stage in row['stages']))

    def test_timestamp_then_primary_key_not_reference_time_filename_or_array_order(self):
        vehicle=self.pattern(); now=timezone.now()
        first=self.design(vehicle,when=now,title='Z-last-name.png')
        second=self.design(vehicle,when=now,title='A-first-name.png')
        self.design(vehicle,when=now+timedelta(days=9),reference=True,title='NewestReference.png')
        data=self.client.get(reverse('design_comparison_manifest',args=[first.pk])).json()
        self.assertEqual(data['latest_upload_id'],second.pk)
        self.assertEqual(self.context()['status_rows'][0]['image'].pk,second.pk)
        PatternDesignImage.objects.filter(pk=first.pk).update(uploaded_at=now+timedelta(seconds=1))
        self.assertEqual(self.client.get(reverse('design_comparison_manifest',args=[second.pk])).json()['latest_upload_id'],first.pk)
        self.assertEqual(self.context()['status_rows'][0]['image'].pk,first.pk)

    def test_latest_uploader_and_private_delivery_headers(self):
        vehicle=self.pattern();self.design(vehicle)
        latest=self.design(vehicle,owner=self.other,title='DifferentUploader.png')
        row=self.context()['status_rows'][0]
        self.assertEqual((row['image'].pk,row['uploader']),(latest.pk,self.other.username))
        for params in ({'subwindow':'3d-status'},{'status_fragment':'1'}):
            response=self.client.get(reverse('car_details'),params)
            self.assertEqual(response.status_code,200)
            self.assertIn('private',response['Cache-Control']);self.assertIn('no-store',response['Cache-Control'])
        PatternDesignImage.objects.filter(pk=latest.pk).update(uploaded_by=None)
        self.assertEqual(self.context()['status_rows'][0]['uploader'],'')

    def test_uploader_sort_uses_the_displayed_name(self):
        User.objects.filter(pk=self.designer.pk).update(first_name='Zulu')
        User.objects.filter(pk=self.other.pk).update(first_name='Alpha')
        self.design(self.pattern(),owner=self.designer)
        self.design(self.pattern(),owner=self.other)
        rows=self.context(status_sort='uploader',status_direction='asc')['status_rows']
        self.assertEqual([row['uploader'] for row in rows],['Alpha','Zulu'])

    def test_approval_view_denial_redacts_individual_decisions_and_dates(self):
        image=self.design(self.pattern());self.decide(image,'CAD')
        profile=self.reviewers['CAD'].workflow_profile
        profile.activity_permissions={'design_approval.view':'deny'};profile.save()
        user=User.objects.get(pk=self.reviewers['CAD'].pk)
        row=self.context(user)['status_rows'][0]
        self.assertTrue(all(stage['status']=='restricted' and stage['date'] is None for stage in row['stages']))
        self.assertEqual(row['priority'],1)

    def test_reference_only_empty_and_unassigned_files_never_create_rows(self):
        self.pattern()
        ref=self.pattern();self.design(ref,reference=True)
        self.design(None)
        vehicle=self.pattern();image=self.design(vehicle)
        PatternDesignImage.objects.filter(pk=image.pk).update(image='')
        self.assertEqual(self.context()['status_rows'],[])

    def test_folder_versions_use_effective_vehicle_and_direct_vehicle_wins(self):
        first,second=self.pattern(),self.pattern()
        folder=PatternDesignFolder.objects.create(vehicle=first,name='Scoped folder')
        image=self.design(None,folder=folder)
        self.assertEqual(self.context()['status_rows'][0]['vehicle'].pk,first.pk)
        PatternDesignImage.objects.filter(pk=image.pk).update(vehicle=second.pk)
        rows=self.context()['status_rows']
        self.assertEqual([row['vehicle'].pk for row in rows],[second.pk])

    def test_partial_and_new_cycle_never_inherit_old_approved_outcome(self):
        image=self.design(self.pattern())
        self.decide(image,'CAD')
        self.assertEqual(final_outcome(image),'pending')
        PatternDesignImage.objects.filter(pk=image.pk).update(approval_status='approved')
        image.refresh_from_db()
        self.assertEqual(final_outcome(image),'pending')
        self.decide(image,'ED','rejected')
        image.refresh_from_db()
        self.assertEqual(final_outcome(image),'rejected')
        submit_design_for_approval(image,self.designer,is_resubmission=True)
        self.assertEqual(final_outcome(image),'pending')
        row=self.context()['status_rows'][0]
        self.assertEqual(row['cycle'],2)
        self.assertEqual(row['outcome'],'pending')

    def test_individual_md_ed_decisions_and_dates_remain_separate(self):
        image=self.design(self.pattern());self.decide(image,'ED')
        row=self.context()['status_rows'][0]
        self.assertEqual(row['outcome'],'pending')
        ed,md=row['stages'][1:]
        self.assertEqual((ed['status'],md['status']),('approved','pending'))
        self.assertIsNotNone(ed['date']);self.assertIsNone(md['date'])
        response=self.client.get(reverse('car_details'),{'subwindow':'3d-status','status_fragment':'1'})
        self.assertContains(response,'ED: Approved');self.assertContains(response,'MD: Pending')

    def test_identity_includes_database_sub_model_variant_pattern_and_safe_missing_values(self):
        vehicle=self.pattern()
        identity=vehicle_identity(vehicle)
        self.assertEqual(identity['heading'],'Status & Brand Actual Model Hybrid 2024–2026 N1')
        self.assertEqual(identity['full'],vehicle.serial_number+' — Status & Brand Actual Model Hybrid N1 (2024–2026)')
        vehicle.br='';vehicle.sub_model.name='-';vehicle.year_start=None;vehicle.year_end=None
        identity=vehicle_identity(vehicle)
        self.assertNotIn('None',identity['full']);self.assertNotIn('()',identity['full'])
        self.assertNotIn('  ',identity['full']);self.assertEqual(vehicle_identity(None)['full'],'')
        vehicle.br='<Hybrid & Turbo>';vehicle.save(update_fields=['br'])
        image=self.design(vehicle)
        response=self.client.get(reverse('car_details'),{'subwindow':'3d-status'})
        self.assertContains(response,'&lt;Hybrid &amp; Turbo&gt;');self.assertNotContains(response,'<Hybrid & Turbo>')
        manifest=self.client.get(reverse('design_comparison_manifest',args=[image.pk])).json()
        self.assertIn('<Hybrid & Turbo>',manifest['identity'])

    def test_role_actionable_priority_completed_stages_rejection_and_approval(self):
        first=self.design(self.pattern());self.decide(first,'CAD')
        second=self.design(self.pattern());self.decide(second,'ED')
        rejected=self.design(self.pattern());self.decide(rejected,'CAD','rejected')
        approved=self.design(self.pattern())
        for stage in ('CAD','ED','MD'):self.decide(approved,stage)
        for role,actionable in [('CAD',second),('ED',first),('MD',second)]:
            with self.subTest(role=role):
                rows=self.context(self.reviewers[role])['status_rows']
                self.assertEqual(rows[0]['image'].pk,actionable.pk)
                self.assertEqual(rows[-1]['image'].pk,approved.pk)
                self.assertEqual(rows[-2]['image'].pk,rejected.pk)
                self.assertEqual(rows[0]['priority'],0)
        rows=self.context(self.reviewers['OM'])['status_rows']
        self.assertTrue(all(row['priority']==1 for row in rows[:2]))
        self.assertEqual([row['outcome'] for row in rows[-2:]],['rejected','approved'])

    def test_own_upload_skipped_stage_and_denied_actions_are_not_actionable(self):
        own=self.design(self.pattern(),owner=self.reviewers['MD'])
        self.assertEqual(own.latest_approval.md_status,'skipped_uploader')
        self.assertEqual(self.context(self.reviewers['MD'])['status_rows'][0]['priority'],1)
        profile=self.reviewers['CAD'].workflow_profile
        profile.activity_permissions={'design_approval.approve':'deny','design_approval.reject':'deny'};profile.save()
        user=User.objects.get(pk=self.reviewers['CAD'].pk)
        self.assertEqual(self.context(user)['status_rows'][0]['priority'],1)

    def test_manual_sort_search_pagination_and_deterministic_default_ties(self):
        now=timezone.now(); images=[]
        for index in range(23):
            images.append(self.design(self.pattern(),when=now,title=f'Needle-{index:02d}.png',submit=False))
        result=self.context(status_search='Needle',status_page_size='20')
        self.assertEqual(result['status_page'].paginator.count,23)
        self.assertEqual([row['image'].pk for row in result['status_rows']],[image.pk for image in reversed(images[-20:])])
        self.assertEqual(len(self.context(status_search='Needle',status_page='2')['status_rows']),3)
        manual=self.context(status_sort='pattern',status_direction='asc',status_search='Needle',status_page_size='50')
        serials=[row['vehicle'].serial_number for row in manual['status_rows']]
        self.assertEqual(serials,sorted(serials));self.assertEqual(len(serials),23)
        self.assertEqual(self.context(status_search='No match')['status_rows'],[])
        self.assertEqual(self.context(status_page_size='invalid')['status_page_size'],20)

    def test_no_fallback_to_older_visible_upload_and_no_cross_country_leak(self):
        vehicle=self.pattern();old=self.design(vehicle,owner=self.other,submit=False)
        PatternDesignImage.objects.filter(pk=old.pk).update(approval_status='approved')
        latest=self.design(vehicle)
        self.assertEqual(self.context(self.other)['status_rows'],[])
        for role in ('CAD','ED','MD'):self.decide(latest,role)
        country=MasterSetting.objects.create(category='Country',name='Status foreign')
        ce=self.account('status-ce',WorkflowRoles.COUNTRY_EXECUTIVE)
        person=ce.workflow_profile;person.country=country;person.activity_permissions={'design.view_all':'allow'};person.save()
        self.assertEqual(self.context(ce)['status_rows'],[])
        vehicle.vehicle_country=country;vehicle.save(update_fields=['vehicle_country'])
        self.assertEqual(len(self.context(ce)['status_rows']),1)

    def test_history_denial_hides_dates_without_exposing_comments(self):
        image=self.design(self.pattern());self.decide(image,'CAD')
        profile=self.reviewers['CAD'].workflow_profile
        profile.activity_permissions={'design.history':'deny','design_approval.history':'deny'};profile.save()
        user=User.objects.get(pk=self.reviewers['CAD'].pk)
        self.assertTrue(all(stage['date'] is None for stage in self.context(user)['status_rows'][0]['stages']))
        self.client.force_login(user)
        response=self.client.get(reverse('car_details'),{'subwindow':'3d-status','status_fragment':'1'})
        self.assertNotContains(response,'Recorded CAD')

    def test_query_count_is_bounded_and_status_reads_do_not_notify_or_write(self):
        for _ in range(21):self.design(self.pattern(),submit=False)
        logs,notifications=ActivityLog.objects.count(),Notification.objects.count()
        with CaptureQueriesContext(connection) as queries:
            result=self.context(status_page_size='50')
            self.assertEqual(len(result['status_rows']),21)
        self.assertLessEqual(len(queries),8)
        self.assertEqual((ActivityLog.objects.count(),Notification.objects.count()),(logs,notifications))
        self.push.assert_not_called()

    def test_status_access_denial_and_original_pattern_columns_unchanged(self):
        response=self.client.get(reverse('car_details'))
        for text in ('X-Code','Fitting Confirm','Vehicle Country','Measurement Country','Drive'):
            self.assertContains(response,text)
        profile=self.reviewers['CAD'].workflow_profile
        profile.activity_permissions={'design.view_all':'deny','design.view_own':'deny'};profile.save()
        self.assertEqual(self.client.get(reverse('car_details'),{'subwindow':'3d-status'}).status_code,403)
        self.assertEqual(self.client.get(reverse('car_details'),{'status_fragment':'1'}).status_code,403)

    def test_successful_upload_returns_server_selected_id_and_failure_changes_nothing(self):
        self.client.force_login(self.designer)
        vehicle=self.pattern();old=self.design(vehicle)
        stream=io.BytesIO();Image.new('RGB',(12,8),'red').save(stream,'PNG')
        url=reverse('upload_vehicle_design_images_api',args=[vehicle.pk])
        response=self.client.post(url,{'images':SimpleUploadedFile('New.png',stream.getvalue(),'image/png')},HTTP_X_UPLOAD_ID='status-new')
        self.assertEqual(response.status_code,200,response.content)
        latest=response.json()['latest_uploaded_id']
        self.assertNotEqual(latest,old.pk)
        self.assertEqual(self.client.get(reverse('design_comparison_manifest',args=[old.pk])).json()['latest_upload_id'],latest)
        response=self.client.post(url,{'images':SimpleUploadedFile('Bad.png',b'invalid','image/png')})
        self.assertEqual(response.status_code,400)
        self.assertEqual(self.client.get(reverse('design_comparison_manifest',args=[old.pk])).json()['latest_upload_id'],latest)
