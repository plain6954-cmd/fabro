import csv
import hashlib
import io
import json
import logging
import os
import re
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

import requests
from django.conf import settings
from django.core.files.base import ContentFile
from django.db import transaction

from management.models import Brand, Model, PatternDesignFolder, PatternDesignImage, SubModel, YearRange

logger = logging.getLogger(__name__)

# Supported image file extensions
SUPPORTED_IMAGE_EXTENSIONS = {'.jpg', '.jpeg', '.png', '.webp', '.gif'}
UNSUPPORTED_EXTENSIONS = {'.lnk', '.cut', '.pdf', '.pptx', '.zip', '.exe', '.doc', '.docx', '.xlsx'}

# Known brands canonical normalization
CANONICAL_BRANDS = {
    'kia': 'Kia',
    'mg': 'MG',
    'gmc': 'GMC',
    'gac': 'GAC',
    'chevrolet': 'Chevrolet',
    'dodge': 'Dodge',
    'ford': 'Ford',
    'honda': 'Honda',
    'hyundai': 'Hyundai',
    'isuzu': 'Isuzu',
    'jetour': 'Jetour',
    'lexus': 'Lexus',
    'mazda': 'Mazda',
    'mitsubishi': 'Mitsubishi',
    'nissan': 'Nissan',
    'suzuki': 'Suzuki',
    'toyota': 'Toyota',
}


class MatchClassification:
    EXACT = 'EXACT'
    PROBABLE = 'PROBABLE'
    AMBIGUOUS = 'AMBIGUOUS'
    CONFLICT = 'CONFLICT'
    UNMATCHED = 'UNMATCHED'
    UNSUPPORTED = 'UNSUPPORTED'
    DUPLICATE = 'DUPLICATE'


def strip_devanagari(text: str) -> str:
    """Remove Hindi / Devanagari unicode characters."""
    if not text:
        return ''
    # Devanagari range: \u0900-\u097F
    cleaned = re.sub(r'[\u0900-\u097F]+', ' ', text)
    return collapse_whitespace(cleaned)


def collapse_whitespace(text: str) -> str:
    """Collapse repeated whitespace."""
    if not text:
        return ''
    text = re.sub(r'\s+', ' ', text)
    return text.strip()


def normalize_token(text: str) -> str:
    """Normalize text for case-insensitive comparison, treating spaces, hyphens and underscores consistently."""
    if not text:
        return ''
    cleaned = strip_devanagari(text).lower()
    cleaned = re.sub(r'[^a-z0-9]', ' ', cleaned)
    return collapse_whitespace(cleaned)


def canonical_brand_name(raw_brand: str) -> str:
    """Convert raw brand string into canonical display name."""
    clean = normalize_token(raw_brand)
    if clean in CANONICAL_BRANDS:
        return CANONICAL_BRANDS[clean]
    # Default title casing
    return raw_brand.strip().title()


def expand_short_year(year_int: int) -> int:
    """Expand a 2-digit year into a 4-digit year.
    Years < 50 are 2000s (e.g. 24 -> 2024, 05 -> 2005).
    Years >= 50 are 1900s (e.g. 98 -> 1998).
    """
    if year_int >= 1000:
        return year_int
    if year_int < 50:
        return 2000 + year_int
    return 1900 + year_int


def parse_year_range(text: str) -> Tuple[Optional[int], Optional[int]]:
    """Extract start and end year from string.
    Supports: 19-24, 2019-2024, 2020-25, 08-17, 98-14, 2025, 19_24.
    """
    if not text:
        return None, None

    # Try full range e.g. 2019-2024 or 19-24 or 2020-25 or 08-16
    m = re.search(r'(?<!\d)(19\d\d|20\d\d|\d{2})\s*[-–—_]\s*(19\d\d|20\d\d|\d{2})(?!\d)', text)
    if m:
        s_raw, e_raw = m.group(1), m.group(2)
        y_start = expand_short_year(int(s_raw))
        y_end = expand_short_year(int(e_raw))
        if y_start > y_end:
            # Handle reverse order or invalid range gracefully
            y_start, y_end = y_end, y_start
        return y_start, y_end

    # Try single 4-digit year
    m_single = re.search(r'(?<!\d)(19\d\d|20\d\d)(?!\d)', text)
    if m_single:
        y = int(m_single.group(1))
        return y, y

    return None, None


def parse_seat_count(text: str) -> Optional[int]:
    """Parse seat count such as 5S, 7S, 8S, 9S, 12S, 5 seats."""
    if not text:
        return None
    m = re.search(r'\b(\d{1,2})\s*S\b', text, re.IGNORECASE)
    if m:
        return int(m.group(1))
    m2 = re.search(r'\b(\d{1,2})\s*seats?\b', text, re.IGNORECASE)
    if m2:
        return int(m2.group(1))
    return None


def parse_door_count(text: str) -> Optional[int]:
    """Parse door count such as 3D, 4D, 5D, 4 doors, 4डी."""
    if not text:
        return None
    # Hindi door match e.g. 4डी
    m_h = re.search(r'(\d)\s*[\u0921][\u0940]', text)
    if m_h:
        return int(m_h.group(1))
    m = re.search(r'\b(\d)\s*D\b', text, re.IGNORECASE)
    if m:
        return int(m.group(1))
    m2 = re.search(r'\b(\d)\s*doors?\b', text, re.IGNORECASE)
    if m2:
        return int(m2.group(1))
    return None


def parse_codes(text: str) -> Dict[str, Any]:
    """Extract N-code, X-code, or variant string."""
    results = {}
    if not text:
        return results
    m_n = re.findall(r'\b(N\d+)\b', text, re.IGNORECASE)
    if m_n:
        results['n_code'] = m_n[0].upper()
    m_x = re.findall(r'\b(X\d+)\b', text, re.IGNORECASE)
    if m_x:
        results['x_code'] = m_x[0].upper()
    m_br = re.findall(r'\b(BR\d+)\b', text, re.IGNORECASE)
    if m_br:
        results['br_code'] = m_br[0].upper()

    # Find all variant/submodel tokens: BR1, BR2, N1, N2, VXR, GXR, SS, SB, etc.
    all_tokens = re.findall(r'\b(BR\d+|N\d+|VXR|GXR|SS|SB)\b', text, re.IGNORECASE)
    if all_tokens:
        # Deduplicate while preserving order
        seen = set()
        deduped = []
        for t in all_tokens:
            up = t.upper()
            if up not in seen:
                seen.add(up)
                deduped.append(up)
        results['submodel_tokens'] = deduped
        results['submodel_str'] = ' '.join(deduped)

    return results


@dataclass
class DriveItem:
    id: str
    name: str
    mime: str
    size: int
    path: str
    is_folder: bool = False


@dataclass
class VehicleAttributes:
    brand: str
    model: str
    year_start: Optional[int] = None
    year_end: Optional[int] = None
    sub_model: str = ''
    seats: Optional[int] = None
    doors: Optional[int] = None
    x_code: str = ''
    n_code: str = ''
    variant_code: str = ''
    design_folder_name: str = ''
    raw_path: str = ''
    raw_filename: str = ''
    drive_file_id: str = ''
    drive_mime: str = ''
    file_size: int = 0


@dataclass
class MatchResult:
    drive_path: str
    drive_file_name: str
    drive_file_id: str
    detected_brand: str
    detected_model: str
    detected_year_range: str
    detected_submodel: str
    detected_seats: Optional[int]
    detected_doors: Optional[int]
    detected_code: str
    candidate_id: Optional[int]
    candidate_description: str
    match_classification: str  # EXACT, PROBABLE, AMBIGUOUS, CONFLICT, UNMATCHED, UNSUPPORTED, DUPLICATE
    match_confidence: float
    conflict_reason: str
    proposed_design_folder: str
    already_exists: bool
    proposed_action: str
    raw_item: Optional[DriveItem] = None
    vehicle_record: Optional[YearRange] = None


def extract_vehicle_attributes_from_path(item: DriveItem) -> VehicleAttributes:
    """Infer vehicle information from the full relative path and filename."""
    path_clean = item.path.replace('\\', '/').strip('/')
    parts = path_clean.split('/')

    raw_filename = parts[-1] if parts else item.name
    folder_parts = parts[:-1] if len(parts) > 1 else []

    detected_brand = ''
    vehicle_folder_str = ''
    subfolder_str = ''

    if folder_parts:
        raw_brand_folder = folder_parts[0]
        detected_brand = strip_devanagari(raw_brand_folder)
        detected_brand = canonical_brand_name(detected_brand)

        if len(folder_parts) >= 2:
            # Check if folder_parts[1] is another brand (e.g. GMC / Honda / ...)
            potential_brand = canonical_brand_name(strip_devanagari(folder_parts[1]))
            if potential_brand.lower() in CANONICAL_BRANDS and potential_brand.lower() != detected_brand.lower():
                # Nested brand structure detected
                detected_brand = potential_brand
                vehicle_folder_str = folder_parts[2] if len(folder_parts) >= 3 else ''
                subfolder_str = '/'.join(folder_parts[3:]) if len(folder_parts) > 3 else ''
            else:
                vehicle_folder_str = folder_parts[1]
                subfolder_str = '/'.join(folder_parts[2:]) if len(folder_parts) > 2 else ''
        else:
            # Only brand folder, file is in brand root
            vehicle_folder_str = raw_filename

    # Also check if filename itself has info
    combined_str = f"{vehicle_folder_str} {subfolder_str} {raw_filename}"
    clean_combined = strip_devanagari(combined_str).replace('_', ' ')

    # Years
    y_start, y_end = parse_year_range(clean_combined)
    # Seats
    seats = parse_seat_count(clean_combined)
    # Doors
    doors = parse_door_count(clean_combined)
    # Codes
    codes = parse_codes(clean_combined)

    # Extract Model name from vehicle_folder_str
    # e.g. "Captiva कैप्टिवा 19-24 7S" -> clean: "Captiva 19-24 7S"
    clean_vf = (strip_devanagari(vehicle_folder_str) if vehicle_folder_str else strip_devanagari(raw_filename)).replace('_', ' ')
    # If the vehicle folder starts with the brand name (e.g. "Dodge Charger ..."), strip brand
    b_pattern = re.compile(rf'^{re.escape(detected_brand)}\s+', re.IGNORECASE)
    clean_vf = b_pattern.sub('', clean_vf).strip()

    # Remove year range, seats, doors, codes from clean_vf to isolate model
    clean_model = clean_vf
    # Remove year patterns
    clean_model = re.sub(r'(?<!\d)(19\d\d|20\d\d|\d{2})\s*[-–—_]\s*(19\d\d|20\d\d|\d{2})(?!\d)', '', clean_model)
    clean_model = re.sub(r'(?<!\d)(19\d\d|20\d\d)(?!\d)', '', clean_model)
    # Remove Hindi door/seat markers
    clean_model = re.sub(r'\d\s*[\u0921][\u0940]', '', clean_model)
    # Remove seats / doors
    clean_model = re.sub(r'\b\d{1,2}\s*[sSdD]\b', '', clean_model)
    # Remove codes and variant tokens
    clean_model = re.sub(r'\b(BR\d+|N\d+|VXR|GXR|SS|SB|X\d+)\b', '', clean_model, flags=re.IGNORECASE)
    # Remove version / noise markers like v0, v1, BW, etc.
    clean_model = re.sub(r'\b(v\d+|bw|rev\d*)\b', '', clean_model, flags=re.IGNORECASE)
    # Remove dates like 04-03-2025
    clean_model = re.sub(r'\b\d{2}[-_]\d{2}[-_]\d{2,4}\b', '', clean_model)
    # Remove punctuation
    clean_model = re.sub(r'[^a-zA-Z0-9\s-]', ' ', clean_model)
    clean_model = collapse_whitespace(clean_model)

    # Common spelling normalizations
    if clean_model.lower() == 'land crusier':
        clean_model = 'Land Cruiser'

    # Determine proposed design folder name
    # If there is a distinct subfolder (e.g. "Seats", "Front", "Interior"), use it
    # Otherwise use clean vehicle folder name
    design_folder_name = ''
    if subfolder_str:
        design_folder_name = strip_devanagari(subfolder_str).strip()
    elif vehicle_folder_str:
        design_folder_name = strip_devanagari(vehicle_folder_str).strip()
    else:
        design_folder_name = 'Design Images'

    # Clean up design_folder_name (limit length to 150)
    design_folder_name = design_folder_name[:150].strip()

    detected_sub = codes.get('submodel_str') or codes.get('n_code') or codes.get('br_code') or ''

    return VehicleAttributes(
        brand=detected_brand,
        model=clean_model,
        year_start=y_start,
        year_end=y_end,
        sub_model=detected_sub,
        seats=seats,
        doors=doors,
        x_code=codes.get('x_code', ''),
        n_code=codes.get('n_code', ''),
        variant_code=codes.get('br_code', ''),
        design_folder_name=design_folder_name,
        raw_path=item.path,
        raw_filename=raw_filename,
        drive_file_id=item.id,
        drive_mime=item.mime,
        file_size=item.size,
    )


class VehicleMatcher:
    """Matches extracted vehicle attributes against Pattern Master YearRange records."""

    def __init__(self, vehicles: Optional[List[YearRange]] = None):
        if vehicles is None:
            self.vehicles = list(
                YearRange.objects.select_related(
                    'sub_model__model__brand',
                    'vehicle_country',
                    'measurement_country',
                ).all()
            )
        else:
            self.vehicles = vehicles

        # Precompute existing images for duplicate detection
        self.existing_drive_ids: Set[str] = set()
        self.existing_titles_per_vehicle: Dict[int, Set[str]] = {}

        try:
            for pdi in PatternDesignImage.objects.select_related('folder').all():
                v_id = pdi.vehicle_id or (pdi.folder.vehicle_id if pdi.folder else None)
                if pdi.title:
                    m_drive = re.search(r'\[Drive:([^\]]+)\]', pdi.title)
                    if m_drive:
                        self.existing_drive_ids.add(m_drive.group(1).strip())
                    clean_t = re.sub(r'\[Drive:[^\]]+\]', '', pdi.title).strip()
                    if v_id:
                        self.existing_titles_per_vehicle.setdefault(v_id, set()).add(
                            normalize_token(clean_t)
                        )
                        self.existing_titles_per_vehicle[v_id].add(normalize_token(pdi.title))
        except Exception as e:
            logger.warning("Could not precompute existing design images: %s", e)

    def match(self, item: DriveItem, attr: VehicleAttributes) -> MatchResult:
        """Classify item according to priority:
        1. Brand
        2. Model
        3. Year range
        4. Submodel/variant
        5. X or N code
        6. Seat count
        7. Door count
        """
        ext = os.path.splitext(item.name)[1].lower()

        # Check unsupported format
        if ext not in SUPPORTED_IMAGE_EXTENSIONS:
            return MatchResult(
                drive_path=item.path,
                drive_file_name=item.name,
                drive_file_id=item.id,
                detected_brand=attr.brand,
                detected_model=attr.model,
                detected_year_range=f"{attr.year_start or ''}-{attr.year_end or ''}".strip('-'),
                detected_submodel=attr.sub_model,
                detected_seats=attr.seats,
                detected_doors=attr.doors,
                detected_code=attr.n_code or attr.x_code,
                candidate_id=None,
                candidate_description='Unsupported file type',
                match_classification='UNSUPPORTED',
                match_confidence=0.0,
                conflict_reason=f'File extension {ext} is not a supported image format',
                proposed_design_folder='',
                already_exists=False,
                proposed_action='Ignore (Unsupported file type)',
                raw_item=item,
            )

        norm_brand = normalize_token(attr.brand)
        norm_model = normalize_token(attr.model)

        if not norm_brand:
            return self._build_result(
                item, attr, None, 'UNMATCHED', 0.0,
                'Could not detect Brand from path', 'No action (Unmatched)'
            )

        # Step 1: Filter by Brand
        brand_candidates = []
        for yr in self.vehicles:
            b_name = yr.sub_model.model.brand.name if yr.sub_model and yr.sub_model.model else ''
            if normalize_token(b_name) == norm_brand:
                brand_candidates.append(yr)

        if not brand_candidates:
            return self._build_result(
                item, attr, None, 'UNMATCHED', 0.0,
                f"No Pattern Master vehicles for brand '{attr.brand}'",
                'No action (Unmatched brand)'
            )

        if not norm_model:
            return self._build_result(
                item, attr, None, 'UNMATCHED', 0.0,
                f"Could not detect vehicle Model under brand '{attr.brand}'",
                'No action (Unmatched model)'
            )

        # Step 2: Filter by Model
        model_candidates = []
        for yr in brand_candidates:
            m_name = yr.sub_model.model.name if yr.sub_model and yr.sub_model.model else ''
            norm_m_name = normalize_token(m_name)
            # Check exact model name or model name within clean string
            if norm_m_name == norm_model or norm_m_name in norm_model or norm_model in norm_m_name:
                model_candidates.append(yr)

        if not model_candidates:
            # Brand exists, but model does not match any known model for that brand
            return self._build_result(
                item, attr, None, 'UNMATCHED', 0.1,
                f"Model '{attr.model}' not found for brand '{attr.brand}'",
                'No action (Unmatched model)'
            )

        # Step 3: Filter by Year Range
        year_candidates = []
        year_conflicts = []
        for yr in model_candidates:
            # If detected year range matches
            if attr.year_start is not None and attr.year_end is not None:
                if yr.year_start == attr.year_start and yr.year_end == attr.year_end:
                    year_candidates.append(yr)
                elif yr.year_start is not None and yr.year_end is not None:
                    # Check overlap or close year
                    if (abs(yr.year_start - attr.year_start) <= 1) and (abs(yr.year_end - attr.year_end) <= 1):
                        year_candidates.append(yr)
                    else:
                        year_conflicts.append(yr)
                elif yr.year_start is None and yr.year_end is None:
                    # Vehicle has no year range specified in DB
                    year_candidates.append(yr)
            else:
                # No year detected in drive folder
                year_candidates.append(yr)

        if not year_candidates and year_conflicts:
            # Brand and model match, but years conflict
            c = year_conflicts[0]
            c_desc = f"{c.sub_model.model.brand.name} {c.sub_model.model.name} {c.year_start}-{c.year_end}"
            return self._build_result(
                item, attr, c, 'CONFLICT', 0.3,
                f"Year mismatch: detected {attr.year_start}-{attr.year_end}, DB vehicle is {c.year_start}-{c.year_end}",
                'No action (Year conflict)'
            )

        candidates = year_candidates if year_candidates else model_candidates

        # Step 4, 5, 6, 7: Submodel, Code, Seats, Doors
        scored_candidates: List[Tuple[float, YearRange, List[str]]] = []
        for yr in candidates:
            score = 1.0
            reasons = []

            # Submodel / Variant check
            yr_sub = normalize_token(yr.sub_model.name) if yr.sub_model and yr.sub_model.name else ''
            det_sub = normalize_token(attr.sub_model)
            if det_sub:
                det_tokens = set(det_sub.split())
                yr_tokens = set(yr_sub.split())
                if yr_sub and det_tokens == yr_tokens:
                    score += 0.5
                elif yr_sub and (det_tokens.issubset(yr_tokens) or yr_tokens.issubset(det_tokens)):
                    score += 0.3
                elif yr_sub and not (det_tokens & yr_tokens):
                    score -= 0.4
                    reasons.append(f"Submodel mismatch: '{attr.sub_model}' vs DB '{yr.sub_model.name}'")
            elif yr_sub:
                # Drive missing submodel, DB has it
                reasons.append(f"Drive missing submodel '{yr.sub_model.name}'")

            # N-code / X-code check
            det_n = (attr.n_code or '').upper()
            yr_x = (yr.x_code or '').upper()
            if det_n:
                if det_n in (yr.layout_code or '').upper() or det_n in yr_sub.upper():
                    score += 0.4
            if attr.x_code and yr_x:
                if attr.x_code in yr_x:
                    score += 0.4

            # Seats check
            if attr.seats is not None:
                if yr.number_of_seats is not None:
                    if yr.number_of_seats == attr.seats:
                        score += 0.3
                    else:
                        score -= 0.3
                        reasons.append(f"Seat count mismatch: detected {attr.seats}S vs DB {yr.number_of_seats}S")
                else:
                    reasons.append(f"DB missing seat count (detected {attr.seats}S)")
            elif yr.number_of_seats is not None:
                reasons.append(f"Drive missing seat count (DB has {yr.number_of_seats}S)")

            # Doors check
            if attr.doors is not None:
                if yr.number_of_doors is not None:
                    if yr.number_of_doors == attr.doors:
                        score += 0.2
                    else:
                        score -= 0.2
                        reasons.append(f"Door count mismatch: detected {attr.doors}D vs DB {yr.number_of_doors}D")

            scored_candidates.append((score, yr, reasons))

        # Sort candidates by score descending
        scored_candidates.sort(key=lambda x: x[0], reverse=True)

        if not scored_candidates:
            return self._build_result(
                item, attr, None, 'UNMATCHED', 0.0,
                'No matching vehicle found', 'No action (Unmatched)'
            )

        best_score, best_yr, reasons = scored_candidates[0]

        # Check if ambiguous (more than 1 candidate with top score)
        if len(scored_candidates) > 1 and abs(scored_candidates[0][0] - scored_candidates[1][0]) < 0.05:
            c1 = scored_candidates[0][1]
            c2 = scored_candidates[1][1]
            c1_str = f"ID {c1.id} ({c1.year_start}-{c1.year_end} {c1.sub_model.name or ''})"
            c2_str = f"ID {c2.id} ({c2.year_start}-{c2.year_end} {c2.sub_model.name or ''})"
            return self._build_result(
                item, attr, None, 'AMBIGUOUS', 0.5,
                f"Multiple candidate matches: {c1_str} and {c2_str}",
                'No action (Ambiguous match)'
            )

        # Check duplicate
        is_dup = False
        if item.id in self.existing_drive_ids:
            is_dup = True
        elif best_yr.id in self.existing_titles_per_vehicle:
            norm_title = normalize_token(item.name)
            if norm_title in self.existing_titles_per_vehicle[best_yr.id]:
                is_dup = True

        if is_dup:
            return self._build_result(
                item, attr, best_yr, 'DUPLICATE', 1.0,
                'Image already exists in Pattern Master',
                'Skip (Duplicate)',
                already_exists=True
            )

        # Classification decision
        # EXACT: Brand, Model, Year agree and no conflict in secondary fields
        has_conflict = any('mismatch' in r for r in reasons)
        has_missing = any('missing' in r for r in reasons)

        if has_conflict:
            return self._build_result(
                item, attr, best_yr, 'CONFLICT', 0.4,
                '; '.join(reasons),
                'No action (Conflict)'
            )

        # If brand, model, and year range match perfectly
        year_matched = (
            attr.year_start is not None and attr.year_end is not None and
            best_yr.year_start == attr.year_start and best_yr.year_end == attr.year_end
        )

        if year_matched and not has_conflict and not has_missing:
            return self._build_result(
                item, attr, best_yr, 'EXACT', 1.0,
                '', 'Import to Pattern Master (Exact match)'
            )
        elif year_matched and has_missing:
            return self._build_result(
                item, attr, best_yr, 'PROBABLE', 0.85,
                '; '.join(reasons),
                'Requires manual mapping approval (Probable match)'
            )
        elif year_matched:
            return self._build_result(
                item, attr, best_yr, 'EXACT', 0.95,
                '', 'Import to Pattern Master (Exact match)'
            )
        else:
            return self._build_result(
                item, attr, best_yr, 'PROBABLE', 0.75,
                '; '.join(reasons) or 'Year range partially matched or missing',
                'Requires manual mapping approval (Probable match)'
            )

    def _build_result(
        self,
        item: DriveItem,
        attr: VehicleAttributes,
        yr: Optional[YearRange],
        classification: str,
        confidence: float,
        conflict_reason: str,
        proposed_action: str,
        already_exists: bool = False,
    ) -> MatchResult:
        desc = ''
        c_id = None
        if yr:
            c_id = yr.id
            b_name = yr.sub_model.model.brand.name if yr.sub_model and yr.sub_model.model else ''
            m_name = yr.sub_model.model.name if yr.sub_model and yr.sub_model.model else ''
            sub_name = yr.sub_model.name if yr.sub_model else ''
            years = f"{yr.year_start or ''}-{yr.year_end or ''}".strip('-')
            desc = f"ID {yr.id}: {b_name} {m_name} {years} {sub_name}".strip()

        return MatchResult(
            drive_path=item.path,
            drive_file_name=item.name,
            drive_file_id=item.id,
            detected_brand=attr.brand,
            detected_model=attr.model,
            detected_year_range=f"{attr.year_start or ''}-{attr.year_end or ''}".strip('-'),
            detected_submodel=attr.sub_model,
            detected_seats=attr.seats,
            detected_doors=attr.doors,
            detected_code=attr.n_code or attr.x_code,
            candidate_id=c_id,
            candidate_description=desc,
            match_classification=classification,
            match_confidence=confidence,
            conflict_reason=conflict_reason,
            proposed_design_folder=attr.design_folder_name,
            already_exists=already_exists,
            proposed_action=proposed_action,
            raw_item=item,
            vehicle_record=yr,
        )


class GoogleDriveClient:
    """Safe read-only Google Drive client that crawls folders and fetches files."""

    def __init__(self, api_key: Optional[str] = None):
        self.api_key = api_key or os.getenv('GOOGLE_API_KEY')
        self.session = requests.Session()
        self.session.headers.update({
            'User-Agent': (
                'Mozilla/5.0 (Windows NT 10.0; Win64; x64) '
                'AppleWebKit/537.36 (KHTML, like Gecko) '
                'Chrome/120.0.0.0 Safari/537.36'
            )
        })

    def extract_folder_id(self, url_or_id: str) -> str:
        """Extract Google Drive folder ID from URL or return raw ID."""
        if not url_or_id:
            return ''
        m = re.search(r'folders/([a-zA-Z0-9_-]+)', url_or_id)
        if m:
            return m.group(1)
        m_id = re.search(r'id=([a-zA-Z0-9_-]+)', url_or_id)
        if m_id:
            return m_id.group(1)
        return url_or_id.strip()

    def get_public_folder_items(self, folder_id: str) -> List[Dict[str, Any]]:
        """Scrape folder listing from public Google Drive folder page."""
        url = f'https://drive.google.com/drive/folders/{folder_id}'
        try:
            r = self.session.get(url, timeout=30)
            if r.status_code != 200:
                logger.error("Failed to load Drive folder %s: HTTP %d", folder_id, r.status_code)
                return []
        except Exception as e:
            logger.error("Exception fetching Drive folder %s: %s", folder_id, e)
            return []

        callbacks = re.findall(r'AF_initDataCallback\((.*?)\);</script>', r.text, re.DOTALL)
        for cb in callbacks:
            start = cb.find('data:') + 5
            end = cb.rfind(', sideChannel:')
            if start > 4 and end > start:
                try:
                    data = json.loads(cb[start:end].strip())

                    def find_item_list(node):
                        if isinstance(node, list):
                            if len(node) > 0 and all(
                                isinstance(x, list) and len(x) > 30 and
                                isinstance(x[0], list) and len(x[0]) > 1 and
                                isinstance(x[0][1], str) for x in node
                            ):
                                return node
                            for x in node:
                                res = find_item_list(x)
                                if res:
                                    return res
                        return None

                    items = find_item_list(data)
                    if items:
                        parsed = []
                        for it in items:
                            fid = it[0][1]
                            mime = it[4] if len(it) > 4 else ''
                            name = ''
                            if len(it) > 35 and isinstance(it[35], list) and it[35]:
                                if isinstance(it[35][0], list) and it[35][0]:
                                    if isinstance(it[35][0][0], list) and it[35][0][0]:
                                        name = it[35][0][0][0]
                            size = it[53][0] if len(it) > 53 and isinstance(it[53], list) and it[53] else 0
                            parsed.append({
                                'id': fid,
                                'mime': mime,
                                'name': name,
                                'size': size,
                                'is_folder': mime == 'application/vnd.google-apps.folder'
                            })
                        return parsed
                except Exception:
                    pass
        return []

    def crawl_all(
        self,
        root_folder_id: str,
        cache_file: Optional[str] = None,
        use_cache: bool = True
    ) -> Tuple[List[DriveItem], List[DriveItem]]:
        """Recursively crawl Google Drive folder, returning (folders, files)."""
        cache_path = Path(cache_file) if cache_file else None
        if use_cache and cache_path and cache_path.exists():
            try:
                with open(cache_path, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    folders = [DriveItem(**item) for item in data.get('folders', [])]
                    files = [DriveItem(**item) for item in data.get('files', [])]
                    logger.info("Loaded %d folders and %d files from cache %s", len(folders), len(files), cache_file)
                    return folders, files
            except Exception as e:
                logger.warning("Failed to read cache file %s: %s", cache_file, e)

        all_folders: List[DriveItem] = []
        all_files: List[DriveItem] = []

        def _traverse(folder_id: str, current_path: str):
            raw_items = self.get_public_folder_items(folder_id)
            for item in raw_items:
                item_path = f"{current_path}/{item['name']}".lstrip('/')
                drive_item = DriveItem(
                    id=item['id'],
                    name=item['name'],
                    mime=item['mime'],
                    size=item['size'],
                    path=item_path,
                    is_folder=item['is_folder']
                )
                if item['is_folder']:
                    all_folders.append(drive_item)
                    _traverse(item['id'], item_path)
                else:
                    all_files.append(drive_item)

        _traverse(root_folder_id, "")

        if cache_path:
            try:
                cache_path.parent.mkdir(parents=True, exist_ok=True)
                with open(cache_path, 'w', encoding='utf-8') as f:
                    json.dump({
                        'folders': [asdict(f) for f in all_folders],
                        'files': [asdict(f) for f in all_files]
                    }, f, ensure_ascii=False, indent=2)
            except Exception as e:
                logger.warning("Failed to write crawl cache: %s", e)

        return all_folders, all_files

    def download_file_bytes(self, file_id: str) -> Optional[bytes]:
        """Download file content by Google Drive file ID."""
        url = f"https://drive.google.com/uc?export=download&id={file_id}"
        try:
            r = self.session.get(url, timeout=45, stream=True)
            if r.status_code == 200:
                return r.content
            logger.error("Download failed for file ID %s: HTTP %d", file_id, r.status_code)
        except Exception as e:
            logger.error("Download exception for file ID %s: %s", file_id, e)
        return None
