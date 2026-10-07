import zoneinfo
from datetime import datetime, timezone as dt_tz

COMMON_TIMEZONES = [
    ('Asia/Kolkata', 'India Standard Time (IST, UTC+05:30)'),
    ('Asia/Dubai', 'Gulf Standard Time (GST, UTC+04:00)'),
    ('Asia/Riyadh', 'Arabia Standard Time (AST, UTC+03:00)'),
    ('UTC', 'Coordinated Universal Time (UTC+00:00)'),
    ('Europe/London', 'London / United Kingdom (GMT/BST, UTC+00:00 / +01:00)'),
    ('Europe/Berlin', 'Central European Time - Berlin/Paris/Rome (CET/CEST, UTC+01:00 / +02:00)'),
    ('America/New_York', 'Eastern Time - US & Canada (EST/EDT, UTC-05:00 / -04:00)'),
    ('America/Chicago', 'Central Time - US & Canada (CST/CDT, UTC-06:00 / -05:00)'),
    ('America/Denver', 'Mountain Time - US & Canada (MST/MDT, UTC-07:00 / -06:00)'),
    ('America/Los_Angeles', 'Pacific Time - US & Canada (PST/PDT, UTC-08:00 / -07:00)'),
    ('Asia/Singapore', 'Singapore / Malaysia (SGT, UTC+08:00)'),
    ('Asia/Shanghai', 'China Standard Time (CST, UTC+08:00)'),
    ('Asia/Tokyo', 'Japan Standard Time (JST, UTC+09:00)'),
    ('Australia/Sydney', 'Australian Eastern Time - Sydney (AEST/AEDT, UTC+10:00 / +11:00)'),
]

COMMON_TZ_KEYS = {tz[0] for tz in COMMON_TIMEZONES}


def is_valid_timezone(tz_name: str) -> bool:
    if not tz_name or not isinstance(tz_name, str):
        return False
    try:
        zoneinfo.ZoneInfo(tz_name.strip())
        return True
    except Exception:
        return False


def get_all_timezones():
    """
    Returns a sorted list of (tz_name, display_label) tuples.
    Common timezones are prioritized, followed by all remaining standard IANA timezones.
    """
    result = list(COMMON_TIMEZONES)
    
    # Collect all other valid standard timezones
    try:
        all_zones = sorted(zoneinfo.available_timezones())
    except Exception:
        all_zones = []

    for z in all_zones:
        # Skip deprecated or non-standard zone names
        if z in COMMON_TZ_KEYS or '/' not in z or z.startswith('SystemV/') or z.startswith('Etc/'):
            continue
        result.append((z, z))

    return result
