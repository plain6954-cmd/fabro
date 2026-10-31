from unittest.mock import patch
from django.contrib.auth.models import User
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, Client
from django.urls import reverse

from management.models import (
    ApprovalRoles,
    Brand,
    Model,
    PatternDesignFolder,
    PatternDesignImage,
    SubModel,
    WorkflowRoles,
    YearRange,
)
from management.services.design_approvals import submit_design_for_approval, record_design_review_decision


class DesignerApprovalsWorkspaceTests(TestCase):
    def setUp(self):
        self.client = Client()
        tiny_gif = b'GIF89a\x01\x00\x01\x00\x80\x00\x00\x00\x00\x00\xff\xff\xff!\xf9\x04\x01\x00\x00\x00\x00,\x00\x00\x00\x00\x01\x00\x01\x00\x00\x02\x02D\x01\x00;'
        self.upload_patcher = patch('management.storage_backends.upload_content', return_value='ok')
        self.url_patcher = patch('management.storage_backends.create_signed_download_url', return_value='/media/test.gif')
        self.download_patcher = patch('management.storage_backends.download_content', return_value=tiny_gif)
        self.upload_patcher.start()
        self.url_patcher.start()
        self.download_patcher.start()
        self.addCleanup(self.upload_patcher.stop)
        self.addCleanup(self.url_patcher.stop)
        self.addCleanup(self.download_patcher.stop)

        # 1. Admin
        self.admin_user = User.objects.create_user(
            username='admin_ws_test',
            email='admin_ws@fabro.test',
            is_staff=True,
            is_superuser=True,
        )

        # 2. CAD Approver
        self.cad_user = User.objects.create_user(
            username='cad_ws_test',
            email='cad_ws@fabro.test',
        )
        self.cad_user.workflow_profile.role = WorkflowRoles.APPROVER
        self.cad_user.workflow_profile.approval_role = ApprovalRoles.CAD
        self.cad_user.workflow_profile.save()

        # 3. PM Approver
        self.pm_user = User.objects.create_user(
            username='pm_ws_test',
            email='pm_ws@fabro.test',
        )
        self.pm_user.workflow_profile.role = WorkflowRoles.APPROVER
        self.pm_user.workflow_profile.approval_role = ApprovalRoles.PM
        self.pm_user.workflow_profile.save()

        # 4. OM Approver (unauthorized for designer upload window)
        self.om_user = User.objects.create_user(
            username='om_ws_test',
            email='om_ws@fabro.test',
        )
        self.om_user.workflow_profile.role = WorkflowRoles.APPROVER
        self.om_user.workflow_profile.approval_role = ApprovalRoles.OM
        self.om_user.workflow_profile.save()

        # 5. Country Executive (unauthorized for designer upload window)
        self.country_user = User.objects.create_user(
            username='country_ws_test',
            email='country_ws@fabro.test',
        )
        self.country_user.workflow_profile.role = WorkflowRoles.COUNTRY_EXECUTIVE
        self.country_user.workflow_profile.save()

        # 6. Factory Executive (unauthorized for designer upload window)
        self.factory_user = User.objects.create_user(
            username='factory_ws_test',
            email='factory_ws@fabro.test',
        )
        self.factory_user.workflow_profile.role = WorkflowRoles.FACTORY_EXECUTIVE
        self.factory_user.workflow_profile.save()

        # 7. Submitting 3D Designer
        self.designer = User.objects.create_user(
            username='designer_ws_test',
            email='designer_ws@fabro.test',
        )
        self.designer.workflow_profile.role = WorkflowRoles.FREELANCE_3D_DESIGNER
        self.designer.workflow_profile.save()

        # Catalog setup
        self.brand = Brand.objects.create(name='Audi Test')
        self.model = Model.objects.create(brand=self.brand, name='Q7')
        self.sub_model = SubModel.objects.create(model=self.model, name='Prestige')
        self.vehicle = YearRange.objects.create(
            sub_model=self.sub_model,
            year_start=2023,
            year_end=2025,
            layout_code='Q7-2325',
        )
        self.folder = PatternDesignFolder.objects.create(
            vehicle=self.vehicle,
            name='Seat Patterns 3D',
        )

        file_obj = SimpleUploadedFile('q7_driver_cushion.gif', tiny_gif, content_type='image/gif')
        self.design_img = PatternDesignImage.objects.create(
            folder=self.folder,
            vehicle=self.vehicle,
            image=file_obj,
            title='q7_driver_cushion.gif',
            file_size=len(tiny_gif),
            uploaded_by=self.designer,
            approval_status='pending',
        )
        submit_design_for_approval(self.design_img, self.designer)

    def test_cad_can_access_designer_stage_and_sees_tab(self):
        self.client.force_login(self.cad_user)
        res = self.client.get(reverse('approvals_list'))
        self.assertEqual(res.status_code, 200)
        self.assertContains(res, 'Designer Uploads')
        self.assertContains(res, '?stage=designer&status=active')

        res_stage = self.client.get(reverse('approvals_list') + '?stage=designer&status=active')
        self.assertEqual(res_stage.status_code, 200)
        self.assertContains(res_stage, 'q7_driver_cushion.gif')
        self.assertContains(res_stage, 'Audi Test Q7 Prestige (2023-2025)')
        self.assertContains(res_stage, 'Live Design Reviewer Matrix')

    def test_pm_can_access_designer_stage_and_sees_tab(self):
        self.client.force_login(self.pm_user)
        res = self.client.get(reverse('approvals_list'))
        self.assertEqual(res.status_code, 200)
        self.assertContains(res, 'Designer Uploads')

        res_stage = self.client.get(reverse('approvals_list') + '?stage=designer&status=active')
        self.assertEqual(res_stage.status_code, 200)
        self.assertContains(res_stage, 'q7_driver_cushion.gif')

    def test_admin_can_access_designer_stage_and_sees_tab(self):
        self.client.force_login(self.admin_user)
        res = self.client.get(reverse('approvals_list'))
        self.assertEqual(res.status_code, 200)
        self.assertContains(res, 'Designer Uploads')

        res_stage = self.client.get(reverse('approvals_list') + '?stage=designer&status=active')
        self.assertEqual(res_stage.status_code, 200)
        self.assertContains(res_stage, 'q7_driver_cushion.gif')

    def test_country_executive_cannot_see_tab_and_is_blocked_from_designer_stage(self):
        self.client.force_login(self.country_user)
        res = self.client.get(reverse('approvals_list'))
        self.assertEqual(res.status_code, 200)
        self.assertNotContains(res, 'Designer Uploads')

        res_stage = self.client.get(reverse('approvals_list') + '?stage=designer&status=active')
        self.assertEqual(res_stage.status_code, 403)

    def test_factory_executive_cannot_see_tab_and_is_blocked_from_designer_stage(self):
        self.client.force_login(self.factory_user)
        res = self.client.get(reverse('approvals_list'))
        self.assertEqual(res.status_code, 200)
        self.assertNotContains(res, 'Designer Uploads')

        res_stage = self.client.get(reverse('approvals_list') + '?stage=designer&status=active')
        self.assertEqual(res_stage.status_code, 403)

    def test_om_approver_can_view_designer_stage_read_only(self):
        self.client.force_login(self.om_user)
        res = self.client.get(reverse('approvals_list'))
        self.assertEqual(res.status_code, 200)
        self.assertContains(res, 'Designer Uploads')

        res_stage = self.client.get(reverse('approvals_list') + '?stage=designer&status=active')
        self.assertEqual(res_stage.status_code, 200)
        self.assertNotContains(res_stage, 'onclick="openQuickDesignReviewModal(')

    def test_partial_review_filter_and_action_modal_are_available(self):
        record_design_review_decision(self.design_img, self.cad_user, 'approved', 'Ready for ED', change_type='minor')
        self.client.force_login(self.pm_user)
        response = self.client.get(reverse('approvals_list') + '?stage=designer&status=partially_approved')
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'q7_driver_cushion.gif')
        self.assertContains(response, 'Partially Approved')
        self.client.force_login(self.cad_user)
        response = self.client.get(reverse('approvals_list') + '?stage=designer&status=my_pending')
        self.assertNotContains(response, 'card-design-' + str(self.design_img.id))

    def test_compact_card_uses_actual_vehicle_heading_and_file_metadata(self):
        import re
        from html import unescape
        self.client.force_login(self.cad_user)
        response = self.client.get(reverse('approvals_list'), {'stage': 'designer', 'status': 'all'})
        headings = re.findall(r'<h2 class="designer-vehicle-heading">(.*?)</h2>', response.content.decode(), re.S)
        self.assertEqual([' '.join(unescape(text).split()) for text in headings], ['Audi Test Q7 Prestige (2023-2025)'])
        self.assertNotIn(self.design_img.title, headings)
        self.assertContains(response, '<dd class="designer-filename">q7_driver_cushion.gif</dd>', html=True)
        self.assertContains(response, 'designer-card-actions')
        self.assertContains(response, 'designer_approval_cards.css')
        self.assertContains(response, 'data-cad-status="pending"')
        self.assertContains(response, reverse('design_approval_detail', args=[self.design_img.pk]) + '?queue_status=all')

    def test_pdf_card_shows_pdf_icon_without_exposing_private_storage_path(self):
        self.design_img.image.name = 'private_design_pdfs/opaque.PDF'
        self.design_img.title = 'Seat inspection.PDF'
        self.design_img.save(update_fields=['image', 'title'])
        self.client.force_login(self.cad_user)
        response = self.client.get(reverse('approvals_list'), {'stage': 'designer', 'status': 'all'})
        self.assertContains(response, 'designer-pdf-thumbnail')
        self.assertContains(response, 'Seat inspection.PDF')
        import re
        card = re.search(r'<article[^>]*id="card-design-' + str(self.design_img.pk) + r'".*?</article>', response.content.decode(), re.S).group(0)
        self.assertNotIn('<img ', card)
        self.assertNotContains(response, 'private_design_pdfs')
        self.assertNotContains(response, 'opaque.PDF')

    def test_folder_vehicle_heading_and_missing_vehicle_label_are_truthful(self):
        self.design_img.vehicle = None
        self.design_img.save(update_fields=['vehicle'])
        self.client.force_login(self.cad_user)
        response = self.client.get(reverse('approvals_list'), {'stage': 'designer', 'status': 'all'})
        self.assertContains(response, 'Audi Test Q7 Prestige (2023–2025)')
        self.design_img.folder = None
        self.design_img.save(update_fields=['folder'])
        response = self.client.get(reverse('approvals_list'), {'stage': 'designer', 'status': 'all'})
        self.assertContains(response, '<h2 class="designer-vehicle-heading">Vehicle not specified</h2>', html=True)

    def test_compact_cards_preserve_skipped_stage_and_readonly_actions(self):
        own = PatternDesignImage.objects.create(vehicle=self.vehicle, title='CAD upload.png',
            image='existing.png', uploaded_by=self.cad_user)
        submit_design_for_approval(own, self.cad_user)
        self.client.force_login(self.cad_user)
        response = self.client.get(reverse('approvals_list'), {'stage': 'designer', 'status': 'all'})
        self.assertContains(response, 'data-cad-status="skipped_uploader"')
        self.assertContains(response, 'Skipped — Uploader')
        self.assertContains(response, 'designer-approve')
        self.client.force_login(self.om_user)
        response = self.client.get(reverse('approvals_list'), {'stage': 'designer', 'status': 'all'})
        self.assertNotContains(response, 'onclick="openQuickDesignReviewModal(')
        self.assertContains(response, 'View Details')
        self.assertContains(response, 'Download original asset')
