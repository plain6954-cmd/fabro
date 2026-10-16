"""
Authoritative Global Color Service for FABRO Leather Portal.

Provides centralized querying, formatting, and selection helpers for
ColorMaster across all modules (complaints, catalogs, API, etc.).
"""

from typing import Optional, List, Dict, Any, Tuple
from django.db.models import Q, QuerySet
from management.models import ColorMaster


def get_active_master_colors() -> QuerySet[ColorMaster]:
    """
    Return all active master colors ordered by color code and ID.
    Used by default in all new selection dropdowns and pickers.
    """
    return ColorMaster.objects.filter(status='Active').order_by('color_code', 'id')


def get_master_colors_for_selection(
    include_archived: bool = False,
    include_color_id: Optional[int] = None,
    search_query: Optional[str] = None
) -> QuerySet[ColorMaster]:
    """
    Query master colors for selection dropdowns.
    If include_archived is False, only Active colors are returned,
    UNLESS include_color_id is provided (preserving historical selections
    when editing existing records whose color may have been archived).
    """
    qs = ColorMaster.objects.all()

    if not include_archived:
        if include_color_id:
            qs = qs.filter(Q(status='Active') | Q(id=include_color_id))
        else:
            qs = qs.filter(status='Active')

    if search_query:
        q = search_query.strip()
        qs = qs.filter(
            Q(name__icontains=q) |
            Q(color_code__icontains=q) |
            Q(hex_code__icontains=q) |
            Q(pantone_code__icontains=q) |
            Q(color_category__icontains=q) |
            Q(material_series__icontains=q)
        )

    return qs.order_by('color_code', 'id')


def get_master_color_choices(
    include_archived: bool = False,
    include_color_id: Optional[int] = None,
    empty_label: Optional[str] = "---------",
) -> List[Tuple[Any, str]]:
    """
    Generate choice tuples (id, display_label) suitable for Django forms or select fields.
    Includes the serial/internal code, name, and HEX representation.
    """
    choices: List[Tuple[Any, str]] = []
    if empty_label is not None:
        choices.append(('', empty_label))

    colors = get_master_colors_for_selection(
        include_archived=include_archived,
        include_color_id=include_color_id
    )

    for c in colors:
        label = f"#{c.color_code} {c.name} ({c.hex_code})"
        if c.status != 'Active':
            label += f" [{c.status}]"
        choices.append((c.id, label))

    return choices


def serialize_color_for_picker(color: ColorMaster) -> Dict[str, Any]:
    """
    Serialize a ColorMaster instance into a clean JSON-ready dictionary
    with all attributes necessary for interactive UI swatches and selectors.
    """
    return {
        'id': color.id,
        'name': color.name,
        'color_code': color.color_code,
        'hex_code': color.hex_code,
        'pantone_code': color.pantone_code or '',
        'rgb_code': color.rgb_code or '',
        'cmyk_code': color.cmyk_code or '',
        'color_category': color.color_category or '',
        'material_series': color.material_series or '',
        'compatible_models': color.compatible_models or '',
        'status': color.status,
        'display_label': f"#{color.color_code} {color.name} ({color.hex_code})"
    }
