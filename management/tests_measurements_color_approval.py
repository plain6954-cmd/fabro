import io
from PIL import Image
from django.contrib.auth.models import User
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from django.urls import reverse
import tempfile

from management.models import (
    ApprovalRoles,
    Brand,
    ColorMaster,
    MasterSetting,
    Model,
    Notification,
    PatternColorApprovalDecision,
    PatternColorSelection,
    PatternMeasurementFile,
    SubModel,
    UserProfile,
    WorkflowRoles,
    YearRange,
)
from management.services.color_approval import (
    derive_rgb_cmyk_from_hex,
    get_next_colormaster_code,
    normalize_hex,
    save_color_selection,
    submit_color_decision,
)
from management.services.measurement_files import (
    save_measurement_file,
    validate_measurement_file,
)


def create_test_image(filename="swatch.jpg", format_name="JPEG", color=(180, 140, 90)):
    buf = io.BytesIO()
    img = Image.new("RGB", (100, 100), color=color)
    img.save(buf, format=format_name)
    buf.seek(0)
    return SimpleUploadedFile(filename, buf.read(), content_type=f"image/{format_name.lower()}")


from unittest.mock import patch


@override_settings(
    STORAGES={
        'default': {
            'BACKEND': 'django.core.files.storage.FileSystemStorage',
        },
        'staticfiles': {
            'BACKEND': 'django.contrib.staticfiles.storage.StaticFilesStorage',
        },
    },
    USE_S3_STORAGE=False,
    MEDIA_ROOT=tempfile.gettempdir(),
)
class MeasurementsColorApprovalTestCase(TestCase):
    def setUp(self):
        self.storage_patcher = patch('management.storage_backends.upload_content', return_value='mocked')
        self.storage_patcher.start()
        self.addCleanup(self.storage_patcher.stop)

        # Configure approver accounts
        self.md_user = User.objects.create_user(username="md_test", password="Password@123")
        self.md_user.workflow_profile.role = WorkflowRoles.APPROVER
        self.md_user.workflow_profile.approval_role = ApprovalRoles.MD
        self.md_user.workflow_profile.save()

        self.ed_user = User.objects.create_user(username="ed_test", password="Password@123")
        self.ed_user.workflow_profile.role = WorkflowRoles.APPROVER
        self.ed_user.workflow_profile.approval_role = ApprovalRoles.ED
        self.ed_user.workflow_profile.save()

        self.cad_user = User.objects.create_user(username="cad_test", password="Password@123")
        self.cad_user.workflow_profile.role = WorkflowRoles.APPROVER
        self.cad_user.workflow_profile.approval_role = ApprovalRoles.CAD
        self.cad_user.workflow_profile.save()

        self.regular_user = User.objects.create_user(username="regular_test", password="Password@123")
        self.regular_user.workflow_profile.role = WorkflowRoles.COUNTRY_EXECUTIVE
        self.regular_user.workflow_profile.save()

        # Create vehicle
        self.brand = Brand.objects.create(name="GWM")
        self.model = Model.objects.create(brand=self.brand, name="HAVAL H9")
        self.submodel = SubModel.objects.create(model=self.model, name="Deluxe")
        self.vehicle = YearRange.objects.create(
            sub_model=self.submodel,
            year_start=2025,
            year_end=2027,
            serial_number="S0237",
        )

        # Existing colors
        self.color1 = ColorMaster.objects.create(
            color_code="01",
            name="F.BEIGE",
            hex_code="#AF955C",
            pantone_code="4007 U",
            status="Active",
        )
        self.color2 = ColorMaster.objects.create(
            color_code="02",
            name="BLACK",
            hex_code="#282526",
            pantone_code="0961 C",
            status="Active",
        )

    def test_hex_normalization_and_derivation(self):
        self.assertEqual(normalize_hex("af955c"), "#AF955C")
        self.assertEqual(normalize_hex("#af955c"), "#AF955C")
        with self.assertRaises(Exception):
            normalize_hex("invalid")

        rgb_str, cmyk_str = derive_rgb_cmyk_from_hex("#AF955C")
        self.assertEqual(rgb_str, "175, 149, 92")
        self.assertTrue(len(cmyk_str) > 0)

    def test_measurement_file_upload_and_validation(self):
        # Valid DXF in scanned patterns
        dxf_file = SimpleUploadedFile("pattern.dxf", b"0\nSECTION\n2\nHEADER\n0\nENDSEC\n0\nEOF", content_type="application/dxf")
        meas_file, created = save_measurement_file(
            vehicle=self.vehicle,
            category=PatternMeasurementFile.CATEGORY_SCANNED,
            uploaded_file=dxf_file,
            user=self.regular_user,
            client_key="test_key_1",
        )
        self.assertTrue(created)
        self.assertEqual(meas_file.file_type, "dxf")
        self.assertEqual(meas_file.filename, "pattern.dxf")

        # Idempotency check with same client key
        meas_file2, created2 = save_measurement_file(
            vehicle=self.vehicle,
            category=PatternMeasurementFile.CATEGORY_SCANNED,
            uploaded_file=dxf_file,
            user=self.regular_user,
            client_key="test_key_1",
        )
        self.assertFalse(created2)
        self.assertEqual(meas_file.id, meas_file2.id)

        # Unsupported format in scanned patterns
        unsupported = SimpleUploadedFile("evil.exe", b"binary", content_type="application/x-msdownload")
        with self.assertRaises(Exception):
            validate_measurement_file(unsupported, PatternMeasurementFile.CATEGORY_SCANNED)

    def test_color_selection_existing_only_auto_approves(self):
        # Existing Single Tone
        data = {
            'tone_type': 'single',
            'inner_source': 'existing',
            'inner_existing_color_id': self.color1.id,
        }
        selection, created = save_color_selection(self.vehicle, self.regular_user, data)
        self.assertTrue(created)
        self.assertEqual(selection.status, PatternColorSelection.STATUS_APPROVED)
        self.assertFalse(selection.is_new_color)
        self.assertEqual(selection.decisions.count(), 0)

        # Existing Dual Tone
        dual_data = {
            'tone_type': 'dual',
            'inner_source': 'existing',
            'inner_existing_color_id': self.color1.id,
            'outer_source': 'existing',
            'outer_existing_color_id': self.color2.id,
        }
        dual_sel, _ = save_color_selection(self.vehicle, self.regular_user, dual_data)
        self.assertEqual(dual_sel.status, PatternColorSelection.STATUS_APPROVED)
        self.assertFalse(dual_sel.is_new_color)
        self.assertEqual(dual_sel.decisions.count(), 0)

    def test_new_color_workflow_full_approval(self):
        swatch = create_test_image("swatch.jpg")
        data = {
            'tone_type': 'dual',
            'inner_source': 'new',
            'inner_pantone_code': '5010 U',
            'inner_hex_code': '#336699',
            'inner_color_name': 'Ocean Navy',
            'outer_source': 'existing',
            'outer_existing_color_id': self.color2.id,
        }
        selection, created = save_color_selection(self.vehicle, self.regular_user, data, swatch_file=swatch)
        self.assertTrue(created)
        self.assertTrue(selection.is_new_color)
        self.assertEqual(selection.status, PatternColorSelection.STATUS_PENDING)

        # Check 3 decisions generated (MD, ED, CAD)
        decisions = {d.department: d for d in selection.decisions.all()}
        self.assertEqual(set(decisions.keys()), {'MD', 'ED', 'CAD'})
        for d in decisions.values():
            self.assertEqual(d.decision, PatternColorApprovalDecision.STATUS_PENDING)

        # Verify notifications created for approvers
        notifs = Notification.objects.filter(color_selection=selection)
        self.assertEqual(notifs.count(), 3)
        notif_recipients = set(notifs.values_list('recipient__username', flat=True))
        self.assertEqual(notif_recipients, {'md_test', 'ed_test', 'cad_test'})

        # MD approves
        submit_color_decision(self.md_user, decisions['MD'].id, 'approved', 'Looks good for luxury trim')
        selection.refresh_from_db()
        self.assertEqual(selection.status, PatternColorSelection.STATUS_PENDING)

        # ED approves
        submit_color_decision(self.ed_user, decisions['ED'].id, 'approved', 'Approved by ED')
        selection.refresh_from_db()
        self.assertEqual(selection.status, PatternColorSelection.STATUS_PENDING)

        # CAD approves -> Triggers overall approval and ColorMaster insertion
        initial_cm_count = ColorMaster.objects.count()
        submit_color_decision(self.cad_user, decisions['CAD'].id, 'approved', 'CAD confirmed pattern fitment')
        selection.refresh_from_db()
        self.assertEqual(selection.status, PatternColorSelection.STATUS_APPROVED)

        # ColorMaster should have 1 new color
        self.assertEqual(ColorMaster.objects.count(), initial_cm_count + 1)
        new_color = ColorMaster.objects.get(hex_code='#336699')
        self.assertEqual(new_color.pantone_code, '5010 U')
        self.assertEqual(new_color.name, 'OCEAN NAVY')
        self.assertEqual(new_color.status, 'Active')
        self.assertEqual(selection.inner_existing_color, new_color)

    def test_new_color_workflow_rejection(self):
        data = {
            'tone_type': 'single',
            'inner_source': 'new',
            'inner_pantone_code': '9999 U',
            'inner_hex_code': '#FF0055',
            'inner_color_name': 'Neon Magenta',
        }
        selection, _ = save_color_selection(self.vehicle, self.regular_user, data)
        decisions = {d.department: d for d in selection.decisions.all()}

        # MD approves
        submit_color_decision(self.md_user, decisions['MD'].id, 'approved', '')

        # ED rejects without remarks should fail
        with self.assertRaises(Exception):
            submit_color_decision(self.ed_user, decisions['ED'].id, 'rejected', '')

        # ED rejects with mandatory remark
        submit_color_decision(self.ed_user, decisions['ED'].id, 'rejected', 'Too bright for Haval model')
        selection.refresh_from_db()
        self.assertEqual(selection.status, PatternColorSelection.STATUS_REJECTED)

        # Unapproved new color must NOT be added to ColorMaster
        self.assertFalse(ColorMaster.objects.filter(hex_code='#FF0055').exists())

    def test_permission_enforcement_on_decisions(self):
        data = {
            'tone_type': 'single',
            'inner_source': 'new',
            'inner_pantone_code': '8888 U',
            'inner_hex_code': '#112233',
        }
        selection, _ = save_color_selection(self.vehicle, self.regular_user, data)
        decisions = {d.department: d for d in selection.decisions.all()}

        # Regular user tries to approve CAD decision -> PermissionDenied
        with self.assertRaises(Exception):
            submit_color_decision(self.regular_user, decisions['CAD'].id, 'approved', 'Hacking')

        # MD user tries to approve ED decision -> PermissionDenied
        with self.assertRaises(Exception):
            submit_color_decision(self.md_user, decisions['ED'].id, 'approved', 'Cross-dept attempt')

        # A stale approval_role on a different workflow role grants no review power.
        self.md_user.workflow_profile.role = WorkflowRoles.FACTORY_VIEWER
        self.md_user.workflow_profile.save(update_fields=['role'])
        with self.assertRaises(Exception):
            submit_color_decision(self.md_user, decisions['MD'].id, 'approved', 'Stale role')

    def test_decisions_are_single_use_and_rejection_is_terminal(self):
        selection, _ = save_color_selection(self.vehicle, self.regular_user, {
            'tone_type': 'single', 'inner_source': 'new',
            'inner_pantone_code': '2000 U', 'inner_hex_code': '#123456',
        })
        decisions = {d.department: d for d in selection.decisions.all()}
        submit_color_decision(self.md_user, decisions['MD'].id, 'approved', 'First review')
        with self.assertRaises(Exception):
            submit_color_decision(self.md_user, decisions['MD'].id, 'rejected', 'Changed mind')
        submit_color_decision(self.ed_user, decisions['ED'].id, 'rejected', 'Needs revision')
        with self.assertRaises(Exception):
            submit_color_decision(self.cad_user, decisions['CAD'].id, 'approved', 'Late vote')
        selection.refresh_from_db()
        self.assertEqual(selection.status, PatternColorSelection.STATUS_REJECTED)
        self.assertFalse(ColorMaster.objects.filter(hex_code='#123456').exists())

    def test_matching_new_inner_and_outer_colors_reuse_one_master_record(self):
        before = ColorMaster.objects.count()
        selection, _ = save_color_selection(self.vehicle, self.regular_user, {
            'tone_type': 'dual',
            'inner_source': 'new', 'inner_pantone_code': '3210 U',
            'inner_hex_code': '#123ABC', 'inner_color_name': 'Inner Blue',
            'outer_source': 'new', 'outer_pantone_code': '3210 U',
            'outer_hex_code': '#123ABC', 'outer_color_name': 'Outer Blue',
        })
        decisions = {d.department: d for d in selection.decisions.all()}
        submit_color_decision(self.md_user, decisions['MD'].id, 'approved', '')
        submit_color_decision(self.ed_user, decisions['ED'].id, 'approved', '')
        submit_color_decision(self.cad_user, decisions['CAD'].id, 'approved', '')
        selection.refresh_from_db()
        self.assertEqual(ColorMaster.objects.count(), before + 1)
        self.assertEqual(selection.inner_existing_color_id, selection.outer_existing_color_id)

    @patch('management.services.push_notifications.send_push_to_user')
    def test_rejection_push_omits_reviewer_remarks(self, push):
        selection, _ = save_color_selection(self.vehicle, self.regular_user, {
            'tone_type': 'single', 'inner_source': 'new',
            'inner_pantone_code': '8000 U', 'inner_hex_code': '#FEDCBA',
        })
        decision = selection.decisions.get(department='MD')
        push.reset_mock()
        private_remark = 'Customer phone and internal details stay in Fabro'
        with self.captureOnCommitCallbacks(execute=True):
            submit_color_decision(self.md_user, decision.id, 'rejected', private_remark)
        self.assertEqual(push.call_count, 1)
        self.assertNotIn(private_remark, push.call_args.args[2])
        self.assertIn(private_remark, Notification.objects.filter(color_selection=selection, recipient=self.regular_user).latest('id').message)

    def test_api_endpoints_integration(self):
        self.client.force_login(self.regular_user)

        # Upload measurement file via API
        pdf_file = SimpleUploadedFile("template.pdf", b"%PDF-1.4 sample content", content_type="application/pdf")
        upload_resp = self.client.post(reverse('upload_measurement_files_api'), {
            'vehicle_id': self.vehicle.id,
            'category': 'scanned_pattern',
            'files': [pdf_file],
        })
        self.assertEqual(upload_resp.status_code, 200)
        resp_data = upload_resp.json()
        self.assertEqual(resp_data['status'], 'success')
        self.assertEqual(len(resp_data['files']), 1)
        file_id = resp_data['files'][0]['id']

        # Get files via API
        list_resp = self.client.get(reverse('get_measurement_files_api') + f"?vehicle_id={self.vehicle.id}")
        self.assertEqual(list_resp.status_code, 200)
        self.assertEqual(len(list_resp.json()['scanned_files']), 1)

        # Delete file via API
        del_resp = self.client.post(reverse('delete_measurement_file_api', args=[file_id]))
        self.assertEqual(del_resp.status_code, 200)
        self.assertEqual(PatternMeasurementFile.objects.filter(id=file_id).count(), 0)

        # Save new color via API
        save_color_resp = self.client.post(reverse('save_color_selection_api'), {
            'vehicle_id': self.vehicle.id,
            'tone_type': 'single',
            'inner_source': 'new',
            'inner_pantone_code': '7540 U',
            'inner_hex_code': '#556677',
            'inner_color_name': 'Slate Grey',
        })
        self.assertEqual(save_color_resp.status_code, 200)
        color_data = save_color_resp.json()['selection']
        self.assertEqual(color_data['status'], 'pending')
        selection_id = color_data['id']

        # Check details API
        details_resp = self.client.get(reverse('get_color_selection_details_api') + f"?selection_id={selection_id}")
        self.assertEqual(details_resp.status_code, 200)
        self.assertEqual(details_resp.json()['selection']['inner_color']['pantone'], '7540 U')

        # Approver submits decision via API
        self.client.force_login(self.md_user)
        md_decision_id = color_data['decisions']['MD']['id']
        decide_resp = self.client.post(reverse('submit_color_decision_api'), {
            'decision_id': md_decision_id,
            'decision': 'approved',
            'remarks': 'Approved by MD via API',
        })
        self.assertEqual(decide_resp.status_code, 200)
        self.assertEqual(decide_resp.json()['selection']['decisions']['MD']['status'], 'approved')
