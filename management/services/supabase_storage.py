import json
import mimetypes
from urllib.error import HTTPError, URLError
from urllib.parse import quote
from urllib.request import Request, urlopen

from django.conf import settings


class SupabaseStorageError(RuntimeError):
    pass


def _storage_url(path):
    return f'{settings.SUPABASE_URL}/storage/v1/{path.lstrip("/")}'


def _request(method, path, *, body=None, content_type='application/json'):
    headers = {
        'apikey': settings.SUPABASE_SERVICE_ROLE_KEY,
        'Authorization': f'Bearer {settings.SUPABASE_SERVICE_ROLE_KEY}',
    }
    if content_type:
        headers['Content-Type'] = content_type
    payload = body
    if isinstance(body, (dict, list)):
        payload = json.dumps(body).encode('utf-8')
    request = Request(_storage_url(path), data=payload, headers=headers, method=method)
    try:
        with urlopen(
            request,
            timeout=settings.SUPABASE_STORAGE_HTTP_TIMEOUT_SECONDS,
        ) as response:
            response_body = response.read()
            return json.loads(response_body) if response_body else {}
    except HTTPError as exc:
        error_body = exc.read().decode('utf-8', errors='replace')
        raise SupabaseStorageError(
            f'Supabase Storage returned HTTP {exc.code}: {error_body[:500]}'
        ) from exc
    except (URLError, TimeoutError, OSError) as exc:
        raise SupabaseStorageError(f'Supabase Storage is unavailable: {exc}') from exc


def create_signed_upload_url(storage_path):
    encoded_path = quote(storage_path, safe='/')
    data = _request(
        'POST',
        f'object/upload/sign/{quote(settings.SUPABASE_STORAGE_BUCKET, safe="")}/{encoded_path}',
        body={},
    )
    relative_url = data.get('url') or data.get('signedURL') or data.get('signedUrl')
    if not relative_url:
        raise SupabaseStorageError('Supabase Storage did not return a signed upload URL.')
    if relative_url.startswith(('https://', 'http://')):
        return relative_url
    return f'{settings.SUPABASE_URL}/storage/v1/{relative_url.lstrip("/")}'


def get_object_info(storage_path):
    encoded_path = quote(storage_path, safe='/')
    return _request(
        'GET',
        f'object/info/{quote(settings.SUPABASE_STORAGE_BUCKET, safe="")}/{encoded_path}',
        content_type=None,
    )


def create_signed_download_url(storage_path, expires_in=None):
    encoded_path = quote(storage_path, safe='/')
    data = _request(
        'POST',
        f'object/sign/{quote(settings.SUPABASE_STORAGE_BUCKET, safe="")}/{encoded_path}',
        body={'expiresIn': expires_in or settings.SUPABASE_SIGNED_DOWNLOAD_TTL_SECONDS},
    )
    relative_url = data.get('signedURL') or data.get('signedUrl')
    if not relative_url:
        raise SupabaseStorageError('Supabase Storage did not return a signed download URL.')
    if relative_url.startswith(('https://', 'http://')):
        return relative_url
    return f'{settings.SUPABASE_URL}/storage/v1/{relative_url.lstrip("/")}'


def delete_objects(storage_paths):
    paths = list(dict.fromkeys(path for path in storage_paths if path))
    if not paths:
        return
    _request(
        'DELETE',
        f'object/{quote(settings.SUPABASE_STORAGE_BUCKET, safe="")}',
        body={'prefixes': paths},
    )


def upload_content(storage_path, content, content_type=None):
    encoded_path = quote(storage_path, safe='/')
    guessed_type = content_type or mimetypes.guess_type(storage_path)[0] or 'application/octet-stream'
    return _request(
        'POST',
        f'object/{quote(settings.SUPABASE_STORAGE_BUCKET, safe="")}/{encoded_path}',
        body=content,
        content_type=guessed_type,
    )
