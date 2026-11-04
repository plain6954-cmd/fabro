from django import template
from django.utils.html import format_html
from management.services.activity_permissions import granted
register = template.Library()

@register.simple_tag(takes_context=True)
def activity_any_attrs(context, *keys):
    value = ' '.join(keys)
    if any(granted(context['request'].user, key) for key in keys):
        return format_html('data-activity-any="{}"', value)
    return format_html('data-activity-any="{}" hidden aria-hidden="true" data-activity-denied="true"', value)

@register.simple_tag(takes_context=True)
def activity_attrs(context, key):
    if granted(context['request'].user, key):
        return format_html('data-activity="{}"', key)
    return format_html('data-activity="{}" hidden disabled aria-hidden="true" data-activity-denied="true" data-activity-disabled-by-gate="true"', key)


@register.simple_tag(takes_context=True)
def file_activity_attrs(context, image, action):
    from management.services.activity_permissions import scoped
    user = context['request'].user
    resource = 'reference' if image.is_reference else 'design'
    keys = [resource + '.' + action + '_all']
    if image.uploaded_by_id is not None and image.uploaded_by_id == user.pk:
        keys.append(resource + '.' + action + '_own')
    value = ' '.join(keys)
    if scoped(user, resource, action, image.uploaded_by_id):
        return format_html('data-activity-any="{}"', value)
    return format_html('data-activity-any="{}" hidden disabled data-activity-denied="true" data-activity-disabled-by-gate="true"', value)
