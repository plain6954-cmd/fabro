import os
import shutil
import tempfile
from unittest.mock import MagicMock, patch

from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.test import TestCase

from management.models import (
    Brand,
    Model,
    PatternDesignFolder,
    PatternDesignImage,
    SubModel,
    YearRange,
)
from management.services.drive_scanner import (
    DriveItem,
    GoogleDriveClient,
    VehicleAttributes,
    VehicleMatcher,
    canonical_brand_name,
    expand_short_year,
    extract_vehicle_attributes_from_path,
    normalize_token,
    parse_door_count,
    parse_seat_count,
    parse_year_range,
    strip_devanagari,
)

User = get_user_model()


class DriveImporterUnitTests(TestCase):
    def setUp(self):
        self.brand_chevrolet = Brand.objects.create(name="CHEVROLET")
        self.model_captiva = Model.objects.create(brand=self.brand_chevrolet, name="CAPTIVA")
        self.sub_captiva = SubModel.objects.create(model=self.model_captiva, name="")
        self.yr_captiva = YearRange.objects.create(
            sub_model=self.sub_captiva,
            year_start=2019,
            year_end=2024,
            number_of_seats=7,
            number_of_doors=4,
            x_code="X1654",
        )

        self.model_traverse = Model.objects.create(brand=self.brand_chevrolet, name="TRAVERSE")
        self.sub_traverse_n2 = SubModel.objects.create(model=self.model_traverse, name="N2")
        self.yr_traverse = YearRange.objects.create(
            sub_model=self.sub_traverse_n2,
            year_start=2018,
            year_end=2025,
            number_of_seats=7,
            number_of_doors=4,
            x_code="X1438",
        )

        self.brand_ford = Brand.objects.create(name="FORD")
        self.model_expedition = Model.objects.create(brand=self.brand_ford, name="EXPEDITION")
        self.sub_expedition = SubModel.objects.create(model=self.model_expedition, name="")
        self.yr_expedition_08 = YearRange.objects.create(
            sub_model=self.sub_expedition,
            year_start=2008,
            year_end=2017,
            number_of_seats=7,
            number_of_doors=4,
        )
        self.yr_expedition_18 = YearRange.objects.create(
            sub_model=self.sub_expedition,
            year_start=2018,
            year_end=2024,
            number_of_seats=7,
            number_of_doors=4,
        )

        # Ambiguous vehicle models
        self.model_ambig = Model.objects.create(brand=self.brand_ford, name="FOCUS")
        self.sub_ambig1 = SubModel.objects.create(model=self.model_ambig, name="Sedan")
        self.yr_ambig1 = YearRange.objects.create(
            sub_model=self.sub_ambig1,
            year_start=2015,
            year_end=2018,
            number_of_seats=5,
            number_of_doors=4,
        )
        self.sub_ambig2 = SubModel.objects.create(model=self.model_ambig, name="Hatchback")
        self.yr_ambig2 = YearRange.objects.create(
            sub_model=self.sub_ambig2,
            year_start=2015,
            year_end=2018,
            number_of_seats=5,
            number_of_doors=5,
        )

    def test_strip_devanagari(self):
        raw = "Chevrolet शेवरलेट / Captiva कैप्टिवा 19-24 7S"
        cleaned = strip_devanagari(raw)
        self.assertNotIn("शेवरलेट", cleaned)
        self.assertNotIn("कैप्टिवा", cleaned)
        self.assertIn("Chevrolet", cleaned)
        self.assertIn("Captiva", cleaned)

    def test_case_and_punctuation_normalization(self):
        self.assertEqual(normalize_token("  CHEVROLET -  captiva__7S  "), "chevrolet captiva 7s")
        self.assertEqual(canonical_brand_name("KIA"), "Kia")
        self.assertEqual(canonical_brand_name("mg"), "MG")
        self.assertEqual(canonical_brand_name("GMC"), "GMC")

    def test_year_range_parsing(self):
        self.assertEqual(parse_year_range("Captiva 19-24 7S"), (2019, 2024))
        self.assertEqual(parse_year_range("Victoria 98-14 5S"), (1998, 2014))
        self.assertEqual(parse_year_range("Swift 05-10 BR1"), (2005, 2010))
        self.assertEqual(parse_year_range("Expedition 2008-2017"), (2008, 2017))
        self.assertEqual(parse_year_range("Traverse 2020-25"), (2020, 2025))

    def test_seat_and_door_parsing(self):
        self.assertEqual(parse_seat_count("Captiva 19-24 7S"), 7)
        self.assertEqual(parse_seat_count("H1 14-21 N2 12S"), 12)
        self.assertEqual(parse_door_count("Hilux 4D 16-25 5S"), 4)
        self.assertEqual(parse_door_count("Yaris 3D 14-20"), 3)

    def test_exact_match(self):
        item = DriveItem(
            id="drv_12345",
            name="IMG_20260123_141313~2.jpg",
            mime="image/jpeg",
            size=520190,
            path="Chevrolet शेवरलेट/Captiva कैप्टिवा 19-24 7S/IMG_20260123_141313~2.jpg",
        )
        attr = extract_vehicle_attributes_from_path(item)
        matcher = VehicleMatcher()
        res = matcher.match(item, attr)

        self.assertEqual(res.match_classification, "EXACT")
        self.assertEqual(res.candidate_id, self.yr_captiva.id)
        self.assertEqual(res.detected_seats, 7)

    def test_submodel_and_code_matching(self):
        item = DriveItem(
            id="drv_traverse",
            name="IMG_traverse.jpg",
            mime="image/jpeg",
            size=100000,
            path="Chevrolet शेवरलेट/Traverse ट्रेवर्स 18-25_N2 7S/IMG_traverse.jpg",
        )
        attr = extract_vehicle_attributes_from_path(item)
        matcher = VehicleMatcher()
        res = matcher.match(item, attr)

        self.assertEqual(res.match_classification, "EXACT")
        self.assertEqual(res.candidate_id, self.yr_traverse.id)

    def test_year_conflict(self):
        # Captiva 2026-2028 does not match 2019-2024
        item = DriveItem(
            id="drv_captiva_new",
            name="IMG_new.jpg",
            mime="image/jpeg",
            size=100000,
            path="Chevrolet शेवरलेट/Captiva कैप्टिवा 26-28 7S/IMG_new.jpg",
        )
        attr = extract_vehicle_attributes_from_path(item)
        matcher = VehicleMatcher()
        res = matcher.match(item, attr)

        self.assertEqual(res.match_classification, "CONFLICT")
        self.assertIn("Year mismatch", res.conflict_reason)

    def test_ambiguous_matching(self):
        # Focus 15-18 without submodel matches both Sedan and Hatchback equally
        item = DriveItem(
            id="drv_focus",
            name="IMG_focus.jpg",
            mime="image/jpeg",
            size=100000,
            path="Ford फोर्ड/Focus 15-18 5S/IMG_focus.jpg",
        )
        attr = extract_vehicle_attributes_from_path(item)
        matcher = VehicleMatcher()
        res = matcher.match(item, attr)

        self.assertEqual(res.match_classification, "AMBIGUOUS")
        self.assertIsNone(res.candidate_id)

    def test_unsupported_file_types(self):
        item_pdf = DriveItem(
            id="drv_pdf",
            name="Manual.pdf",
            mime="application/pdf",
            size=200000,
            path="Chevrolet शेवरलेट/Captiva कैप्टिवा 19-24 7S/Manual.pdf",
        )
        attr = extract_vehicle_attributes_from_path(item_pdf)
        matcher = VehicleMatcher()
        res = matcher.match(item_pdf, attr)

        self.assertEqual(res.match_classification, "UNSUPPORTED")

        item_cut = DriveItem(
            id="drv_cut",
            name="Tucson.cut",
            mime="application/octet-stream",
            size=100000,
            path="Hyundai ह्युंडई/Tucson 21-25.cut",
        )
        attr_cut = extract_vehicle_attributes_from_path(item_cut)
        res_cut = matcher.match(item_cut, attr_cut)
        self.assertEqual(res_cut.match_classification, "UNSUPPORTED")

    def test_duplicate_detection(self):
        admin_user = User.objects.create_superuser("admin_test", "admin@test.com", "pass123")
        folder = PatternDesignFolder.objects.create(name="Captiva 19-24 7S", vehicle=self.yr_captiva)
        PatternDesignImage.objects.create(
            folder=folder,
            vehicle=self.yr_captiva,
            title="IMG_20260123_141313~2.jpg [Drive:drv_existing_123]",
            file_size=5000,
            uploaded_by=admin_user,
        )

        item = DriveItem(
            id="drv_existing_123",
            name="IMG_20260123_141313~2.jpg",
            mime="image/jpeg",
            size=5000,
            path="Chevrolet शेवरलेट/Captiva कैप्टिवा 19-24 7S/IMG_20260123_141313~2.jpg",
        )
        attr = extract_vehicle_attributes_from_path(item)
        matcher = VehicleMatcher()
        res = matcher.match(item, attr)

        self.assertEqual(res.match_classification, "DUPLICATE")
        self.assertTrue(res.already_exists)

    def test_dry_run_makes_no_database_changes(self):
        initial_folders = PatternDesignFolder.objects.count()
        initial_images = PatternDesignImage.objects.count()

        # Run command with dry run
        call_command("import_vehicle_drive_designs", "--dry-run")

        self.assertEqual(PatternDesignFolder.objects.count(), initial_folders)
        self.assertEqual(PatternDesignImage.objects.count(), initial_images)

    def test_apply_and_rollback(self):
        admin_user = User.objects.create_superuser("admin_apply", "admin2@test.com", "pass123")
        initial_folders = PatternDesignFolder.objects.count()
        initial_images = PatternDesignImage.objects.count()

        # Mock download_file_bytes to avoid network calls during test
        with patch.object(
            GoogleDriveClient, "download_file_bytes", return_value=b"\xff\xd8\xff\xe0mock_jpeg_data"
        ):
            with patch.object(
                GoogleDriveClient,
                "crawl_all",
                return_value=(
                    [
                        DriveItem(
                            id="fld_1",
                            name="Captiva कैप्टिवा 19-24 7S",
                            mime="application/vnd.google-apps.folder",
                            size=0,
                            path="Chevrolet शेवरलेट/Captiva कैप्टिवा 19-24 7S",
                            is_folder=True,
                        )
                    ],
                    [
                        DriveItem(
                            id="img_1",
                            name="test_design.jpg",
                            mime="image/jpeg",
                            size=1234,
                            path="Chevrolet शेवरलेट/Captiva कैप्टिवा 19-24 7S/test_design.jpg",
                            is_folder=False,
                        )
                    ],
                ),
            ):
                # Execute apply
                call_command("import_vehicle_drive_designs", "--apply")

                self.assertEqual(PatternDesignImage.objects.count(), initial_images + 1)
                self.assertEqual(PatternDesignFolder.objects.count(), initial_folders + 1)

                created_img = PatternDesignImage.objects.latest("id")
                self.assertIn("test_design.jpg", created_img.title)
                self.assertEqual(created_img.vehicle_id, self.yr_captiva.id)

                # Test Rollback
                call_command("import_vehicle_drive_designs", "--rollback", "latest")

                self.assertEqual(PatternDesignImage.objects.count(), initial_images)
                self.assertEqual(PatternDesignFolder.objects.count(), initial_folders)
