import csv
import hashlib
import json
import logging
import os
import sys
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Set

from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.files.base import ContentFile
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from management.models import PatternDesignFolder, PatternDesignImage, YearRange
from management.services.drive_scanner import (
    DriveItem,
    GoogleDriveClient,
    MatchClassification,
    MatchResult,
    VehicleMatcher,
    extract_vehicle_attributes_from_path,
)

logger = logging.getLogger(__name__)

DEFAULT_FOLDER_URL = "https://drive.google.com/drive/folders/13m5IkDAVYm0v5ihmnvVwMywRk-Mfptgu?usp=drive_link"
RUN_LOG_PATH = Path(settings.BASE_DIR) / "scratch" / "import_runs.json"


class Command(BaseCommand):
    help = "Safe, one-time import of vehicle design images from Google Drive into Pattern Master"

    def add_arguments(self, parser):
        parser.add_argument(
            "--folder-url",
            type=str,
            default=DEFAULT_FOLDER_URL,
            help="Google Drive folder URL or ID to scan (defaults to provided shared folder)",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            default=True,
            help="Run in dry-run mode (default). No database or storage changes will be made.",
        )
        parser.add_argument(
            "--apply",
            action="store_true",
            default=False,
            help="Execute real import. Only EXACT matches and explicitly approved mappings will be imported.",
        )
        parser.add_argument(
            "--approved-mappings",
            type=str,
            default=None,
            help="Path to JSON file specifying approved candidate vehicle IDs for PROBABLE matches.",
        )
        parser.add_argument(
            "--report-json",
            type=str,
            default=None,
            help="Path for JSON report output (defaults to scratch/import_drive_report.json)",
        )
        parser.add_argument(
            "--report-csv",
            type=str,
            default=None,
            help="Path for CSV report output (defaults to scratch/import_drive_report.csv)",
        )
        parser.add_argument(
            "--cache-file",
            type=str,
            default=str(Path(settings.BASE_DIR) / "scratch" / "crawl_results.json"),
            help="Path to Drive crawl cache file",
        )
        parser.add_argument(
            "--refresh-drive",
            action="store_true",
            default=False,
            help="Force re-crawling Google Drive folder instead of using existing cache file",
        )
        parser.add_argument(
            "--rollback",
            type=str,
            default=None,
            help="Rollback created records from a previous import run by Run ID (or 'latest')",
        )
        parser.add_argument(
            "--google-api-key",
            type=str,
            default=None,
            help="Optional Google API Key for Drive API access",
        )

    def handle(self, *args, **options):
        # Handle Rollback if requested
        if options.get("rollback"):
            self.handle_rollback(options["rollback"])
            return

        is_apply = options.get("apply", False)
        is_dry_run = not is_apply  # Default is dry-run unless --apply is explicitly passed

        self.stdout.write(self.style.MIGRATE_HEADING("=" * 70))
        self.stdout.write(
            self.style.MIGRATE_HEADING("  FABRO LEATHER PORTAL — PATTERN MASTER DESIGN IMAGE IMPORTER")
        )
        mode_str = self.style.WARNING("DRY-RUN (NO CHANGES WILL BE MADE)") if is_dry_run else self.style.SUCCESS("APPLY (LIVE IMPORT)")
        self.stdout.write(f"  Mode: {mode_str}")
        self.stdout.write(self.style.MIGRATE_HEADING("=" * 70))

        # Setup paths
        scratch_dir = Path(settings.BASE_DIR) / "scratch"
        scratch_dir.mkdir(parents=True, exist_ok=True)

        report_json_path = (
            Path(options["report_json"])
            if options.get("report_json")
            else scratch_dir / "import_drive_report.json"
        )
        report_csv_path = (
            Path(options["report_csv"])
            if options.get("report_csv")
            else scratch_dir / "import_drive_report.csv"
        )

        folder_url = options.get("folder_url") or DEFAULT_FOLDER_URL
        drive_client = GoogleDriveClient(api_key=options.get("google_api_key"))
        folder_id = drive_client.extract_folder_id(folder_url)

        self.stdout.write(f"[*] Target Drive Folder ID: {folder_id}")

        cache_file = options.get("cache_file")
        use_cache = not options.get("refresh_drive", False)

        # Step 1: Crawl Google Drive
        self.stdout.write("[*] Scanning Drive directory tree...")
        folders, files = drive_client.crawl_all(
            root_folder_id=folder_id,
            cache_file=cache_file,
            use_cache=use_cache,
        )
        self.stdout.write(
            self.style.SUCCESS(
                f"[+] Scan complete: {len(folders)} folders and {len(files)} files discovered."
            )
        )

        # Step 2: Load Approved Mappings if provided
        approved_mappings: Dict[str, int] = {}
        if options.get("approved_mappings"):
            map_path = Path(options["approved_mappings"])
            if map_path.exists():
                try:
                    with open(map_path, "r", encoding="utf-8") as mf:
                        approved_mappings = json.load(mf)
                    self.stdout.write(
                        self.style.SUCCESS(f"[+] Loaded {len(approved_mappings)} approved mappings from {map_path}")
                    )
                except Exception as e:
                    raise CommandError(f"Failed to read approved mappings file: {e}")

        # Step 3: Match files against Pattern Master vehicles
        self.stdout.write("[*] Matching Drive items against Pattern Master records...")
        matcher = VehicleMatcher()

        results: List[MatchResult] = []
        matched_vehicle_ids: Set[int] = set()

        for item in files:
            attr = extract_vehicle_attributes_from_path(item)
            res = matcher.match(item, attr)

            # Check if this item is in approved mappings
            if (
                res.match_classification == "PROBABLE"
                and res.drive_file_id in approved_mappings
            ):
                target_id = approved_mappings[res.drive_file_id]
                try:
                    target_yr = YearRange.objects.select_related("sub_model__model__brand").get(id=target_id)
                    res.candidate_id = target_yr.id
                    res.vehicle_record = target_yr
                    res.match_classification = "EXACT"
                    res.match_confidence = 1.0
                    res.conflict_reason = "Manually approved via mapping file"
                    res.proposed_action = "Import to Pattern Master (Approved mapping)"
                except YearRange.DoesNotExist:
                    res.conflict_reason += f"; Approved vehicle ID {target_id} does not exist"

            results.append(res)
            if res.candidate_id and res.match_classification in ("EXACT", "PROBABLE"):
                matched_vehicle_ids.add(res.candidate_id)

        # Step 4: Compute Totals
        all_vehicle_ids = set(YearRange.objects.values_list("id", flat=True))
        unmatched_vehicles = all_vehicle_ids - matched_vehicle_ids

        total_folders = len(folders)
        total_files = len(files)
        supported_images = sum(1 for r in results if r.match_classification != "UNSUPPORTED")
        exact_matches = sum(1 for r in results if r.match_classification == "EXACT")
        probable_matches = sum(1 for r in results if r.match_classification == "PROBABLE")
        ambiguous_matches = sum(1 for r in results if r.match_classification == "AMBIGUOUS")
        conflicts = sum(1 for r in results if r.match_classification == "CONFLICT")
        unmatched_files = sum(1 for r in results if r.match_classification == "UNMATCHED")
        duplicates = sum(1 for r in results if r.match_classification == "DUPLICATE")
        unsupported_files = sum(1 for r in results if r.match_classification == "UNSUPPORTED")
        records_without_images = len(unmatched_vehicles)

        # Print Summary
        self.stdout.write("\n" + "=" * 70)
        self.stdout.write("  IMPORTER SUMMARY & CLASSIFICATION TOTALS")
        self.stdout.write("=" * 70)
        self.stdout.write(f"  Total folders scanned:                    {total_folders}")
        self.stdout.write(f"  Total files scanned:                      {total_files}")
        self.stdout.write(f"  Supported images:                         {supported_images}")
        self.stdout.write(self.style.SUCCESS(f"  Exact matches:                            {exact_matches}"))
        self.stdout.write(self.style.WARNING(f"  Probable matches:                         {probable_matches}"))
        self.stdout.write(self.style.WARNING(f"  Ambiguous matches:                        {ambiguous_matches}"))
        self.stdout.write(self.style.ERROR(f"  Conflicts:                                {conflicts}"))
        self.stdout.write(f"  Unmatched files:                          {unmatched_files}")
        self.stdout.write(f"  Duplicate files:                          {duplicates}")
        self.stdout.write(f"  Unsupported files:                        {unsupported_files}")
        self.stdout.write(f"  Pattern Master records without images:    {records_without_images}")
        self.stdout.write("=" * 70 + "\n")

        # Step 5: Generate Dry-Run Report (JSON & CSV)
        self.write_reports(results, report_json_path, report_csv_path)
        self.stdout.write(self.style.SUCCESS(f"[+] Detailed JSON report written to: {report_json_path}"))
        self.stdout.write(self.style.SUCCESS(f"[+] Detailed CSV report written to:  {report_csv_path}"))

        # Step 6: Handle Apply if enabled
        if is_dry_run:
            self.stdout.write(
                self.style.SUCCESS(
                    "\n[v] DRY-RUN VERIFIED: Zero database and zero storage changes were made.\n"
                    "    Review the reports above. To execute the live import, rerun with --apply.\n"
                )
            )
            return

        # Execute Live Import
        self.stdout.write(self.style.MIGRATE_HEADING("[*] Executing Live Import (--apply)..."))
        self.execute_import(results, drive_client)

    def write_reports(self, results: List[MatchResult], json_path: Path, csv_path: Path):
        """Write JSON and CSV reports."""
        report_data = []
        for r in results:
            report_data.append({
                "drive_relative_path": r.drive_path,
                "drive_file_name": r.drive_file_name,
                "drive_file_id": r.drive_file_id,
                "detected_brand": r.detected_brand,
                "detected_model": r.detected_model,
                "detected_year_range": r.detected_year_range,
                "detected_submodel": r.detected_submodel,
                "detected_seats": r.detected_seats,
                "detected_doors": r.detected_doors,
                "detected_code": r.detected_code,
                "candidate_pattern_master_record_id": r.candidate_id,
                "candidate_vehicle_description": r.candidate_description,
                "match_classification": r.match_classification,
                "match_confidence": r.match_confidence,
                "conflict_reason": r.conflict_reason,
                "proposed_design_folder_destination": r.proposed_design_folder,
                "already_exists": r.already_exists,
                "proposed_action": r.proposed_action,
            })

        # Save JSON
        with open(json_path, "w", encoding="utf-8") as f:
            json.dump(report_data, f, ensure_ascii=False, indent=2)

        # Save CSV
        if report_data:
            fieldnames = list(report_data[0].keys())
            with open(csv_path, "w", encoding="utf-8", newline="") as f:
                writer = csv.DictWriter(f, fieldnames=fieldnames)
                writer.writeheader()
                writer.writerows(report_data)

    def execute_import(self, results: List[MatchResult], drive_client: GoogleDriveClient):
        """Execute real import of approved exact matches."""
        import_run_id = f"RUN-{datetime.utcnow().strftime('%Y%m%d%H%M%S')}-{uuid.uuid4().hex[:6]}"
        created_image_ids: List[int] = []
        created_folder_ids: List[int] = []

        to_import = [r for r in results if r.match_classification == "EXACT" and not r.already_exists]
        self.stdout.write(f"[*] Found {len(to_import)} EXACT items ready for import.")

        admin_user = get_user_model().objects.filter(is_superuser=True).first()

        imported_count = 0
        failed_count = 0

        for idx, item_res in enumerate(to_import, 1):
            file_id = item_res.drive_file_id
            yr = item_res.vehicle_record or YearRange.objects.get(id=item_res.candidate_id)
            folder_name = item_res.proposed_design_folder or f"{yr.sub_model.model.name} Design"

            self.stdout.write(f"  [{idx}/{len(to_import)}] Downloading {item_res.drive_file_name}...")
            content = drive_client.download_file_bytes(file_id)
            if not content:
                self.stdout.write(self.style.ERROR(f"    [!] Failed to download file {file_id}. Skipping."))
                failed_count += 1
                continue

            try:
                with transaction.atomic():
                    # Find or create PatternDesignFolder
                    folder, created_f = PatternDesignFolder.objects.get_or_create(
                        name=folder_name,
                        vehicle=yr,
                        defaults={"created_by": admin_user},
                    )
                    if created_f:
                        created_folder_ids.append(folder.id)

                    # Sanitize filename
                    clean_name = os.path.basename(item_res.drive_file_name)
                    # Title preserves Drive file ID for tracking
                    title = f"{clean_name} [Drive:{file_id}]"

                    design_img = PatternDesignImage(
                        folder=folder,
                        vehicle=yr,
                        title=title[:255],
                        file_size=len(content),
                        uploaded_by=admin_user,
                    )
                    design_img.image.save(clean_name, ContentFile(content), save=False)
                    design_img.save()

                    created_image_ids.append(design_img.id)
                    imported_count += 1
                    self.stdout.write(
                        self.style.SUCCESS(
                            f"    [+] Imported image ID {design_img.id} into folder '{folder.name}' (Vehicle ID {yr.id})"
                        )
                    )
            except Exception as e:
                self.stdout.write(self.style.ERROR(f"    [!] Error importing {item_res.drive_file_name}: {e}"))
                failed_count += 1

        # Record Run for rollback
        run_record = {
            "run_id": import_run_id,
            "timestamp": datetime.utcnow().isoformat(),
            "imported_count": imported_count,
            "failed_count": failed_count,
            "created_folder_ids": created_folder_ids,
            "created_image_ids": created_image_ids,
        }
        self.save_run_log(run_record)

        self.stdout.write("\n" + "=" * 70)
        self.stdout.write(self.style.SUCCESS(f"  IMPORT COMPLETE (Run ID: {import_run_id})"))
        self.stdout.write(f"  Successfully imported: {imported_count}")
        self.stdout.write(f"  Failed downloads/saves: {failed_count}")
        self.stdout.write(f"  Rollback command: python manage.py import_vehicle_drive_designs --rollback {import_run_id}")
        self.stdout.write("=" * 70 + "\n")

    def save_run_log(self, run_record: Dict[str, Any]):
        """Persist import run log for rollback."""
        RUN_LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
        runs = []
        if RUN_LOG_PATH.exists():
            try:
                with open(RUN_LOG_PATH, "r", encoding="utf-8") as f:
                    runs = json.load(f)
            except Exception:
                runs = []
        runs.append(run_record)
        with open(RUN_LOG_PATH, "w", encoding="utf-8") as f:
            json.dump(runs, f, ensure_ascii=False, indent=2)

    def handle_rollback(self, rollback_id: str):
        """Rollback records created in an import run."""
        if not RUN_LOG_PATH.exists():
            raise CommandError("No import runs log found to rollback from.")

        with open(RUN_LOG_PATH, "r", encoding="utf-8") as f:
            runs = json.load(f)

        target_run = None
        if rollback_id.lower() == "latest" and runs:
            target_run = runs[-1]
        else:
            for r in runs:
                if r.get("run_id") == rollback_id:
                    target_run = r
                    break

        if not target_run:
            raise CommandError(f"Import run '{rollback_id}' not found in runs log.")

        self.stdout.write(
            self.style.WARNING(f"[*] Rolling back import run: {target_run['run_id']} ({target_run['timestamp']})")
        )

        image_ids = target_run.get("created_image_ids", [])
        folder_ids = target_run.get("created_folder_ids", [])

        # Delete images
        deleted_images = 0
        for img_id in image_ids:
            try:
                img = PatternDesignImage.objects.get(id=img_id)
                # Delete storage file
                if img.image:
                    img.image.delete(save=False)
                img.delete()
                deleted_images += 1
            except PatternDesignImage.DoesNotExist:
                pass

        # Delete empty folders created by this run
        deleted_folders = 0
        for f_id in folder_ids:
            try:
                folder = PatternDesignFolder.objects.get(id=f_id)
                if folder.images.count() == 0:
                    folder.delete()
                    deleted_folders += 1
            except PatternDesignFolder.DoesNotExist:
                pass

        # Remove run from log
        runs = [r for r in runs if r.get("run_id") != target_run["run_id"]]
        with open(RUN_LOG_PATH, "w", encoding="utf-8") as f:
            json.dump(runs, f, ensure_ascii=False, indent=2)

        self.stdout.write(
            self.style.SUCCESS(
                f"[+] Rollback complete: Deleted {deleted_images} images and {deleted_folders} empty folders."
            )
        )
