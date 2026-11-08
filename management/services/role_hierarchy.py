"""Canonical presentation/ancestor inventory for existing activity keys.

Shared services keep their existing identifiers and object authorization. Window
gates are separate only where a shared service cannot identify the entry window.
"""
from functools import lru_cache
from management.services.activity_permissions import REGISTRY


def node(key, label, icon, *, actions=(), children=()):
    return dict(key=key, label=label, icon=icon, actions=list(actions), children=list(children))


def category(name):
    return [key for key, item in REGISTRY.items() if item.category == name]


def tree():
    pattern = [key for key in category('pattern') if key not in ('pattern.view',) and not key.startswith('pattern.drive_')]
    return [
        node('dashboard', 'Dashboard', 'chart-pie', actions=category('dashboard')),
        node('patterns', 'Patterns', 'folder-open', actions=['pattern.view'], children=[
            node('patterns.master', 'Pattern Master', 'layer-group', actions=pattern+['vehicle.import','reports.pattern_history']),
            node('patterns.colors', 'Color Master', 'palette', actions=[key for key in category('color') if key in ('color.view','color.create','color.edit','color.delete')]),
            node('patterns.status', '3D Status', 'cube', actions=['design_status.view']),
            node('patterns.measurements', 'Measurements', 'ruler-combined', actions=category('measurement'), children=[
                node('patterns.measurements.colors', 'Color Selector & Picked Colors', 'swatchbook', actions=category('picked_colors')+[key for key in category('color') if key not in ('color.view','color.create','color.edit','color.delete')])]),
            node('patterns.design', '3D Design', 'cube', actions=category('design')+[key for key in category('pattern') if key.startswith('pattern.drive_')], children=[
                node('patterns.design.reference', 'Reference Images', 'images', actions=category('reference')),
                node('patterns.design.folders', 'Design Folders', 'folder', actions=category('folder')),
                node('patterns.design.review', 'Design Review', 'clipboard-check', actions=category('design_approval'))]),
        ]),
        node('vehicle', 'Vehicle Catalog', 'car', actions=[key for key in category('vehicle') if key!='vehicle.import']),
        node('sku', 'SKUs', 'box-open', actions=category('sku')),
        node('complaints', 'Complaints', 'list-alt', actions=category('complaint'), children=[
            node('complaints.execution', 'Factory Review & Execution', 'industry', actions=[key for key in category('workflow') if key not in ('workflow.view','workflow.approve','workflow.reject')])]),
        node('approvals', 'Approvals', 'clipboard-check', actions=category('approvals')+['workflow.view','workflow.approve','workflow.reject']),
        node('notifications', 'Notifications', 'bell', actions=category('notification')),
        node('chat', 'Internal Chat', 'comments', actions=category('chat')),
        node('admin', 'Admin Panel', 'cog', actions=['erp.view'], children=[
            node('admin.dashboard', 'Control Tower', 'chart-pie', actions=['erp.control_tower']),
            node('admin.users', 'Users', 'users', actions=category('users')),
            node('admin.roles', 'Roles', 'shield-alt', actions=category('roles')),
            node('admin.master', 'Master Settings', 'sliders-h', actions=category('master')),
            node('admin.sessions', 'Active Sessions', 'network-wired', actions=['erp.sessions_view','erp.sessions_terminate']),
            node('admin.logs', 'Activity Logs', 'history', actions=['reports.activity']),
        ]),
    ]


@lru_cache(maxsize=1)
def paths():
    result = {}
    def walk(items, ancestors=()):
        for item in items:
            lineage = ancestors+(item['key'],)
            for key in item['actions']:
                if key in result or key not in REGISTRY:
                    raise ValueError('Invalid or duplicate role activity: '+key)
                result[key] = lineage
            walk(item['children'], lineage)
    walk(tree())
    if set(result) != set(REGISTRY):
        raise ValueError('Missing role activities: '+str(set(REGISTRY)-set(result)))
    return result


def window_keys():
    return {key for lineage in paths().values() for key in lineage}


def ancestors_enabled(role, key):
    return role is None or all(role.windows.get(parent, bool(role.system_code)) for parent in paths()[key])
