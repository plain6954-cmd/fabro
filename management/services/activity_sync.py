"""Private, content-addressed access snapshots; no cross-request authorization cache."""
import hashlib
import json
from copy import copy
from urllib.parse import urlsplit
from django.http import QueryDict
from django.core.exceptions import PermissionDenied
from django.urls import resolve, Resolver404
from management.services.activity_permissions import REGISTRY, granted, identity, profile, require


def access_snapshot(user):
    permissions = {key: bool(granted(user, key)) for key in REGISTRY}
    person = profile(user)
    # Include business visibility identity as well as grants. Role defaults and
    # direct/group Django permission changes are detected without a write hook.
    info = identity(user)
    scope = [user.pk, info, getattr(person, 'country_id', None),
             getattr(person, 'can_receive_factory_assignments', False), permissions]
    role = getattr(user, '_activity_role_config', None)
    scope.append([role.pk, role.revision, role.name] if role else None)
    version = hashlib.sha256(json.dumps(scope, sort_keys=True).encode()).hexdigest()
    business = [user.pk, {key: info[key] for key in ('role', 'approval_role', 'is_staff', 'is_superuser')},
                getattr(person, 'country_id', None), getattr(person, 'can_receive_factory_assignments', False)]
    context_version = hashlib.sha256(json.dumps(business, sort_keys=True).encode()).hexdigest()
    return {'user_id': user.pk, 'version': version, 'context_version': context_version, 'permissions': permissions}


def page_allowed(request, path):
    if not path or not path.startswith('/') or path.startswith('//'):
        return False
    from management.services.activity_routes import request_keys
    try:
        destination = urlsplit(path)
        match = resolve(destination.path)
        check = copy(request)
        check.GET = QueryDict(destination.query)
        check.resolver_match, check.method = match, 'GET'
        # Only section-level feature requirements belong in this presentation
        # hint. Object checks remain in the real authorized data/action routes;
        # arbitrary page parameters must not become an object-existence oracle.
        require(request.user, *request_keys(check))
        return True
    except (PermissionDenied, Resolver404):
        return False
