from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import Client, TestCase, override_settings
from django.urls import reverse

from .models import Brand, Complaint, ComplaintMedia, MasterSetting, Model, SKU, SubModel, YearRange


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

    def test_protected_routes_redirect_anonymous_users(self):
        for route_name in ["index", "complaint_list", "add_complaint", "car_details", "add_sku", "master_settings", "profile_settings"]:
            response = self.client.get(reverse(route_name))
            self.assertEqual(response.status_code, 302, route_name)
            self.assertIn("/login/", response["Location"])

    def test_dashboard_and_main_pages_render_for_authenticated_user(self):
        self.login()
        for route_name in ["index", "complaint_list", "add_complaint", "car_details", "add_car_details", "add_sku", "master_settings", "profile_settings"]:
            response = self.client.get(reverse(route_name))
            self.assertEqual(response.status_code, 200, route_name)

    def test_complaint_create_edit_delete_and_media_fallback(self):
        self.login()
        upload = SimpleUploadedFile("backend-test.txt", b"hello", content_type="text/plain")
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
        self.assertTrue(complaint.media_files.first().file.startswith("/media/") or complaint.media_files.first().file.startswith("https://"))

        response = self.client.post(reverse("edit_complaint", args=[complaint.complaint_id]), {
            "status": "Closed",
            "priority": "High",
            "complaint_description": "Backend complaint updated",
            "batch_order": "BATCH-2",
        })
        self.assertEqual(response.status_code, 302)
        complaint.refresh_from_db()
        self.assertEqual(complaint.status, "Closed")
        self.assertEqual(complaint.priority, "High")

        response = self.client.post(reverse("delete_complaint", args=[complaint.complaint_id]))
        self.assertEqual(response.status_code, 302)
        self.assertFalse(Complaint.objects.filter(complaint_id=complaint.complaint_id).exists())

    def test_vehicle_sku_and_master_crud_routes(self):
        self.login()
        response = self.client.post(reverse("add_car_details"), {
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

        response = self.client.get(reverse("delete_master_setting", args=[setting.id]))
        self.assertEqual(response.status_code, 302)
        self.assertFalse(MasterSetting.objects.filter(id=setting.id).exists())

        response = self.client.get(reverse("delete_car_detail", args=[new_year.id]))
        self.assertEqual(response.status_code, 302)
        self.assertFalse(YearRange.objects.filter(id=new_year.id).exists())

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
