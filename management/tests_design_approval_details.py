from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse

from management.models import (
    ApprovalRoles, Brand, MasterSetting, Model, PatternDesignFolder,
    PatternDesignImage, SubModel, WorkflowRoles, YearRange,
)


class DesignApprovalDetailsTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.designer = User.objects.create_user('details_designer')
        cls.other = User.objects.create_user('details_other')
        for user in (cls.designer, cls.other):
            profile = user.workflow_profile
            profile.role = WorkflowRoles.FREELANCE_3D_DESIGNER
            profile.save()
        cls.cad = User.objects.create_user('details_cad')
        profile = cls.cad.workflow_profile
        profile.role, profile.approval_role = WorkflowRoles.APPROVER, ApprovalRoles.CAD
        profile.save()
        cls.factory = User.objects.create_user('details_factory')
        profile = cls.factory.workflow_profile
        profile.role = WorkflowRoles.FACTORY_EXECUTIVE
        profile.save()
        brand = Brand.objects.create(name='Details Brand')
        model = Model.objects.create(brand=brand, name='Details Model')
        sub = SubModel.objects.create(model=model, name='Touring')
        country = MasterSetting.objects.create(category='Country', name='Saudi Arabia')
        cls.vehicle = YearRange.objects.create(
            sub_model=sub, year_start=2024, year_end=2026,
            vehicle_country=country, layout_code='DETAILS-S237',
        )
        # Historical serials are displayed verbatim, never re-numbered on GET.
        YearRange.objects.filter(pk=cls.vehicle.pk).update(serial_number='S237')
        cls.vehicle.refresh_from_db()
        cls.folder = PatternDesignFolder.objects.create(vehicle=cls.vehicle, name='Design details')

    def image(self, **kwargs):
        data = dict(folder=self.folder, uploaded_by=self.designer,
                    image='pattern_designs/existing.png', title='Seat design.png', approval_status='pending')
        data.update(kwargs)
        return PatternDesignImage.objects.create(**data)

    def detail(self, image, user=None):
        self.client.force_login(user or self.designer)
        return self.client.get(reverse('design_approval_detail', args=[image.pk]))

    def test_folder_vehicle_full_name_and_existing_serial(self):
        image = self.image()
        response = self.detail(image)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context['design_vehicle'], self.vehicle)
        self.assertContains(response, 'Details Brand Details Model 2024-2026 Touring')
        self.assertContains(response, '<strong>S237</strong>', html=True)
        self.vehicle.refresh_from_db()
        self.assertEqual(self.vehicle.serial_number, 'S237')

    def test_direct_vehicle_takes_precedence_and_preserves_india_prefix(self):
        india, _ = MasterSetting.objects.get_or_create(category='Country', name='India')
        direct = YearRange.objects.create(sub_model=self.vehicle.sub_model,
                                         measurement_country=india, serial_number='I42', year_start=2025)
        image = self.image(vehicle=direct)
        response = self.detail(image)
        self.assertEqual(response.context['design_vehicle'].pk, direct.pk)
        self.assertContains(response, direct.serial_number)
        self.assertEqual(response.context['design_vehicle_name'], 'Details Brand Details Model 2025 Touring')

    def test_missing_association_does_not_invent_vehicle_or_gallery(self):
        image = self.image(folder=None)
        self.image(folder=None)
        response = self.detail(image)
        self.assertIsNone(response.context['design_vehicle'])
        self.assertEqual(response.context['design_vehicle_name'], '')
        self.assertEqual([entry['id'] for entry in response.context['preview_images']], [image.pk])

    def test_gallery_excludes_other_designers_folders_references_and_nonimages(self):
        image = self.image(thumbnail='pattern_design_thumbnails/existing.webp')
        sibling = self.image(image='pattern_designs/another.jpg')
        self.image(uploaded_by=self.other, approval_status='approved')
        self.image(is_reference=True)
        self.image(image='pattern_designs/design.obj')
        self.image(folder=PatternDesignFolder.objects.create(vehicle=self.vehicle, name='Other folder'))
        response = self.detail(image, self.cad)
        entries = response.context['preview_images']
        self.assertEqual([entry['id'] for entry in entries], [image.pk, sibling.pk])
        self.assertEqual(entries[0]['url'], reverse('pattern_design_image_download', args=[image.pk]))
        self.assertEqual(entries[0]['thumbnail'], reverse('design_comparison_file', args=[image.pk]) + '?thumbnail=1')
        self.assertEqual(set(entries[0]), {'id', 'title', 'url', 'thumbnail'})
        self.assertContains(response, 'id="designImageViewer"', count=1)

    def test_direct_gallery_is_scoped_to_pattern_and_uploader(self):
        image = self.image(folder=None, vehicle=self.vehicle)
        sibling = self.image(folder=None, vehicle=self.vehicle)
        self.image(folder=None, vehicle=self.vehicle, uploaded_by=self.other)
        self.image()
        entries = self.detail(image).context['preview_images']
        self.assertEqual([entry['id'] for entry in entries], [image.pk, sibling.pk])

    def test_details_and_fullsize_media_keep_existing_access_controls(self):
        image = self.image()
        from django.core.files.base import ContentFile
        from django.core.files.storage import default_storage
        saved = default_storage.save(image.image.name, ContentFile(b'private fixture'))
        image.image.name = saved
        image.save()
        self.addCleanup(default_storage.delete, saved)
        detail_url = reverse('design_approval_detail', args=[image.pk])
        media_url = reverse('pattern_design_image_download', args=[image.pk])
        self.assertEqual(self.client.get(detail_url).status_code, 302)
        self.assertEqual(self.client.get(media_url).status_code, 302)
        self.assertEqual(self.detail(image, self.other).status_code, 403)
        self.assertEqual(self.client.get(media_url).status_code, 404)
        self.assertEqual(self.detail(image, self.factory).status_code, 403)
        self.assertEqual(self.client.get(media_url).status_code, 404)
        self.assertEqual(self.detail(image, self.designer).status_code, 200)
        response = self.client.get(media_url)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(b''.join(response.streaming_content), b'private fixture')

    def test_review_defaults_and_optional_remarks_remain_intact(self):
        from management.services.design_approvals import submit_design_for_approval
        image = self.image()
        submit_design_for_approval(image, self.designer)
        response = self.detail(image, self.cad)
        self.assertContains(response, '<option value="minor" selected>Minor Change</option>', html=True)
        self.assertContains(response, 'id="cadReviewForm"')
        self.assertNotContains(response, 'Mandatory if declining')
        self.assertContains(response, 'Optional')

    def test_queue_details_link_is_direct_and_preserves_filters(self):
        from management.services.design_approvals import submit_design_for_approval
        image = self.image()
        submit_design_for_approval(image, self.designer)
        self.client.force_login(self.cad)
        response = self.client.get(reverse('approvals_list'), {'stage': 'designer', 'status': 'all', 'search': 'Seat design', 'page': 1})
        from html import escape
        href = reverse('design_approval_detail', args=[image.pk]) + '?queue_status=all&queue_search=Seat+design&queue_page=1'
        self.assertContains(response, 'href="' + escape(href, quote=True) + '"')
        self.assertNotContains(response, reverse('design_approvals_list') + '"')
        self.assertNotContains(response, 'My Designs')

    def test_review_back_url_is_stable_and_local(self):
        from urllib.parse import urlsplit, parse_qs
        image = self.image()
        self.client.force_login(self.cad)
        url = reverse('design_approval_detail', args=[image.pk])
        for params in [{}, {'queue_status': 'all', 'queue_search': 'Seat & door', 'queue_page': '2', 'next': 'https://evil.example/'},
                       {'queue_status': '//evil.example', 'queue_page': '-3'}]:
            response = self.client.get(url, params)
            back = urlsplit(response.context['design_queue_url'])
            self.assertEqual(back.path, reverse('approvals_list'))
            self.assertEqual(back.netloc, '')
            query = parse_qs(back.query)
            self.assertEqual(query['stage'], ['designer'])
            self.assertNotIn('next', query)
            self.assertIn(query['status'][0], {'active', 'all'})
            if params.get('queue_page') == '2':
                self.assertEqual(query['search'], ['Seat & door'])
                self.assertEqual(query['page'], ['2'])
            repeated = self.client.get(url, params)
            self.assertEqual(repeated.context['design_queue_url'], response.context['design_queue_url'])

    def test_legacy_gallery_redirects_to_authorized_designer_queue(self):
        from urllib.parse import parse_qs, urlsplit
        for user in [self.cad, self.designer]:
            self.client.force_login(user)
            for tab in ['pending', 'all', 'approved', 'rejected', '//evil.example']:
                response = self.client.get(reverse('design_approvals_list'), {'tab': tab, 'next': 'https://evil.example'})
                self.assertEqual(response.status_code, 302)
                self.assertEqual(urlsplit(response.url).path, reverse('approvals_list'))
                self.assertEqual(parse_qs(urlsplit(response.url).query)['stage'], ['designer'])
                self.assertNotIn('evil.example', response.url)
                self.assertEqual(self.client.get(response.url).status_code, 200)
        self.client.force_login(self.factory)
        self.assertEqual(self.client.get(reverse('design_approvals_list')).status_code, 403)
        self.client.logout()
        self.assertEqual(self.client.get(reverse('design_approvals_list')).status_code, 302)

    def test_pdf_review_reuses_authenticated_pdfjs_viewer(self):
        image = self.image(image='private_design_pdfs/opaque.pdf', title='Seat drawing.pdf', file_size=4567)
        response = self.detail(image, self.cad)
        self.assertContains(response, 'data-review-pdf-canvas')
        self.assertContains(response, 'id="designPdfViewer"', count=1)
        self.assertContains(response, 'management/js/design_pdf_viewer.js')
        self.assertContains(response, 'Download File')
        self.assertNotContains(response, '/media/private_design_pdfs/')
        self.assertNotContains(response, 'opaque.pdf')
        self.assertEqual(response.context['design_file_ext'], 'PDF')
        self.assertEqual(response.context['design_filename'], 'Seat drawing.pdf')

    def test_review_tabs_keep_all_actual_stages_and_explicit_admin_selection(self):
        from django.contrib.auth.models import User
        from management.services.design_approvals import submit_design_for_approval
        image = self.image(uploaded_by=self.cad)
        approval = submit_design_for_approval(image, self.cad)
        response = self.detail(image, self.cad)
        self.assertEqual(response.context['initial_review_stage'], 'cad')
        self.assertEqual([stage['status'] for stage in response.context['review_stages']], ['skipped_uploader', 'pending', 'pending'])
        self.assertNotContains(response, 'id="cadReviewForm"')
        admin = User.objects.create_superuser('direct_review_admin', 'a@example.com', 'unused')
        admin.workflow_profile.role = WorkflowRoles.ADMIN
        admin.workflow_profile.save()
        response = self.detail(image, admin)
        self.assertEqual(response.context['initial_review_stage'], '')
        self.assertContains(response, 'id="edReviewForm"')
        self.assertContains(response, 'id="mdReviewForm"')
        approval.refresh_from_db()
        self.assertEqual(approval.ed_status, 'pending')

    def test_review_get_does_not_change_history_notifications_or_audit(self):
        from management.models import ActivityLog, Notification
        from management.services.design_approvals import submit_design_for_approval
        image = self.image()
        submit_design_for_approval(image, self.designer)
        before = (image.approval_requests.count(), Notification.objects.count(), ActivityLog.objects.count())
        response = self.detail(image, self.cad)
        self.assertEqual(response.status_code, 200)
        self.assertEqual((image.approval_requests.count(), Notification.objects.count(), ActivityLog.objects.count()), before)

    def test_review_submission_preserves_queue_context_and_original_rules(self):
        from management.services.design_approvals import submit_design_for_approval
        image = self.image()
        submit_design_for_approval(image, self.designer)
        self.client.force_login(self.cad)
        url = reverse('design_approval_detail', args=[image.pk]) + '?queue_status=all&queue_search=Seat'
        response = self.client.post(url, dict(action='review', stage='cad', decision='approved', change_type='major', comment='  Keep exact text  '))
        self.assertEqual(response.url, url)
        approval = image.latest_approval
        self.assertEqual((approval.cad_status, approval.cad_change_type, approval.cad_comment), ('approved', 'major', '  Keep exact text  '))
        self.assertEqual(approval.ed_status, 'pending')

    def test_partial_review_uses_same_presentation_assets(self):
        image = self.image()
        self.client.force_login(self.cad)
        response = self.client.get(reverse('design_approval_detail', args=[image.pk]), HTTP_HX_REQUEST='true')
        self.assertContains(response, 'data-fabro-page-head')
        self.assertContains(response, 'management/css/design_review.css')
        self.assertContains(response, 'management/js/design_review.js')
        self.assertNotContains(response, '<!DOCTYPE html>')
