import json
from datetime import date, timedelta

from django.contrib.auth import get_user_model
from django.contrib.sessions.models import Session
from django.core.cache import cache
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import Client, TestCase, override_settings
from django.urls import reverse
from django.utils import timezone
from rest_framework.authtoken.models import Token

from .models import (
    Brand,
    ChatMessage,
    Complaint,
    ComplaintApproval,
    ComplaintEditLog,
    ComplaintMedia,
    ComplaintTypes,
    ApprovalRoles,
    ApprovalStages,
    DecisionStatuses,
    FactoryPriorities,
    MasterSetting,
    Model,
    Notification,
    SKU,
    SubModel,
    UserProfile,
    WorkflowRoles,
    WorkflowStatuses,
    YearRange,
)
from .services.workflow import (
    close_complaint_after_execution,
    complaint_journey_steps,
    create_approval_round,
    prepare_complaint_for_create,
    record_approval_decision,
    required_approval_roles,
    start_action_execution,
    submit_factory_review,
    visible_complaints_for_user,
)


class FabroBackendTests(TestCase):
    def setUp(self):
        User = get_user_model()
        self.user = User.objects.create_superuser(
            username="backend_test_admin",
            email="backend@example.com",
            password="BackendTest!234",
        )
        self.client = Client()

        self.channel = MasterSetting.objects.create(category="Channel", name="WhatsApp")
        self.country = MasterSetting.objects.create(category="Country", name="KSA")
        self.person = MasterSetting.objects.create(category="Reported By", name="Backend Reporter")
        self.case_type = MasterSetting.objects.create(category="Type", name="Stitching")
        self.series = MasterSetting.objects.create(category="Series", name="Luxe")
        self.material = MasterSetting.objects.create(category="Material", name="Rexin")
        self.region = MasterSetting.objects.create(category="Region", name="Backend Region")
        self.sku = SKU.objects.create(code="BACKEND-SKU", description="Backend test SKU", region=self.region)
        self.brand = Brand.objects.create(name="BACKEND BRAND")
        self.model = Model.objects.create(brand=self.brand, name="BACKEND MODEL")
        self.sub_model = SubModel.objects.create(model=self.model, name="BACKEND SUB")
        self.year = YearRange.objects.create(
            sub_model=self.sub_model,
            year_start=2024,
            year_end=2026,
            number_of_seats=5,
            number_of_doors=4,
            layout_code="BACKEND-LAYOUT",
        )

    def login(self):
        self.client.force_login(self.user)

    def create_workflow_user(self, username, role, approval_role=''):
        User = get_user_model()
        user = User.objects.create_user(
            username=username,
            email=f'{username}@example.com',
            password='WorkflowTest!234',
        )
        UserProfile.objects.filter(user=user).update(
            role=role,
            approval_role=approval_role,
            can_receive_factory_assignments=role == WorkflowRoles.FACTORY_EXECUTIVE,
        )
        return user

    def create_approval_accounts(self, roles, suffix):
        return {
            role: self.create_workflow_user(
                f'{suffix}_{role.lower()}',
                WorkflowRoles.APPROVER,
                role,
            )
            for role in roles
        }

    def test_required_approval_roles_follow_the_agreed_priority_matrix(self):
        self.assertEqual(
            required_approval_roles(FactoryPriorities.LOW),
            [ApprovalRoles.PM, ApprovalRoles.OM, ApprovalRoles.CAD],
        )
        self.assertEqual(
            required_approval_roles(FactoryPriorities.MEDIUM),
            [ApprovalRoles.PM, ApprovalRoles.OM, ApprovalRoles.CAD, ApprovalRoles.ED],
        )
        self.assertEqual(
            required_approval_roles(FactoryPriorities.TOP),
            [ApprovalRoles.PM, ApprovalRoles.OM, ApprovalRoles.CAD, ApprovalRoles.ED, ApprovalRoles.MD],
        )

    def test_protected_routes_redirect_anonymous_users(self):
        for route_name in ["index", "complaint_list", "add_complaint", "car_details", "add_sku", "master_settings", "profile_settings"]:
            response = self.client.get(reverse(route_name))
            self.assertEqual(response.status_code, 302, route_name)
            self.assertIn("/login/", response["Location"])

    def test_health_endpoint_and_security_headers(self):
        response = self.client.get(reverse('health_check'))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {'status': 'ok'})
        self.assertIn('Content-Security-Policy', response.headers)
        self.assertIn('Permissions-Policy', response.headers)

    @override_settings(
        LOGIN_MAX_ATTEMPTS=2,
        LOGIN_RATE_WINDOW_SECONDS=60,
        LOGIN_LOCKOUT_SECONDS=60,
    )
    def test_web_login_is_rate_limited(self):
        cache.clear()
        payload = {'username': self.user.username, 'password': 'wrong-password'}
        self.assertEqual(self.client.post(reverse('login'), payload).status_code, 200)
        self.assertEqual(self.client.post(reverse('login'), payload).status_code, 200)
        self.assertEqual(self.client.post(reverse('login'), payload).status_code, 429)
        cache.clear()

    def test_dashboard_and_main_pages_render_for_authenticated_user(self):
        self.login()
        for route_name in ["index", "complaint_list", "add_complaint", "car_details", "add_sku", "master_settings", "profile_settings"]:
            response = self.client.get(reverse(route_name))
            self.assertEqual(response.status_code, 200, route_name)

    def test_add_complaint_recognition_defaults_and_preserves_submitted_type(self):
        self.login()

        default_response = self.client.get(reverse('add_complaint'))
        self.assertContains(default_response, 'id="complaint-type-indicator"')
        self.assertContains(default_response, 'Pattern Complaint')
        self.assertContains(default_response, 'Save Pattern Complaint')

        invalid_production_response = self.client.post(reverse('add_complaint'), {
            'complaint_type': ComplaintTypes.PRODUCTION,
        })
        self.assertEqual(invalid_production_response.status_code, 200)
        self.assertEqual(
            invalid_production_response.context['selected_complaint_type'],
            ComplaintTypes.PRODUCTION,
        )
        self.assertContains(invalid_production_response, 'type-production')
        self.assertContains(invalid_production_response, 'Save Production Complaint')

    def test_complaint_create_edit_delete_and_media_fallback(self):
        self.login()
        upload = SimpleUploadedFile("backend-test.png", b"fake-png", content_type="image/png")
        response = self.client.post(reverse("add_complaint"), {
            "status": "Open",
            "priority": "Medium",
            "channel": self.channel.id,
            "country": self.country.id,
            "person": self.person.id,
            "case_sub_category": self.case_type.id,
            "series": self.series.id,
            "material": self.material.id,
            "sku": self.sku.id,
            "brand": self.brand.id,
            "model": self.model.id,
            "sub_model": self.sub_model.id,
            "year": self.year.id,
            "complaint_description": "Backend complaint",
            "batch_order": "BATCH-1",
            "media_files": upload,
        })
        self.assertEqual(response.status_code, 302)
        complaint = Complaint.objects.get(complaint_description="Backend complaint")
        self.assertEqual(complaint.media_files.count(), 1)
        media = complaint.media_files.first()
        self.assertTrue(media.file.startswith("complaint_media/"))
        self.assertTrue(media.url.startswith("/media/"))
        self.assertTrue(media.is_available)

        response = self.client.post(reverse("edit_complaint", args=[complaint.complaint_id]), {
            "status": "Closed",
            "priority": "High",
            "complaint_description": "Backend complaint updated",
            "batch_order": "BATCH-2",
        })
        self.assertEqual(response.status_code, 302)
        complaint.refresh_from_db()
        self.assertEqual(complaint.status, "Open")
        self.assertEqual(complaint.priority, "High")

        response = self.client.post(reverse("delete_complaint", args=[complaint.complaint_id]))
        self.assertEqual(response.status_code, 302)
        self.assertFalse(Complaint.objects.filter(complaint_id=complaint.complaint_id).exists())

    def test_vehicle_sku_and_master_crud_routes(self):
        self.login()
        response = self.client.post(reverse("car_details"), {
            "layout_code": "BACKEND-NEW-CAR",
            "brand_name": "BACKEND NEW BRAND",
            "model_name": "BACKEND NEW MODEL",
            "sub_model_name": "BACKEND NEW SUB",
            "year_start": 2020,
            "year_end": 2022,
            "number_of_seats": 5,
            "number_of_doors": 4,
        })
        self.assertEqual(response.status_code, 302)
        new_year = YearRange.objects.get(layout_code="BACKEND-NEW-CAR")

        response = self.client.post(reverse("add_sku"), {
            "add_sku": "1",
            "code": "BACKEND-NEW-SKU",
            "description": "New SKU",
            "region": self.region.id,
        })
        self.assertEqual(response.status_code, 302)
        self.assertTrue(SKU.objects.filter(code="BACKEND-NEW-SKU").exists())

        response = self.client.post(reverse("master_settings"), {
            "category": "Channel",
            "name": "Backend Channel",
        })
        self.assertEqual(response.status_code, 302)
        setting = MasterSetting.objects.get(name="Backend Channel")

        response = self.client.post(reverse("delete_master_setting", args=[setting.id]))
        self.assertEqual(response.status_code, 302)
        self.assertFalse(MasterSetting.objects.filter(id=setting.id).exists())

        response = self.client.post(reverse("delete_car_detail", args=[new_year.id]))
        self.assertEqual(response.status_code, 302)
        self.assertFalse(YearRange.objects.filter(id=new_year.id).exists())

    def test_catalog_search_filtering(self):
        user = self.create_workflow_user("audit_country", "country_executive")
        self.client.force_login(user)
        # Create test vehicles and SKUs
        brand1 = Brand.objects.create(name="Toyota")
        model1 = Model.objects.create(brand=brand1, name="Camry")
        sub_model1 = SubModel.objects.create(model=model1, name="Hybrid")
        yr1 = YearRange.objects.create(
            sub_model=sub_model1,
            year_start=2021,
            year_end=2023,
            number_of_seats=5,
            number_of_doors=4,
            layout_code="CAMRY-HYBRID"
        )

        brand2 = Brand.objects.create(name="Ford")
        model2 = Model.objects.create(brand=brand2, name="Mustang")
        sub_model2 = SubModel.objects.create(model=model2, name="GT")
        yr2 = YearRange.objects.create(
            sub_model=sub_model2,
            year_start=2022,
            year_end=2024,
            number_of_seats=4,
            number_of_doors=2,
            layout_code="MUSTANG-GT"
        )

        sku1 = SKU.objects.create(code="TOY-123", description="Toyota part", region=self.region)
        sku2 = SKU.objects.create(code="FRD-456", description="Ford part", region=self.region)

        # Test SKU search by code
        response = self.client.get(reverse("add_sku"), {"search": "TOY", "column": "code"})
        self.assertContains(response, "TOY-123")
        self.assertNotContains(response, "FRD-456")

        # Test SKU search by description
        response = self.client.get(reverse("add_sku"), {"search": "Ford", "column": "description"})
        self.assertContains(response, "FRD-456")
        self.assertNotContains(response, "TOY-123")

        # Test SKU search all columns
        response = self.client.get(reverse("add_sku"), {"search": "part", "column": "all"})
        self.assertContains(response, "TOY-123")
        self.assertContains(response, "FRD-456")

        # Test Vehicle search by layout_code
        response = self.client.get(reverse("car_details"), {"search": "MUSTANG", "column": "layout_code"})
        self.assertContains(response, "MUSTANG-GT")
        self.assertNotContains(response, "CAMRY-HYBRID")

        # Test Vehicle search by brand
        response = self.client.get(reverse("car_details"), {"search": "Toyota", "column": "brand"})
        self.assertContains(response, "CAMRY-HYBRID")
        self.assertNotContains(response, "MUSTANG-GT")

    def test_vehicle_csv_validation_does_not_raise_server_errors(self):
        self.login()
        missing_headers = SimpleUploadedFile(
            'missing-columns.csv',
            b'brand,model\nFABRO,TEST\n',
            content_type='text/csv',
        )
        response = self.client.post(reverse('upload_car_csv'), {'csv_file': missing_headers})
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Missing required CSV columns')

        malformed_row = SimpleUploadedFile(
            'malformed-row.csv',
            (
                b'brand,model,sub_model,year_start,year_end,number_of_seats,'
                b'number_of_doors,layout_code\n'
                b'MALFORMED BRAND,MODEL,SUB,not-a-year,2026,5,4,MALFORMED-LAYOUT\n'
            ),
            content_type='text/csv',
        )
        response = self.client.post(reverse('upload_car_csv'), {'csv_file': malformed_row})
        self.assertEqual(response.status_code, 302)
        self.assertFalse(YearRange.objects.filter(layout_code='MALFORMED-LAYOUT').exists())

    def test_dropdown_json_endpoints(self):
        self.login()
        response = self.client.get(reverse("get_models", args=[self.brand.id]))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()[0]["name"], "BACKEND MODEL")

        response = self.client.get(reverse("get_sub_models", args=[self.model.id]))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()[0]["name"], "BACKEND SUB")

        response = self.client.get(reverse("get_year_ranges", args=[self.sub_model.id]))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()[0]["range"], "24-26")

    def test_export_complaints_csv(self):
        self.login()
        Complaint.objects.create(
            date="2026-07-02",
            status="Open",
            priority="Medium",
            complaint_description="CSV complaint",
            batch_order="CSV-BATCH",
        )
        response = self.client.get(reverse("export_complaints"))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Content-Type"], "text/csv")
        self.assertIn(b"CSV complaint", response.content)

    def test_api_register_is_disabled_by_default(self):
        response = self.client.post(
            reverse("api_register"),
            data=json.dumps({
                "username": "blocked_mobile_user",
                "email": "blocked@example.com",
                "password": "MobileUser!234",
            }),
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 403)
        self.assertFalse(get_user_model().objects.filter(username="blocked_mobile_user").exists())

    @override_settings(ALLOW_PUBLIC_REGISTRATION=True)
    def test_api_register_never_grants_staff_or_superuser(self):
        User = get_user_model()
        response = self.client.post(
            reverse("api_register"),
            data=json.dumps({
                "username": "mobile_regular_user",
                "email": "mobile@example.com",
                "password": "MobileUser!234",
                "is_staff": True,
                "is_superuser": True,
            }),
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 201)
        created_user = User.objects.get(username="mobile_regular_user")
        self.assertFalse(created_user.is_staff)
        self.assertFalse(created_user.is_superuser)

    def test_destructive_catalog_routes_reject_get(self):
        self.login()
        for route_name, object_id in [
            ("delete_car_detail", self.year.id),
            ("delete_sku", self.sku.id),
            ("delete_master_setting", self.channel.id),
        ]:
            response = self.client.get(reverse(route_name, args=[object_id]))
            self.assertEqual(response.status_code, 405, route_name)

    def test_non_admin_cannot_delete_complaints_or_write_catalog_api(self):
        User = get_user_model()
        viewer = User.objects.create_user(
            username="read_only_factory_user",
            password="ReadOnly!234",
        )
        complaint = Complaint.objects.create(
            date="2026-07-10",
            status="Open",
            priority="Medium",
            complaint_description="Protected complaint",
            batch_order="PROTECTED",
        )
        self.client.force_login(viewer)
        response = self.client.post(reverse("delete_complaint", args=[complaint.complaint_id]))
        self.assertEqual(response.status_code, 403)
        self.assertTrue(Complaint.objects.filter(pk=complaint.pk).exists())

        token, _ = Token.objects.get_or_create(user=viewer)
        response = self.client.post(
            reverse("api_skus_list_create"),
            data=json.dumps({"code": "FORBIDDEN-SKU"}),
            content_type="application/json",
            HTTP_AUTHORIZATION=f"Token {token.key}",
        )
        self.assertEqual(response.status_code, 403)

    def test_factory_viewer_cannot_edit_the_original_report_step(self):
        User = get_user_model()
        viewer = User.objects.create_user(
            username="factory_report_viewer",
            password="ReadOnly!234",
        )
        complaint = Complaint.objects.create(
            date="2026-07-10",
            country=self.country,
            complaint_type=ComplaintTypes.PATTERN,
            status="Open",
            priority="Medium",
            complaint_description="Read-only reporter step",
            batch_order="READ-ONLY",
        )

        self.client.force_login(viewer)
        response = self.client.get(reverse("edit_complaint", args=[complaint.complaint_id]))

        self.assertEqual(response.status_code, 302)
        self.assertEqual(response["Location"], reverse("complaint_list"))

    def test_missing_legacy_media_is_not_exposed_as_available(self):
        complaint = Complaint.objects.create(
            date="2026-07-10",
            status="Open",
            priority="Medium",
            complaint_description="Legacy media",
            batch_order="LEGACY-MEDIA",
        )
        media = ComplaintMedia.objects.create(
            complaint=complaint,
            file="complaint_media/missing/legacy-image.jpg",
        )

        self.assertFalse(media.is_available)
        self.assertEqual(media.url, "/media/complaint_media/missing/legacy-image.jpg")

    def test_invalid_complaint_search_field_does_not_raise_server_error(self):
        self.login()
        response = self.client.get(reverse("complaint_list"), {
            "search": "test",
            "search_by": "created_by__password",
        })
        self.assertEqual(response.status_code, 200)

    def test_complaint_search_does_not_submit_none_for_blank_filters(self):
        self.login()

        response = self.client.get(reverse('complaint_list'))

        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, 'value="None"', html=False)

    def test_api_profile_can_be_viewed_and_updated_with_token(self):
        token, _ = Token.objects.get_or_create(user=self.user)
        response = self.client.patch(
            reverse("api_profile"),
            data=json.dumps({
                "first_name": "Fabro",
                "last_name": "Tester",
                "email": "updated-backend@example.com",
            }),
            content_type="application/json",
            HTTP_AUTHORIZATION=f"Token {token.key}",
        )

        self.assertEqual(response.status_code, 200)
        self.user.refresh_from_db()
        self.assertEqual(self.user.first_name, "Fabro")
        self.assertEqual(self.user.last_name, "Tester")
        self.assertEqual(self.user.email, "updated-backend@example.com")
        self.assertTrue(response.json()["is_staff"])

    def test_api_dashboard_requires_auth_and_returns_stats(self):
        anonymous_response = self.client.get(reverse("api_dashboard"))
        self.assertIn(anonymous_response.status_code, [401, 403])

        Complaint.objects.create(date="2026-07-08", status="Open", priority="Medium", complaint_description="Open API complaint")
        Complaint.objects.create(date="2026-07-08", status="Closed", priority="Medium", complaint_description="Closed API complaint")
        Complaint.objects.create(date="2026-07-08", status="On Hold", priority="High", complaint_description="Hold API complaint")

        token, _ = Token.objects.get_or_create(user=self.user)
        response = self.client.get(
            reverse("api_dashboard"),
            HTTP_AUTHORIZATION=f"Token {token.key}",
        )

        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["total_complaints"], 3)
        self.assertEqual(data["open_complaints"], 1)
        self.assertEqual(data["closed_complaints"], 1)
        self.assertEqual(data["on_hold_complaints"], 1)
        self.assertEqual(data["total_vehicles"], 1)
        self.assertEqual(data["total_skus"], 1)
        self.assertEqual(data["total_settings"], 7)
        self.assertEqual(data["total_master_settings"], 7)

    def test_country_executive_sees_only_own_country_pattern_and_production_complaints(self):
        User = get_user_model()
        country_user = User.objects.create_user(
            username="ksa_country_exec",
            email="ksa.exec@example.com",
            password="CountryExec!234",
        )
        UserProfile.objects.filter(user=country_user).update(
            role=WorkflowRoles.COUNTRY_EXECUTIVE,
            country=self.country,
        )
        other_country = MasterSetting.objects.create(category="Country", name="UAE")

        own_pattern = Complaint.objects.create(
            date="2026-07-09",
            country=self.country,
            complaint_type=ComplaintTypes.PATTERN,
            status="Open",
            priority="Medium",
            complaint_description="Own country pattern complaint",
            batch_order="OWN-PATTERN",
        )
        own_production = Complaint.objects.create(
            date="2026-07-09",
            country=self.country,
            complaint_type=ComplaintTypes.PRODUCTION,
            status="Open",
            priority="Medium",
            complaint_description="Own country production complaint",
            batch_order="OWN-PRODUCTION",
        )
        Complaint.objects.create(
            date="2026-07-09",
            country=self.country,
            complaint_type=ComplaintTypes.LINE,
            status="Open",
            priority="Medium",
            complaint_description="Hidden line complaint",
            batch_order="HIDDEN-LINE",
        )
        Complaint.objects.create(
            date="2026-07-09",
            country=other_country,
            complaint_type=ComplaintTypes.PATTERN,
            status="Open",
            priority="Medium",
            complaint_description="Hidden other country complaint",
            batch_order="HIDDEN-COUNTRY",
        )

        visible_ids = set(
            visible_complaints_for_user(country_user).values_list("complaint_id", flat=True)
        )

        self.assertEqual(visible_ids, {own_pattern.complaint_id, own_production.complaint_id})

    def test_country_executive_api_forces_own_country_and_rejects_line_complaints(self):
        User = get_user_model()
        country_user = User.objects.create_user(
            username='api_country_exec',
            email='api.country@example.com',
            password='CountryExec!234',
        )
        UserProfile.objects.filter(user=country_user).update(
            role=WorkflowRoles.COUNTRY_EXECUTIVE,
            country=self.country,
        )
        other_country = MasterSetting.objects.create(category='Country', name='API UAE')
        token = Token.objects.create(user=country_user)
        headers = {'HTTP_AUTHORIZATION': f'Token {token.key}'}
        payload = {
            'date': '2026-07-09',
            'country': other_country.id,
            'case_sub_category': self.case_type.id,
            'priority': 'Medium',
            'complaint_description': 'Country must be forced by the API',
            'batch_order': 'API-COUNTRY-FORCE',
        }

        response = self.client.post(
            reverse('api_complaints_list_create'),
            data=json.dumps(payload),
            content_type='application/json',
            **headers,
        )
        self.assertEqual(response.status_code, 201)
        complaint = Complaint.objects.get(complaint_description=payload['complaint_description'])
        self.assertEqual(complaint.country, self.country)
        self.assertEqual(complaint.created_by, country_user)

        line_type = MasterSetting.objects.create(category='Type', name='Line Complaint')
        payload.update({
            'case_sub_category': line_type.id,
            'complaint_description': 'Country line attempt',
            'batch_order': 'API-LINE-BLOCKED',
        })
        response = self.client.post(
            reverse('api_complaints_list_create'),
            data=json.dumps(payload),
            content_type='application/json',
            **headers,
        )
        self.assertEqual(response.status_code, 403)
        self.assertFalse(Complaint.objects.filter(batch_order='API-LINE-BLOCKED').exists())

    def test_country_executive_complaint_list_hides_line_and_other_country_records(self):
        User = get_user_model()
        country_user = User.objects.create_user(
            username="portal_country_exec",
            email="portal.exec@example.com",
            password="CountryExec!234",
        )
        UserProfile.objects.filter(user=country_user).update(
            role=WorkflowRoles.COUNTRY_EXECUTIVE,
            country=self.country,
        )
        other_country = MasterSetting.objects.create(category="Country", name="QATAR")

        Complaint.objects.create(
            date="2026-07-09",
            country=self.country,
            complaint_type=ComplaintTypes.PRODUCTION,
            status="Open",
            priority="Medium",
            complaint_description="Visible production complaint",
            batch_order="VISIBLE-PRODUCTION",
        )
        Complaint.objects.create(
            date="2026-07-09",
            country=self.country,
            complaint_type=ComplaintTypes.LINE,
            status="Open",
            priority="Medium",
            complaint_description="Invisible line complaint",
            batch_order="INVISIBLE-LINE",
        )
        Complaint.objects.create(
            date="2026-07-09",
            country=other_country,
            complaint_type=ComplaintTypes.PATTERN,
            status="Open",
            priority="Medium",
            complaint_description="Invisible country complaint",
            batch_order="INVISIBLE-COUNTRY",
        )

        self.client.force_login(country_user)
        response = self.client.get(reverse("complaint_list"))

        self.assertContains(response, "Visible production complaint")
        self.assertNotContains(response, "Invisible line complaint")
        self.assertNotContains(response, "Invisible country complaint")

    def test_dashboard_replaces_master_stat_with_scoped_monthly_summary_for_non_admins(self):
        country_user = self.create_workflow_user(
            'monthly_country_exec',
            WorkflowRoles.COUNTRY_EXECUTIVE,
        )
        UserProfile.objects.filter(user=country_user).update(country=self.country)
        other_country = MasterSetting.objects.create(category='Country', name='MONTHLY-UAE')
        today = timezone.localdate()

        Complaint.objects.create(
            date=today,
            country=self.country,
            complaint_type=ComplaintTypes.PATTERN,
            status='Open',
            priority='Medium',
            complaint_description='Visible monthly complaint',
            batch_order='MONTHLY-OPEN',
        )
        Complaint.objects.create(
            date=today,
            country=self.country,
            complaint_type=ComplaintTypes.PRODUCTION,
            workflow_status=WorkflowStatuses.CLOSED,
            status='Closed',
            priority='Low',
            complaint_description='Visible resolved complaint',
            batch_order='MONTHLY-CLOSED',
            closed_at=timezone.now(),
        )
        Complaint.objects.create(
            date=today,
            country=other_country,
            complaint_type=ComplaintTypes.PATTERN,
            status='Open',
            priority='Medium',
            complaint_description='Other country monthly complaint',
            batch_order='MONTHLY-HIDDEN',
        )

        self.client.force_login(country_user)
        response = self.client.get(reverse('index'))

        self.assertEqual(response.context['complaints_this_month'], 2)
        self.assertEqual(response.context['resolved_this_month'], 1)
        self.assertContains(response, '<div class="stat-card-compact monthly-stats-card">', html=False)
        self.assertContains(response, 'This Month')

        self.client.force_login(self.user)
        admin_response = self.client.get(reverse('index'))
        self.assertContains(admin_response, reverse('master_settings'))
        self.assertNotContains(
            admin_response,
            '<div class="stat-card-compact monthly-stats-card">',
            html=False,
        )

    def test_dashboard_complaint_type_summary_links_apply_real_filters(self):
        viewer = self.create_workflow_user('type_summary_viewer', WorkflowRoles.FACTORY_VIEWER)
        for complaint_type, batch_order in [
            (ComplaintTypes.LINE, 'TYPE-LINE'),
            (ComplaintTypes.PATTERN, 'TYPE-PATTERN'),
            (ComplaintTypes.PRODUCTION, 'TYPE-PRODUCTION'),
        ]:
            Complaint.objects.create(
                date='2026-07-16',
                country=self.country,
                complaint_type=complaint_type,
                status='Open',
                priority='Medium',
                complaint_description=f'{complaint_type} summary complaint',
                batch_order=batch_order,
            )

        self.client.force_login(viewer)
        dashboard = self.client.get(reverse('index'))

        self.assertEqual(dashboard.context['line_complaints'], 1)
        self.assertEqual(dashboard.context['pattern_complaints'], 1)
        self.assertEqual(dashboard.context['production_complaints'], 1)
        self.assertContains(dashboard, f'{reverse("complaint_list")}?complaint_type=line')
        self.assertContains(dashboard, f'{reverse("complaint_list")}?complaint_type=pattern')
        self.assertContains(dashboard, f'{reverse("complaint_list")}?complaint_type=production')

        line_response = self.client.get(reverse('complaint_list'), {'complaint_type': ComplaintTypes.LINE})
        self.assertEqual(line_response.context['selected_complaint_type'], ComplaintTypes.LINE)
        self.assertEqual(len(line_response.context['complaints']), 1)
        self.assertEqual(line_response.context['complaints'][0].complaint_type, ComplaintTypes.LINE)

    def test_visible_complaints_preserves_an_empty_supplied_queryset(self):
        empty_ordered_queryset = Complaint.objects.filter(
            batch_order='DOES-NOT-EXIST',
        ).order_by('-complaint_id')

        visible = visible_complaints_for_user(self.user, empty_ordered_queryset)

        self.assertTrue(visible.ordered)
        self.assertFalse(visible.exists())

    def test_factory_review_requires_mandatory_fields(self):
        User = get_user_model()
        factory_user = User.objects.create_user(
            username="factory_exec_required",
            email="factory.required@example.com",
            password="FactoryExec!234",
        )
        UserProfile.objects.filter(user=factory_user).update(
            role=WorkflowRoles.FACTORY_EXECUTIVE,
            can_receive_factory_assignments=True,
        )
        complaint = Complaint.objects.create(
            date="2026-07-09",
            country=self.country,
            complaint_type=ComplaintTypes.PATTERN,
            workflow_status=WorkflowStatuses.ASSIGNED_TO_FACTORY,
            assigned_factory_executive=factory_user,
            status="Open",
            priority="Medium",
            complaint_description="Needs factory review validation",
            batch_order="FACTORY-VALIDATION",
        )

        self.client.force_login(factory_user)
        response = self.client.post(reverse("factory_review_complaint", args=[complaint.complaint_id]), {
            "factory_reason": "",
            "factory_action_plan": "",
            "factory_priority": "",
        })

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "This field is required")
        self.assertFalse(ComplaintApproval.objects.filter(complaint=complaint).exists())

    def test_factory_review_submission_creates_parallel_approval_round(self):
        User = get_user_model()
        factory_user = User.objects.create_user(
            username="factory_exec_submit",
            email="factory.submit@example.com",
            password="FactoryExec!234",
        )
        UserProfile.objects.filter(user=factory_user).update(
            role=WorkflowRoles.FACTORY_EXECUTIVE,
            can_receive_factory_assignments=True,
        )

        for role in [ApprovalRoles.PM, ApprovalRoles.OM, ApprovalRoles.CAD, ApprovalRoles.ED]:
            approver = User.objects.create_user(
                username=f"approver_{role.lower()}",
                email=f"{role.lower()}@example.com",
                password="Approver!234",
            )
            UserProfile.objects.filter(user=approver).update(
                role=WorkflowRoles.APPROVER,
                approval_role=role,
            )

        complaint = Complaint.objects.create(
            date="2026-07-09",
            country=self.country,
            complaint_type=ComplaintTypes.PRODUCTION,
            workflow_status=WorkflowStatuses.ASSIGNED_TO_FACTORY,
            assigned_factory_executive=factory_user,
            status="Open",
            priority="Medium",
            complaint_description="Needs factory review submit",
            batch_order="FACTORY-SUBMIT",
        )

        self.client.force_login(factory_user)
        response = self.client.post(reverse("factory_review_complaint", args=[complaint.complaint_id]), {
            "factory_reason": "Seat pattern measurement mismatch found in side panel.",
            "factory_action_plan": "Revise pattern allowance and send corrected CAD for approval.",
            "factory_priority": FactoryPriorities.MEDIUM,
        })

        self.assertEqual(response.status_code, 302)
        complaint.refresh_from_db()
        self.assertEqual(complaint.workflow_status, WorkflowStatuses.AWAITING_APPROVAL)
        self.assertEqual(complaint.factory_priority, FactoryPriorities.MEDIUM)
        self.assertEqual(complaint.justification_from_factory, complaint.factory_reason)
        self.assertEqual(complaint.action_from_factory, complaint.factory_action_plan)
        self.assertIsNotNone(complaint.factory_review_started_at)
        self.assertIsNotNone(complaint.last_submitted_for_approval_at)

        approvals = ComplaintApproval.objects.filter(complaint=complaint)
        self.assertEqual(approvals.count(), 4)
        self.assertEqual(
            set(approvals.values_list("approver_role", flat=True)),
            {ApprovalRoles.PM, ApprovalRoles.OM, ApprovalRoles.CAD, ApprovalRoles.ED},
        )
        self.assertEqual(approvals.filter(status=DecisionStatuses.PENDING).count(), 4)
        self.assertEqual(Notification.objects.filter(complaint=complaint, notification_type="approval").count(), 4)

    def test_opening_factory_review_is_read_only(self):
        User = get_user_model()
        country_user = User.objects.create_user(
            username="country_locked_edit",
            email="country.locked@example.com",
            password="CountryExec!234",
        )
        UserProfile.objects.filter(user=country_user).update(
            role=WorkflowRoles.COUNTRY_EXECUTIVE,
            country=self.country,
        )
        factory_user = User.objects.create_user(
            username="factory_lock_edit",
            email="factory.lock@example.com",
            password="FactoryExec!234",
        )
        UserProfile.objects.filter(user=factory_user).update(
            role=WorkflowRoles.FACTORY_EXECUTIVE,
            can_receive_factory_assignments=True,
        )
        complaint = Complaint.objects.create(
            date="2026-07-09",
            country=self.country,
            complaint_type=ComplaintTypes.PATTERN,
            workflow_status=WorkflowStatuses.ASSIGNED_TO_FACTORY,
            created_by=country_user,
            assigned_factory_executive=factory_user,
            status="Open",
            priority="Medium",
            complaint_description="Country edit should lock after review starts",
            batch_order="COUNTRY-LOCK",
        )

        self.client.force_login(factory_user)
        response = self.client.get(reverse("factory_review_complaint", args=[complaint.complaint_id]))
        self.assertEqual(response.status_code, 200)
        complaint.refresh_from_db()
        self.assertIsNone(complaint.factory_review_started_at)
        self.assertEqual(complaint.workflow_status, WorkflowStatuses.ASSIGNED_TO_FACTORY)

        self.client.force_login(country_user)
        response = self.client.get(reverse("edit_complaint", args=[complaint.complaint_id]))
        self.assertEqual(response.status_code, 200)

    def test_country_report_edit_is_audited_and_notifies_factory_executive(self):
        country_user = self.create_workflow_user('report_editor', WorkflowRoles.COUNTRY_EXECUTIVE)
        UserProfile.objects.filter(user=country_user).update(country=self.country)
        factory_user = self.create_workflow_user('report_edit_factory', WorkflowRoles.FACTORY_EXECUTIVE)
        complaint = Complaint.objects.create(
            date='2026-07-14',
            country=self.country,
            complaint_type=ComplaintTypes.PATTERN,
            workflow_status=WorkflowStatuses.ASSIGNED_TO_FACTORY,
            created_by=country_user,
            assigned_factory_executive=factory_user,
            channel=self.channel,
            person=self.person,
            case_sub_category=self.case_type,
            status='Open',
            priority='Medium',
            complaint_description='Original country report',
            batch_order='REPORT-EDIT-1',
        )

        self.client.force_login(country_user)
        response = self.client.post(reverse('edit_complaint', args=[complaint.complaint_id]), {
            'channel': self.channel.id,
            'person': self.person.id,
            'priority': 'High',
            'complaint_description': 'Updated after checking the fitment photos',
            'batch_order': 'REPORT-EDIT-2',
        })

        self.assertEqual(response.status_code, 302)
        complaint.refresh_from_db()
        self.assertEqual(complaint.priority, 'High')
        self.assertEqual(complaint.batch_order, 'REPORT-EDIT-2')
        self.assertTrue(ComplaintEditLog.objects.filter(
            complaint=complaint,
            edited_by=country_user,
            field_name='complaint_description',
        ).exists())
        self.assertTrue(complaint.timeline_events.filter(action_type='report_updated').exists())
        self.assertTrue(Notification.objects.filter(
            recipient=factory_user,
            complaint=complaint,
            notification_type='report_updated',
        ).exists())

    def test_report_edit_is_locked_during_approval_and_after_closure(self):
        country_user = self.create_workflow_user('locked_reporter', WorkflowRoles.COUNTRY_EXECUTIVE)
        UserProfile.objects.filter(user=country_user).update(country=self.country)
        complaint = Complaint.objects.create(
            date='2026-07-14',
            country=self.country,
            complaint_type=ComplaintTypes.PRODUCTION,
            workflow_status=WorkflowStatuses.AWAITING_APPROVAL,
            created_by=country_user,
            status='Open',
            priority='Medium',
            complaint_description='Approval snapshot must remain immutable',
            batch_order='LOCKED-REPORT',
        )

        self.client.force_login(country_user)
        response = self.client.get(reverse('edit_complaint', args=[complaint.complaint_id]))
        self.assertEqual(response.status_code, 302)

        self.client.force_login(self.user)
        response = self.client.get(reverse('edit_complaint', args=[complaint.complaint_id]))
        self.assertEqual(response.status_code, 302)

        complaint.workflow_status = WorkflowStatuses.CLOSED
        complaint.status = 'Closed'
        complaint.save(update_fields=['workflow_status', 'status'])
        response = self.client.get(reverse('edit_complaint', args=[complaint.complaint_id]))
        self.assertEqual(response.status_code, 302)

    def test_api_report_edit_uses_the_same_audit_and_workflow_lock(self):
        country_user = self.create_workflow_user('api_report_editor', WorkflowRoles.COUNTRY_EXECUTIVE)
        UserProfile.objects.filter(user=country_user).update(country=self.country)
        factory_user = self.create_workflow_user('api_report_factory', WorkflowRoles.FACTORY_EXECUTIVE)
        complaint = Complaint.objects.create(
            date=timezone.localdate(),
            country=self.country,
            complaint_type=ComplaintTypes.PRODUCTION,
            workflow_status=WorkflowStatuses.ASSIGNED_TO_FACTORY,
            created_by=country_user,
            assigned_factory_executive=factory_user,
            status='Open',
            priority='Medium',
            complaint_description='Original API report',
            batch_order='API-REPORT-EDIT',
        )
        token = Token.objects.create(user=country_user)
        headers = {'HTTP_AUTHORIZATION': f'Token {token.key}'}

        response = self.client.patch(
            reverse('api_complaint_detail', args=[complaint.complaint_id]),
            data=json.dumps({'complaint_description': 'Audited API report update'}),
            content_type='application/json',
            **headers,
        )
        self.assertEqual(response.status_code, 200)
        self.assertTrue(ComplaintEditLog.objects.filter(
            complaint=complaint,
            edited_by=country_user,
            field_name='complaint_description',
        ).exists())
        self.assertTrue(Notification.objects.filter(
            recipient=factory_user,
            complaint=complaint,
            notification_type='report_updated',
        ).exists())

        complaint.workflow_status = WorkflowStatuses.AWAITING_APPROVAL
        complaint.save(update_fields=['workflow_status'])
        response = self.client.patch(
            reverse('api_complaint_detail', args=[complaint.complaint_id]),
            data=json.dumps({'complaint_description': 'Forbidden approval-stage edit'}),
            content_type='application/json',
            **headers,
        )
        self.assertEqual(response.status_code, 403)
        complaint.refresh_from_db()
        self.assertEqual(complaint.complaint_description, 'Audited API report update')

    def test_rejection_opens_reconsideration_for_every_other_approver(self):
        factory_user = self.create_workflow_user('wait_factory', WorkflowRoles.FACTORY_EXECUTIVE)
        approvers = self.create_approval_accounts(
            [ApprovalRoles.PM, ApprovalRoles.OM, ApprovalRoles.CAD],
            'wait',
        )
        complaint = Complaint.objects.create(
            date='2026-07-14',
            country=self.country,
            complaint_type=ComplaintTypes.PATTERN,
            workflow_status=WorkflowStatuses.FACTORY_REVIEW,
            assigned_factory_executive=factory_user,
            factory_reason='Pattern allowance is incorrect.',
            factory_action_plan='Correct the CAD and verify the revised sample.',
            factory_priority=FactoryPriorities.LOW,
            status='Open',
            priority='Low',
            complaint_description='Wait for every opinion',
            batch_order='WAIT-ALL',
        )
        approvals = create_approval_round(complaint, factory_user)
        approvals_by_role = {approval.approver_role: approval for approval in approvals}

        _, outcome = record_approval_decision(
            approvals_by_role[ApprovalRoles.PM].pk,
            approvers[ApprovalRoles.PM],
            DecisionStatuses.REJECTED,
            'Increase the side-panel allowance before release.',
        )
        complaint.refresh_from_db()
        self.assertEqual(outcome, 'reconsideration')
        self.assertEqual(complaint.workflow_status, WorkflowStatuses.AWAITING_APPROVAL)
        reconsideration = ComplaintApproval.objects.filter(
            complaint=complaint,
            approval_round=2,
            review_stage=ApprovalStages.RECONSIDERATION,
        )
        self.assertEqual(
            set(reconsideration.values_list('approver_role', flat=True)),
            {ApprovalRoles.OM, ApprovalRoles.CAD},
        )
        self.assertTrue(reconsideration.filter(
            trigger_approval=approvals_by_role[ApprovalRoles.PM],
        ).exists())
        self.assertEqual(Notification.objects.filter(
            complaint=complaint,
            notification_type='approval_reconsideration',
        ).count(), 2)

        reconsideration_by_role = {
            approval.approver_role: approval for approval in reconsideration
        }
        _, outcome = record_approval_decision(
            reconsideration_by_role[ApprovalRoles.OM].pk,
            approvers[ApprovalRoles.OM],
            DecisionStatuses.APPROVED,
            'Operations chooses to proceed.',
        )
        complaint.refresh_from_db()
        self.assertEqual(outcome, 'pending')
        self.assertEqual(complaint.workflow_status, WorkflowStatuses.PARTIALLY_APPROVED)
        self.assertFalse(Notification.objects.filter(complaint=complaint, notification_type='rework').exists())

        _, outcome = record_approval_decision(
            reconsideration_by_role[ApprovalRoles.CAD].pk,
            approvers[ApprovalRoles.CAD],
            DecisionStatuses.APPROVED,
            'CAD also chooses to proceed.',
        )
        complaint.refresh_from_db()
        self.assertEqual(outcome, 'approved')
        self.assertEqual(complaint.workflow_status, WorkflowStatuses.APPROVED)
        self.assertEqual(ComplaintApproval.objects.filter(complaint=complaint).count(), 5)
        self.assertTrue(Notification.objects.filter(
            recipient=factory_user,
            complaint=complaint,
            notification_type='fully_approved',
        ).exists())

    def test_reconsideration_waits_for_all_then_returns_for_rework(self):
        factory_user = self.create_workflow_user('return_factory', WorkflowRoles.FACTORY_EXECUTIVE)
        approvers = self.create_approval_accounts(
            [ApprovalRoles.PM, ApprovalRoles.OM, ApprovalRoles.CAD],
            'return',
        )
        complaint = Complaint.objects.create(
            date='2026-07-14',
            country=self.country,
            complaint_type=ComplaintTypes.PATTERN,
            workflow_status=WorkflowStatuses.FACTORY_REVIEW,
            assigned_factory_executive=factory_user,
            factory_reason='Pattern allowance is incorrect.',
            factory_action_plan='Correct the CAD and verify the revised sample.',
            factory_priority=FactoryPriorities.LOW,
            status='Open',
            priority='Low',
            complaint_description='Reconsideration return test',
            batch_order='RETURN-ALL',
        )
        first_round = create_approval_round(complaint, factory_user)
        pm_approval = next(item for item in first_round if item.approver_role == ApprovalRoles.PM)
        record_approval_decision(
            pm_approval.pk,
            approvers[ApprovalRoles.PM],
            DecisionStatuses.REJECTED,
            'The allowance must be corrected.',
        )
        reconsideration = {
            item.approver_role: item
            for item in ComplaintApproval.objects.filter(complaint=complaint, approval_round=2)
        }
        _, outcome = record_approval_decision(
            reconsideration[ApprovalRoles.OM].pk,
            approvers[ApprovalRoles.OM],
            DecisionStatuses.REJECTED,
            'Return this to the factory executive.',
        )
        self.assertEqual(outcome, 'pending')
        complaint.refresh_from_db()
        self.assertEqual(complaint.workflow_status, WorkflowStatuses.PARTIALLY_APPROVED)

        _, outcome = record_approval_decision(
            reconsideration[ApprovalRoles.CAD].pk,
            approvers[ApprovalRoles.CAD],
            DecisionStatuses.APPROVED,
            'CAD would proceed.',
        )
        complaint.refresh_from_db()
        self.assertEqual(outcome, 'rejected')
        self.assertEqual(complaint.workflow_status, WorkflowStatuses.REWORK_REQUIRED)

    def test_rework_submission_creates_a_fresh_parallel_approval_round(self):
        factory_user = self.create_workflow_user('rework_factory', WorkflowRoles.FACTORY_EXECUTIVE)
        approvers = self.create_approval_accounts(
            [ApprovalRoles.PM, ApprovalRoles.OM, ApprovalRoles.CAD],
            'rework_round',
        )
        complaint = Complaint.objects.create(
            date='2026-07-14',
            country=self.country,
            complaint_type=ComplaintTypes.PATTERN,
            workflow_status=WorkflowStatuses.FACTORY_REVIEW,
            assigned_factory_executive=factory_user,
            factory_priority=FactoryPriorities.LOW,
            status='Open',
            priority='Low',
            complaint_description='Rework round test',
            batch_order='REWORK-ROUND',
        )
        first_round = create_approval_round(complaint, factory_user)
        pm_approval = next(item for item in first_round if item.approver_role == ApprovalRoles.PM)
        record_approval_decision(
            pm_approval.pk,
            approvers[ApprovalRoles.PM],
            DecisionStatuses.REJECTED,
            'PM rejected the first review.',
        )
        reconsideration = {
            item.approver_role: item
            for item in ComplaintApproval.objects.filter(complaint=complaint, approval_round=2)
        }
        record_approval_decision(
            reconsideration[ApprovalRoles.OM].pk,
            approvers[ApprovalRoles.OM],
            DecisionStatuses.APPROVED,
            'OM would proceed.',
        )
        record_approval_decision(
            reconsideration[ApprovalRoles.CAD].pk,
            approvers[ApprovalRoles.CAD],
            DecisionStatuses.REJECTED,
            'CAD requests rework.',
        )

        complaint.refresh_from_db()
        self.assertEqual(complaint.workflow_status, WorkflowStatuses.REWORK_REQUIRED)
        second_round = submit_factory_review(
            complaint,
            factory_user,
            'The rejected pattern allowance has been corrected.',
            'Issue the revised CAD and verify a replacement sample.',
            FactoryPriorities.LOW,
        )

        complaint.refresh_from_db()
        self.assertEqual(complaint.workflow_status, WorkflowStatuses.AWAITING_APPROVAL)
        self.assertEqual({approval.approval_round for approval in second_round}, {3})
        self.assertEqual(ComplaintApproval.objects.filter(complaint=complaint).count(), 8)
        self.assertEqual(
            ComplaintApproval.objects.filter(
                complaint=complaint,
                approval_round=3,
                status=DecisionStatuses.PENDING,
            ).count(),
            3,
        )

    def test_unanimous_medium_approval_gives_green_light_and_allows_closure(self):
        reporter = self.create_workflow_user('green_reporter', WorkflowRoles.COUNTRY_EXECUTIVE)
        factory_user = self.create_workflow_user('green_factory', WorkflowRoles.FACTORY_EXECUTIVE)
        roles = [ApprovalRoles.PM, ApprovalRoles.OM, ApprovalRoles.CAD, ApprovalRoles.ED]
        approvers = self.create_approval_accounts(roles, 'green')
        complaint = Complaint.objects.create(
            date='2026-07-14',
            country=self.country,
            complaint_type=ComplaintTypes.PRODUCTION,
            workflow_status=WorkflowStatuses.FACTORY_REVIEW,
            created_by=reporter,
            assigned_factory_executive=factory_user,
            factory_reason='Production stitching guide was offset.',
            factory_action_plan='Correct the guide and issue a replacement batch.',
            factory_priority=FactoryPriorities.MEDIUM,
            status='Open',
            priority='Medium',
            complaint_description='Unanimous approval closes after execution',
            batch_order='GREEN-LIGHT',
        )
        approvals = create_approval_round(complaint, factory_user)

        outcome = None
        for approval in approvals:
            _, outcome = record_approval_decision(
                approval.pk,
                approvers[approval.approver_role],
                DecisionStatuses.APPROVED,
                f'{approval.approver_role} approves the action plan.',
            )
        complaint.refresh_from_db()
        self.assertEqual(outcome, 'approved')
        self.assertEqual(complaint.workflow_status, WorkflowStatuses.APPROVED)
        self.assertIsNotNone(complaint.fully_approved_at)
        self.assertTrue(Notification.objects.filter(
            recipient=factory_user,
            complaint=complaint,
            notification_type='fully_approved',
        ).exists())

        start_action_execution(complaint, factory_user)
        complaint.refresh_from_db()
        self.assertEqual(complaint.workflow_status, WorkflowStatuses.ACTION_IN_PROGRESS)

        close_complaint_after_execution(
            complaint,
            factory_user,
            date(2026, 7, 14),
            'FABRO-CONTAINER-2026-0714',
        )
        complaint.refresh_from_db()
        self.assertEqual(complaint.workflow_status, WorkflowStatuses.CLOSED)
        self.assertEqual(complaint.status, 'Closed')
        self.assertEqual(complaint.production_updates_container, 'FABRO-CONTAINER-2026-0714')
        self.assertEqual(complaint.closed_by, factory_user)
        self.assertTrue(Notification.objects.filter(
            recipient=reporter,
            complaint=complaint,
            notification_type='closed',
        ).exists())

    def test_line_complaint_closes_without_production_container(self):
        factory_user = self.create_workflow_user('line_factory', WorkflowRoles.FACTORY_EXECUTIVE)
        complaint = Complaint.objects.create(
            date='2026-07-14',
            country=self.country,
            complaint_type=ComplaintTypes.LINE,
            workflow_status=WorkflowStatuses.ACTION_IN_PROGRESS,
            assigned_factory_executive=factory_user,
            status='Open',
            priority='Low',
            complaint_description='Line complaint final update',
            batch_order='LINE-FINAL',
        )

        close_complaint_after_execution(complaint, factory_user, date(2026, 7, 14), '')
        complaint.refresh_from_db()
        self.assertEqual(complaint.workflow_status, WorkflowStatuses.CLOSED)
        self.assertEqual(complaint.production_updates_container, '')

    def test_production_closure_rejects_future_date_and_missing_container(self):
        factory_user = self.create_workflow_user('final_guard_factory', WorkflowRoles.FACTORY_EXECUTIVE)
        complaint = Complaint.objects.create(
            date=timezone.localdate(),
            country=self.country,
            complaint_type=ComplaintTypes.PRODUCTION,
            workflow_status=WorkflowStatuses.ACTION_IN_PROGRESS,
            assigned_factory_executive=factory_user,
            status='Open',
            priority='Medium',
            complaint_description='Final update guards',
            batch_order='FINAL-GUARDS',
        )

        with self.assertRaisesMessage(ValueError, 'cannot be in the future'):
            close_complaint_after_execution(
                complaint,
                factory_user,
                timezone.localdate() + timedelta(days=1),
                'FUTURE-CONTAINER',
            )
        with self.assertRaisesMessage(ValueError, 'Container Number is mandatory'):
            close_complaint_after_execution(
                complaint,
                factory_user,
                timezone.localdate(),
                '',
            )

        complaint.refresh_from_db()
        self.assertEqual(complaint.workflow_status, WorkflowStatuses.ACTION_IN_PROGRESS)
        self.assertEqual(complaint.status, 'Open')

    def test_approval_api_allows_blank_approval_comment_and_requires_rejection_comment(self):
        factory_user = self.create_workflow_user('api_flow_factory', WorkflowRoles.FACTORY_EXECUTIVE)
        approvers = self.create_approval_accounts(
            [ApprovalRoles.PM, ApprovalRoles.OM, ApprovalRoles.CAD],
            'api_flow',
        )
        complaint = Complaint.objects.create(
            date='2026-07-14',
            country=self.country,
            complaint_type=ComplaintTypes.PATTERN,
            workflow_status=WorkflowStatuses.FACTORY_REVIEW,
            assigned_factory_executive=factory_user,
            factory_priority=FactoryPriorities.LOW,
            status='Open',
            priority='Low',
            complaint_description='API approval permission test',
            batch_order='API-APPROVAL',
        )
        approval = next(
            item for item in create_approval_round(complaint, factory_user)
            if item.approver_role == ApprovalRoles.PM
        )
        om_approval = ComplaintApproval.objects.get(
            complaint=complaint,
            approver_role=ApprovalRoles.OM,
        )

        pm_token = Token.objects.create(user=approvers[ApprovalRoles.PM])
        response = self.client.post(
            reverse('api_approval_decision', args=[approval.pk]),
            data=json.dumps({'decision': DecisionStatuses.REJECTED, 'comment': ''}),
            content_type='application/json',
            HTTP_AUTHORIZATION=f'Token {pm_token.key}',
        )
        self.assertEqual(response.status_code, 400)

        om_token = Token.objects.create(user=approvers[ApprovalRoles.OM])
        response = self.client.post(
            reverse('api_approval_decision', args=[approval.pk]),
            data=json.dumps({'decision': DecisionStatuses.APPROVED, 'comment': 'Wrong approver'}),
            content_type='application/json',
            HTTP_AUTHORIZATION=f'Token {om_token.key}',
        )
        self.assertEqual(response.status_code, 403)

        response = self.client.post(
            reverse('api_approval_decision', args=[approval.pk]),
            data=json.dumps({'decision': DecisionStatuses.APPROVED, 'comment': ''}),
            content_type='application/json',
            HTTP_AUTHORIZATION=f'Token {pm_token.key}',
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()['outcome'], 'pending')

        response = self.client.post(
            reverse('api_approval_decision', args=[om_approval.pk]),
            data=json.dumps({'decision': DecisionStatuses.REJECTED, 'comment': 'Correct the CAD allowance.'}),
            content_type='application/json',
            HTTP_AUTHORIZATION=f'Token {om_token.key}',
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()['outcome'], 'reconsideration')

        cad_approval = ComplaintApproval.objects.get(
            complaint=complaint,
            approver_role=ApprovalRoles.CAD,
            review_stage=ApprovalStages.RECONSIDERATION,
        )
        self.client.force_login(approvers[ApprovalRoles.CAD])
        response = self.client.post(
            reverse('approval_review', args=[cad_approval.pk]),
            data={'decision': DecisionStatuses.APPROVED, 'comment': ''},
        )
        self.assertRedirects(response, reverse('approval_inbox'))
        cad_approval.refresh_from_db()
        self.assertEqual(cad_approval.status, DecisionStatuses.APPROVED)
        self.assertEqual(cad_approval.comment, '')

    def test_admin_panel_creates_and_updates_workflow_roles(self):
        self.client.force_login(self.user)
        response = self.client.post(reverse('admin_panel'), {
            'add_user': '1',
            'username': 'configured_approver',
            'email': 'configured.approver@example.com',
            'password': 'ConfiguredApprover!234',
            'role': WorkflowRoles.APPROVER,
            'approval_role': ApprovalRoles.PM,
            'department': 'Management',
        })
        self.assertEqual(response.status_code, 200)
        configured = get_user_model().objects.get(username='configured_approver')
        self.assertEqual(configured.workflow_profile.role, WorkflowRoles.APPROVER)
        self.assertEqual(configured.workflow_profile.approval_role, ApprovalRoles.PM)

        response = self.client.post(reverse('edit_user'), {
            'user_id': configured.pk,
            'username': configured.username,
            'email': configured.email,
            'role': WorkflowRoles.COUNTRY_EXECUTIVE,
            'country': self.country.pk,
            'department': 'KSA Operations',
            'approval_role': '',
        })
        self.assertEqual(response.status_code, 302)
        configured.refresh_from_db()
        configured.workflow_profile.refresh_from_db()
        self.assertEqual(configured.workflow_profile.role, WorkflowRoles.COUNTRY_EXECUTIVE)
        self.assertEqual(configured.workflow_profile.country, self.country)
        self.assertEqual(configured.workflow_profile.approval_role, '')

    def test_create_preparation_preserves_explicit_complaint_category(self):
        complaint = Complaint(
            date='2026-07-14',
            country=self.country,
            complaint_type=ComplaintTypes.PRODUCTION,
            case_sub_category=self.case_type,
            status='Open',
            priority='Low',
            complaint_description='Explicit category must not be inferred from the defect type.',
            batch_order='EXPLICIT-CATEGORY',
        )

        prepare_complaint_for_create(complaint, self.user)

        self.assertEqual(complaint.complaint_type, ComplaintTypes.PRODUCTION)
        self.assertEqual(complaint.workflow_status, WorkflowStatuses.SUBMITTED)

    def test_complaint_list_handles_unconfigured_legacy_approver(self):
        complaint = Complaint.objects.create(
            date='2026-07-14',
            country=self.country,
            complaint_type=ComplaintTypes.PATTERN,
            workflow_status=WorkflowStatuses.CLOSED,
            status='Closed',
            priority='Low',
            complaint_description='Legacy approval without a linked user.',
            batch_order='LEGACY-APPROVER',
        )
        ComplaintApproval.objects.create(
            complaint=complaint,
            approval_round=1,
            approver_role=ApprovalRoles.PM,
            approver_user=None,
            status=DecisionStatuses.PENDING,
        )
        self.client.force_login(self.user)

        response = self.client.get(reverse('complaint_list'))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Not configured')
        self.assertNotContains(
            response,
            reverse('factory_review_complaint', args=[complaint.complaint_id]),
        )

    def test_complaint_journey_tracker_maps_and_renders_workflow_progress(self):
        complaint = Complaint.objects.create(
            date='2026-07-16',
            country=self.country,
            complaint_type=ComplaintTypes.PATTERN,
            workflow_status=WorkflowStatuses.PARTIALLY_APPROVED,
            status='Open',
            priority='Medium',
            complaint_description='Journey tracker regression complaint.',
            batch_order='JOURNEY-TRACKER',
        )

        steps = complaint_journey_steps(complaint)
        self.assertEqual([step['state'] for step in steps], [
            'completed', 'completed', 'current', 'pending', 'pending', 'pending',
        ])

        complaint.workflow_status = WorkflowStatuses.REWORK_REQUIRED
        self.assertEqual(complaint_journey_steps(complaint)[2]['state'], 'attention')

        complaint.workflow_status = WorkflowStatuses.CLOSED
        self.assertTrue(all(
            step['state'] == 'completed'
            for step in complaint_journey_steps(complaint)
        ))

        complaint.workflow_status = WorkflowStatuses.PARTIALLY_APPROVED
        complaint.save(update_fields=['workflow_status'])
        self.client.force_login(self.user)
        response = self.client.get(reverse('complaint_list'))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Complaint Journey')
        self.assertContains(response, 'Partially Approved')
        self.assertContains(response, 'journey-step current')

    def test_profile_admin_button_and_panel_follow_workflow_admin_permission(self):
        workflow_admin = self.create_workflow_user('workflow_admin', WorkflowRoles.ADMIN)
        self.client.force_login(workflow_admin)

        profile_response = self.client.get(reverse('profile_settings'))
        panel_response = self.client.get(reverse('admin_panel'))

        self.assertEqual(profile_response.status_code, 200)
        self.assertContains(profile_response, 'data-testid="open-admin-panel"')
        self.assertContains(profile_response, reverse('admin_panel'))
        self.assertEqual(panel_response.status_code, 200)

        create_response = self.client.post(reverse('admin_panel'), {
            'add_user': '1',
            'username': 'workflow_created_user',
            'email': 'workflow.created@example.com',
            'password': 'WorkflowCreated!234',
            'role': WorkflowRoles.FACTORY_VIEWER,
            'is_staff': 'on',
            'is_superuser': 'on',
        })
        self.assertEqual(create_response.status_code, 200)
        created_user = get_user_model().objects.get(username='workflow_created_user')
        self.assertFalse(created_user.is_staff)
        self.assertFalse(created_user.is_superuser)

        normal_user = self.create_workflow_user('factory_viewer', WorkflowRoles.FACTORY_VIEWER)
        self.client.force_login(normal_user)

        normal_profile_response = self.client.get(reverse('profile_settings'))
        normal_panel_response = self.client.get(reverse('admin_panel'))

        self.assertNotContains(normal_profile_response, 'data-testid="open-admin-panel"')
        self.assertEqual(normal_panel_response.status_code, 302)

    def test_profile_settings_save_and_pill_rendering(self):
        self.login()
        # GET profile page - should contain save icon button and not contain Back to Dashboard
        response = self.client.get(reverse('profile_settings'))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'btn-icon-save')
        self.assertNotContains(response, 'Back to Dashboard')
        self.assertNotContains(response, 'id="flash-messages"')

        # POST profile update
        post_response = self.client.post(reverse('profile_settings'), {
            'update_profile': '1',
            'email': 'updated_admin@fabro.com',
            'first_name': 'Hadi',
            'last_name': 'Muhammed',
        }, follow=True)
        self.assertEqual(post_response.status_code, 200)
        self.assertContains(post_response, 'save-status-pill')
        self.assertContains(post_response, 'Your profile details have been updated successfully.')
        self.assertNotContains(post_response, 'id="flash-messages"')
        country_user = self.create_workflow_user(
            'role_country',
            WorkflowRoles.COUNTRY_EXECUTIVE,
        )
        country_user.workflow_profile.country = self.country
        country_user.workflow_profile.save(update_fields=['country'])
        self.client.force_login(country_user)

        country_dashboard = self.client.get(reverse('index'))
        self.assertContains(country_dashboard, 'Country Executive')
        self.assertContains(country_dashboard, reverse('add_complaint'))
        self.assertNotIn(
            f'href="{reverse("master_settings")}"',
            country_dashboard.content.decode(),
        )
        self.assertEqual(self.client.get(reverse('add_complaint')).status_code, 200)
        country_add_response = self.client.get(reverse('add_complaint'))
        self.assertFalse(country_add_response.context['can_create_line'])
        self.assertNotContains(country_add_response, 'id="complaint-type-line"')

        # Country Executive can view vehicle details read-only
        car_details_response = self.client.get(reverse('car_details'))
        self.assertEqual(car_details_response.status_code, 200)
        self.assertFalse(car_details_response.context['can_manage_catalog'])

        viewer = self.create_workflow_user('role_viewer', WorkflowRoles.FACTORY_VIEWER)
        self.client.force_login(viewer)
        viewer_dashboard = self.client.get(reverse('index'))
        self.assertContains(viewer_dashboard, 'Factory Viewer')
        self.assertNotContains(viewer_dashboard, reverse('add_complaint'))
        self.assertNotIn(
            f'href="{reverse("master_settings")}"',
            viewer_dashboard.content.decode(),
        )
        self.assertEqual(self.client.get(reverse('add_complaint')).status_code, 403)

        factory = self.create_workflow_user('role_factory', WorkflowRoles.FACTORY_EXECUTIVE)
        self.client.force_login(factory)
        self.assertContains(self.client.get(reverse('index')), reverse('add_complaint'))
        self.assertEqual(self.client.get(reverse('add_complaint')).status_code, 200)

        approver = self.create_workflow_user(
            'role_approver',
            WorkflowRoles.APPROVER,
            ApprovalRoles.PM,
        )
        self.client.force_login(approver)
        approver_dashboard = self.client.get(reverse('index'))
        self.assertContains(approver_dashboard, 'Approver')
        self.assertContains(approver_dashboard, reverse('approvals_list'))
        self.assertNotContains(approver_dashboard, reverse('add_complaint'))
        self.assertEqual(self.client.get(reverse('add_complaint')).status_code, 403)

    def test_workflow_admin_can_manage_catalog_and_master_without_superuser_flag(self):
        workflow_admin = self.create_workflow_user('catalog_admin', WorkflowRoles.ADMIN)
        self.assertFalse(workflow_admin.is_staff)
        self.assertFalse(workflow_admin.is_superuser)
        self.client.force_login(workflow_admin)

        dashboard = self.client.get(reverse('index'))
        self.assertContains(dashboard, reverse('master_settings'))
        self.assertEqual(self.client.get(reverse('master_settings')).status_code, 200)
        self.assertEqual(self.client.get(reverse('car_details')).status_code, 200)

        response = self.client.post(reverse('api_skus_list_create'), {
            'code': 'ROLE-ADMIN-SKU',
            'description': 'Created by workflow administrator',
            'region': self.region.pk,
        }, content_type='application/json')
        self.assertEqual(response.status_code, 201)
        self.assertTrue(SKU.objects.filter(code='ROLE-ADMIN-SKU').exists())

    def test_session_termination_requires_post_and_csrf_protected_forms(self):
        self.client.force_login(self.user)
        other_client = self.client_class()
        other_client.force_login(self.user)
        session = Session.objects.get(session_key=self.client.session.session_key)

        single_get = self.client.get(reverse('terminate_session', args=[session.session_key]))
        all_get = self.client.get(reverse('terminate_all_sessions'))
        panel = self.client.get(reverse('admin_panel'))

        self.assertEqual(single_get.status_code, 405)
        self.assertEqual(all_get.status_code, 405)
        self.assertContains(panel, 'method="post"')
        self.assertContains(panel, reverse('terminate_all_sessions'))
        self.assertContains(
            panel,
            reverse('terminate_session', args=[other_client.session.session_key]),
        )


class ChatSystemTests(TestCase):
    def setUp(self):
        User = get_user_model()
        self.sender = User.objects.create_user(username='chat_sender', password='password123')
        self.recipient = User.objects.create_user(username='chat_recipient', password='password123')
        self.complaint = Complaint.objects.create(
            complaint_id='PAT-26089999',
            date='2026-08-23',
            complaint_type='pattern',
            status='Open',
            priority='High',
            complaint_description='Chat test complaint'
        )

    def test_chat_page_and_send_message_api(self):
        self.client.force_login(self.sender)
        response = self.client.get(reverse('chat_view'))
        self.assertEqual(response.status_code, 200)

        # Send message via API
        send_response = self.client.post(reverse('chat_send_api'), {
            'recipient_id': self.recipient.id,
            'message': 'Hello there regarding PAT-26089999',
            'complaint_id': self.complaint.complaint_id,
        })
        self.assertEqual(send_response.status_code, 200)
        self.assertTrue(ChatMessage.objects.filter(sender=self.sender, recipient=self.recipient).exists())

        # Check messages API
        msg_response = self.client.get(reverse('chat_messages_api', args=[self.recipient.id]))
        self.assertEqual(msg_response.status_code, 200)
        json_data = msg_response.json()
        self.assertEqual(json_data['status'], 'ok')
        self.assertEqual(len(json_data['messages']), 1)
        self.assertEqual(json_data['messages'][0]['complaint_id'], 'PAT-26089999')

    def test_unread_messages_sorted_to_top_by_latest(self):
        User = get_user_model()
        user_a = User.objects.create_user(username='alpha_user', password='password123')
        user_b = User.objects.create_user(username='beta_user', password='password123')
        user_c = User.objects.create_user(username='gamma_user', password='password123')

        # User B sends message to sender first
        msg1 = ChatMessage.objects.create(
            sender=user_b,
            recipient=self.sender,
            message='Older unread from Beta',
            is_read=False,
        )

        # User A sends message to sender later (latest unread)
        msg2 = ChatMessage.objects.create(
            sender=user_a,
            recipient=self.sender,
            message='Latest unread from Alpha',
            is_read=False,
        )

        # User C has read messages
        msg3 = ChatMessage.objects.create(
            sender=user_c,
            recipient=self.sender,
            message='Read message from Gamma',
            is_read=True,
        )

        self.client.force_login(self.sender)
        api_res = self.client.get(reverse('chat_users_api'))
        self.assertEqual(api_res.status_code, 200)
        users = api_res.json()['users']

        # Alpha should be first (latest unread), then Beta (older unread), then Gamma (read), then recipient (no msg)
        usernames = [u['username'] for u in users]
        self.assertEqual(usernames[0], 'alpha_user')
        self.assertEqual(usernames[1], 'beta_user')
        self.assertEqual(usernames[2], 'gamma_user')
        self.assertEqual(users[0]['unread_count'], 1)
        self.assertEqual(users[1]['unread_count'], 1)
        self.assertEqual(users[2]['unread_count'], 0)


class ApprovalsWorkspaceTests(TestCase):
    def setUp(self):
        User = get_user_model()
        self.country_ksa = MasterSetting.objects.create(category='Country', name='KSA')
        self.country_uae = MasterSetting.objects.create(category='Country', name='UAE')

        # Create Country Executive for KSA
        self.country_exec = User.objects.create_user(username='ksa_exec', password='password123')
        UserProfile.objects.filter(user=self.country_exec).update(role=WorkflowRoles.COUNTRY_EXECUTIVE, country=self.country_ksa)

        # Create Factory Executive
        self.factory_exec = User.objects.create_user(username='fac_exec', password='password123')
        UserProfile.objects.filter(user=self.factory_exec).update(role=WorkflowRoles.FACTORY_EXECUTIVE, can_receive_factory_assignments=True)

        # Create Approver (PM)
        self.pm_approver = User.objects.create_user(username='pm_user', password='password123')
        UserProfile.objects.filter(user=self.pm_approver).update(role=WorkflowRoles.APPROVER, approval_role=ApprovalRoles.PM)

        # Create Approver (OM)
        self.om_approver = User.objects.create_user(username='om_user', password='password123')
        UserProfile.objects.filter(user=self.om_approver).update(role=WorkflowRoles.APPROVER, approval_role=ApprovalRoles.OM)

        # Create Admin
        self.admin_user = User.objects.create_user(username='wf_admin', password='password123', is_superuser=True)
        UserProfile.objects.filter(user=self.admin_user).update(role=WorkflowRoles.ADMIN)

        # Create Factory Viewer (restricted)
        self.viewer_user = User.objects.create_user(username='fac_viewer', password='password123')
        UserProfile.objects.filter(user=self.viewer_user).update(role=WorkflowRoles.FACTORY_VIEWER)

        # Create Complaint in KSA awaiting approval
        self.complaint_ksa = Complaint.objects.create(
            complaint_id='PAT-26081001',
            date='2026-08-23',
            complaint_type=ComplaintTypes.PATTERN,
            country=self.country_ksa,
            workflow_status=WorkflowStatuses.AWAITING_APPROVAL,
            factory_priority='top',
            factory_reason='Dimension mismatch on cushion',
            factory_action_plan='Recalibrate CNC cutter and update CAD',
            assigned_factory_executive=self.factory_exec,
        )

        # Create Complaint in UAE awaiting approval
        self.complaint_uae = Complaint.objects.create(
            complaint_id='PRO-26081002',
            date='2026-08-23',
            complaint_type=ComplaintTypes.PRODUCTION,
            country=self.country_uae,
            workflow_status=WorkflowStatuses.AWAITING_APPROVAL,
            factory_priority='medium',
            factory_reason='Leather discoloration',
            factory_action_plan='Replace hide batch',
            assigned_factory_executive=self.factory_exec,
        )

        # Create approvals for KSA complaint (PM & OM)
        self.approval_pm = ComplaintApproval.objects.create(
            complaint=self.complaint_ksa,
            approval_round=1,
            approver_role=ApprovalRoles.PM,
            approver_user=self.pm_approver,
            status=DecisionStatuses.PENDING,
            required=True,
        )
        self.approval_om = ComplaintApproval.objects.create(
            complaint=self.complaint_ksa,
            approval_round=1,
            approver_role=ApprovalRoles.OM,
            approver_user=self.om_approver,
            status=DecisionStatuses.PENDING,
            required=True,
        )

    def test_factory_viewer_is_forbidden_from_approvals_workspace(self):
        self.client.force_login(self.viewer_user)
        response = self.client.get(reverse('approvals_list'))
        self.assertEqual(response.status_code, 403)

        # Check navbar does not include Approvals for viewer
        index_res = self.client.get(reverse('index'))
        self.assertNotContains(index_res, reverse('approvals_list'))

    def test_country_executive_sees_only_own_country_approvals(self):
        self.client.force_login(self.country_exec)
        response = self.client.get(reverse('approvals_list'))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'PAT-26081001')
        self.assertNotContains(response, 'PRO-26081002')

    def test_approver_and_admin_see_approvals_workspace(self):
        self.client.force_login(self.pm_approver)
        response = self.client.get(reverse('approvals_list'))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'PAT-26081001')
        self.assertContains(response, 'Recalibrate CNC cutter')
        self.assertContains(response, 'Live Approver Status Matrix')

        self.client.force_login(self.admin_user)
        admin_response = self.client.get(reverse('approvals_list'))
        self.assertEqual(admin_response.status_code, 200)
        self.assertContains(admin_response, 'PAT-26081001')
        self.assertContains(admin_response, 'PRO-26081002')

    def test_factory_executive_sees_approvals_workspace(self):
        self.client.force_login(self.factory_exec)
        response = self.client.get(reverse('approvals_list'))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'PAT-26081001')

    def test_quick_approval_decision_api(self):
        self.client.force_login(self.pm_approver)
        response = self.client.post(
            reverse('quick_approval_decision_api', args=[self.approval_pm.id]),
            data={'decision': DecisionStatuses.APPROVED, 'comment': 'Looks good to go'},
        )
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()['success'])

        self.approval_pm.refresh_from_db()
        self.assertEqual(self.approval_pm.status, DecisionStatuses.APPROVED)
        self.assertEqual(self.approval_pm.comment, 'Looks good to go')


