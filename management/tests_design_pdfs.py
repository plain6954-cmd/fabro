import io
from pathlib import Path
from unittest.mock import patch

from django.contrib.auth.models import User
from django.core.files.base import ContentFile
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import Client, TestCase, override_settings
from django.urls import reverse
from pypdf import PdfWriter
from pypdf.generic import DecodedStreamObject, DictionaryObject, NameObject, RectangleObject

from management.models import (
    ApprovalRoles, Brand, Model, Notification, PatternDesignImage,
    SubModel, WorkflowRoles, YearRange,
)
from management.services.design_pdfs import design_file_storage


def make_pdf(encrypted=False, empty=False, bad_box=False):
    writer = PdfWriter()
    if not empty:
        for width, height, color in [(300, 400, '0 0.6 0'), (600, 300, '0.8 0 0')]:
            page = writer.add_blank_page(width, height)
            font = writer._add_object(DictionaryObject({NameObject('/Type'): NameObject('/Font'),
                NameObject('/Subtype'): NameObject('/Type1'), NameObject('/BaseFont'): NameObject('/Helvetica')}))
            page[NameObject('/Resources')] = DictionaryObject({NameObject('/Font'): DictionaryObject({NameObject('/F1'): font})})
            stream = DecodedStreamObject()
            stream.set_data(f'{color} rg 0 0 {width} {height} re f 1 1 1 rg BT /F1 18 Tf 20 {height - 40} Td (FABRO design PDF) Tj ET'.encode())
            page[NameObject('/Contents')] = writer._add_object(stream)
        if bad_box:
            writer.pages[0].mediabox = RectangleObject([0, 0, 0, 10])
    if encrypted:
        writer.encrypt('test-password', algorithm='RC4-128')
    output = io.BytesIO()
    writer.write(output)
    return output.getvalue()


class DesignPdfTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.designer = User.objects.create_user('pdf_designer')
        cls.other = User.objects.create_user('pdf_other')
        cls.factory = User.objects.create_user('pdf_factory')
        for user, role in [(cls.designer, WorkflowRoles.FREELANCE_3D_DESIGNER),
                           (cls.other, WorkflowRoles.FREELANCE_3D_DESIGNER),
                           (cls.factory, WorkflowRoles.FACTORY_EXECUTIVE)]:
            profile = user.workflow_profile
            profile.role = role
            profile.save()
        for role in (ApprovalRoles.CAD, ApprovalRoles.ED, ApprovalRoles.MD, ApprovalRoles.OM, ApprovalRoles.PM):
            user = User.objects.create_user('pdf_' + role.lower())
            profile = user.workflow_profile
            profile.role, profile.approval_role = WorkflowRoles.APPROVER, role
            profile.save()
        brand = Brand.objects.create(name='PDF Brand')
        model = Model.objects.create(brand=brand, name='PDF Model')
        sub = SubModel.objects.create(model=model, name='PDF Sub')
        cls.vehicle = YearRange.objects.create(sub_model=sub, year_start=2026, layout_code='PDF-TEST')
        cls.upload_url = reverse('upload_vehicle_design_images_api', args=[cls.vehicle.pk])

    def upload(self, content=None, **kwargs):
        self.client.force_login(self.designer)
        return self.client.post(self.upload_url, {
            'images': SimpleUploadedFile('Seat design.pdf', make_pdf() if content is None else content, 'application/pdf'),
            **kwargs.pop('data', {}),
        }, **kwargs)

    def test_valid_pdf_is_private_and_uses_existing_record_and_approval(self):
        response = self.upload()
        self.assertEqual(response.status_code, 200)
        image = PatternDesignImage.objects.get()
        self.assertTrue(image.is_pdf)
        self.assertTrue(image.image.name.startswith('private_design_pdfs/'))
        storage = design_file_storage(image.image.name)
        self.assertTrue(storage.exists(image.image.name))
        from django.conf import settings
        self.assertFalse(Path(storage.path(image.image.name)).is_relative_to(Path(settings.MEDIA_ROOT)))
        self.assertEqual(image.approval_status, 'pending')
        self.assertEqual(image.latest_approval.cad_status, 'pending')
        url = reverse('pattern_design_image_download', args=[image.pk])
        self.assertEqual(response.json()['images'][0]['url'], reverse('design_comparison_file', args=[image.pk]))
        self.assertEqual(response.json()['images'][0]['original_url'], url)
        # A display title without an extension does not change the actual PDF type.
        image.title = 'Renamed seat design'
        image.save(update_fields=['title'])
        data = self.client.get(reverse('get_design_folders_api'), {'vehicle_id': self.vehicle.pk}).json()['design_files'][0]
        self.assertEqual((data['file_type'], data['url'], data['preview_url']), ('pdf', url, url))

    def test_invalid_truncated_encrypted_empty_and_bad_page_pdfs_rejected(self):
        for content in [b'<html>not a PDF</html>', b'%PDF-1.7\ncorrupt\n%%EOF',
                        make_pdf()[:120], make_pdf(encrypted=True), make_pdf(empty=True), make_pdf(bad_box=True)]:
            with self.subTest(content=content[:20]):
                self.assertEqual(self.upload(content).status_code, 400)
        self.assertFalse(PatternDesignImage.objects.exists())
        self.assertFalse(Notification.objects.exists())

    def test_authentication_permissions_csrf_and_size_limit_still_apply(self):
        self.client.force_login(self.factory)
        self.assertEqual(self.client.post(self.upload_url, {'images': SimpleUploadedFile('x.pdf', make_pdf())}).status_code, 403)
        csrf = Client(enforce_csrf_checks=True)
        csrf.force_login(self.designer)
        self.assertEqual(csrf.post(self.upload_url, {'images': SimpleUploadedFile('x.pdf', make_pdf())}).status_code, 403)
        with patch('management.views.validate_design_pdf') as validate:
            large = SimpleUploadedFile('large.pdf', b'%PDF-1.7')
            large.size = 50 * 1024 * 1024 + 1
            # Directly exercise the existing request validation without allocating 50 MB.
            from django.test import RequestFactory
            from management.views import _upload_design_files
            request = RequestFactory().post(self.upload_url)
            request.FILES.setlist('images', [large])
            request.user = self.designer
            self.assertEqual(_upload_design_files(request, vehicle=self.vehicle).status_code, 400)
            validate.assert_not_called()

    def test_pdf_bytes_and_download_are_authenticated_without_storage_redirect(self):
        self.upload()
        image = PatternDesignImage.objects.get()
        url = reverse('pattern_design_image_download', args=[image.pk])
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response['Content-Type'], 'application/pdf')
        self.assertEqual(response['Cache-Control'], 'private, no-store')
        self.assertNotIn('Location', response)
        self.assertEqual(b''.join(response.streaming_content), make_pdf())
        download = self.client.get(url + '?download=1')
        self.assertTrue(download['Content-Disposition'].startswith('attachment;'))
        self.assertEqual(b''.join(download.streaming_content), make_pdf())
        self.client.logout()
        self.assertEqual(self.client.get(url).status_code, 302)
        for user in (self.other, self.factory):
            self.client.force_login(user)
            self.assertEqual(self.client.get(url).status_code, 404)
        self.client.force_login(User.objects.get(username='pdf_cad'))
        allowed = self.client.get(url)
        self.assertEqual(allowed.status_code, 200)
        self.assertEqual(b''.join(allowed.streaming_content), make_pdf())
        for role in ('om', 'pm'):
            self.client.force_login(User.objects.get(username='pdf_' + role))
            allowed = self.client.get(url)
            self.assertEqual(allowed.status_code, 200)
            self.assertEqual(b''.join(allowed.streaming_content), make_pdf())
            self.assertEqual(self.client.post(reverse('approve_design_image_api', args=[image.pk]), {'change_type': 'minor'}).status_code, 403)

    @override_settings(USE_S3_STORAGE=True)
    def test_private_s3_bytes_use_existing_storage_adapter(self):
        image = PatternDesignImage.objects.create(vehicle=self.vehicle, uploaded_by=self.designer,
            image='private_design_pdfs/private.pdf', title='private.pdf')
        self.client.force_login(self.designer)
        with patch('management.services.design_pdfs.default_storage.open', return_value=ContentFile(make_pdf())) as opened:
            response = self.client.get(reverse('pattern_design_image_download', args=[image.pk]))
            self.assertEqual(response.status_code, 200)
            self.assertEqual(b''.join(response.streaming_content), make_pdf())
        opened.assert_called_once_with(image.image.name, 'rb')

    def test_retry_reuses_record_approval_and_notifications(self):
        self.assertEqual(self.upload(HTTP_X_UPLOAD_ID='pdf-retry').status_code, 200)
        image = PatternDesignImage.objects.get()
        approval_id = image.latest_approval.pk
        notifications = list(Notification.objects.values_list('pk', flat=True))
        self.assertEqual(self.upload(HTTP_X_UPLOAD_ID='pdf-retry').status_code, 200)
        self.assertEqual(PatternDesignImage.objects.count(), 1)
        self.assertEqual(PatternDesignImage.objects.get().latest_approval.pk, approval_id)
        self.assertEqual(list(Notification.objects.values_list('pk', flat=True)), notifications)

    def test_missing_private_pdf_and_submitted_deletion_protection(self):
        self.upload()
        image = PatternDesignImage.objects.get()
        storage = design_file_storage(image.image.name)
        approval_id = image.latest_approval.pk
        self.assertEqual(self.client.post(reverse('delete_design_image_api', args=[image.pk])).status_code, 403)
        self.assertTrue(storage.exists(image.image.name))
        image.refresh_from_db()
        self.assertEqual(image.latest_approval.pk, approval_id)
        missing = PatternDesignImage.objects.create(vehicle=self.vehicle, uploaded_by=self.designer,
            image='private_design_pdfs/missing.pdf', title='missing.pdf')
        self.assertEqual(self.client.get(reverse('pattern_design_image_download', args=[missing.pk])).status_code, 404)

    def test_pdf_replacements_are_validated_before_rework_cycle_changes(self):
        self.upload()
        image = PatternDesignImage.objects.get()
        from management.services.design_approvals import record_design_review_decision
        record_design_review_decision(image, User.objects.get(username='pdf_cad'), 'rejected', change_type='major')
        url = reverse('resubmit_design_image_api', args=[image.pk])
        response = self.client.post(url, {'image': SimpleUploadedFile('invalid.pdf', b'not PDF')})
        self.assertEqual(response.status_code, 409)  # Preserve the existing rework validation contract.
        self.assertEqual(image.approval_requests.count(), 1)
        response = self.client.post(url, {'image': SimpleUploadedFile('revised.pdf', make_pdf())})
        self.assertEqual(response.status_code, 200)
        image.refresh_from_db()
        self.assertTrue(image.is_pdf)
        self.assertEqual(image.latest_approval.cycle, 2)
