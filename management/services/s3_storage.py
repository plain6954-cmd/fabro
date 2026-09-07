import mimetypes
from django.conf import settings
import boto3
from botocore.config import Config
from botocore.exceptions import BotoCoreError, ClientError


class S3StorageError(RuntimeError):
    """Base exception for S3 / Garage object storage operations."""
    pass


# Backward compatibility alias
SupabaseStorageError = S3StorageError


def _get_client_config():
    addressing_style = getattr(settings, 'S3_ADDRESSING_STYLE', 'path')
    signature_version = getattr(settings, 'S3_SIGNATURE_VERSION', 's3v4')
    return Config(
        signature_version=signature_version,
        s3={'addressing_style': addressing_style},
        retries={'max_attempts': 3, 'mode': 'standard'},
    )


def get_s3_client(public=False):
    """Return a boto3 S3 client.

    When ``public=True``, uses ``settings.S3_PUBLIC_ENDPOINT_URL`` so presigned URLs
    contain the public host and signature expected by browsers. Otherwise uses
    ``settings.S3_ENDPOINT_URL`` for direct internal backend API calls.
    """
    endpoint_url = settings.S3_PUBLIC_ENDPOINT_URL if public else settings.S3_ENDPOINT_URL
    return boto3.client(
        's3',
        endpoint_url=endpoint_url,
        region_name=getattr(settings, 'S3_REGION', 'garage'),
        aws_access_key_id=getattr(settings, 'S3_ACCESS_KEY_ID', ''),
        aws_secret_access_key=getattr(settings, 'S3_SECRET_ACCESS_KEY', ''),
        config=_get_client_config(),
    )


def create_signed_upload_url(storage_path, content_type=None):
    """Generate a presigned PUT URL for browser-direct upload."""
    key = storage_path.lstrip('/')
    bucket = getattr(settings, 'S3_BUCKET_NAME', '')
    ttl = getattr(settings, 'S3_SIGNED_UPLOAD_TTL_SECONDS', 7200)
    params = {'Bucket': bucket, 'Key': key}
    if content_type:
        params['ContentType'] = content_type
    try:
        client = get_s3_client(public=True)
        return client.generate_presigned_url(
            ClientMethod='put_object',
            Params=params,
            ExpiresIn=ttl,
            HttpMethod='PUT',
        )
    except (BotoCoreError, ClientError) as exc:
        raise S3StorageError(f'Failed to create signed upload URL: {exc}') from exc


def create_signed_download_url(storage_path, expires_in=None):
    """Generate a presigned GET URL for browser downloads."""
    key = storage_path.lstrip('/')
    bucket = getattr(settings, 'S3_BUCKET_NAME', '')
    ttl = expires_in or getattr(settings, 'S3_SIGNED_DOWNLOAD_TTL_SECONDS', 300)
    try:
        client = get_s3_client(public=True)
        return client.generate_presigned_url(
            ClientMethod='get_object',
            Params={'Bucket': bucket, 'Key': key},
            ExpiresIn=ttl,
            HttpMethod='GET',
        )
    except (BotoCoreError, ClientError) as exc:
        raise S3StorageError(f'Failed to create signed download URL: {exc}') from exc


def get_object_info(storage_path):
    """Retrieve metadata for an object in S3/Garage, normalized for application code."""
    key = storage_path.lstrip('/')
    bucket = getattr(settings, 'S3_BUCKET_NAME', '')
    try:
        client = get_s3_client(public=False)
        response = client.head_object(Bucket=bucket, Key=key)
        return {
            'size': response.get('ContentLength', 0),
            'contentType': response.get('ContentType', ''),
            'content_type': response.get('ContentType', ''),
            'etag': response.get('ETag', ''),
            'last_modified': response.get('LastModified'),
            'metadata': response.get('Metadata', {}),
        }
    except ClientError as exc:
        code = str(exc.response.get('Error', {}).get('Code', ''))
        if code in ('404', 'NoSuchKey', 'NotFound'):
            raise S3StorageError(f'Object not found: {storage_path}') from exc
        raise S3StorageError(f'Object storage error getting info for {storage_path}: {exc}') from exc
    except (BotoCoreError, OSError) as exc:
        raise S3StorageError(f'Object storage is unavailable: {exc}') from exc


def delete_objects(storage_paths):
    """Delete one or more objects from S3/Garage."""
    paths = list(dict.fromkeys(path.lstrip('/') for path in storage_paths if path))
    if not paths:
        return
    bucket = getattr(settings, 'S3_BUCKET_NAME', '')
    try:
        client = get_s3_client(public=False)
        # S3 delete_objects takes up to 1000 keys per request
        chunk_size = 1000
        for i in range(0, len(paths), chunk_size):
            chunk = paths[i:i + chunk_size]
            delete_payload = {'Objects': [{'Key': p} for p in chunk], 'Quiet': True}
            response = client.delete_objects(Bucket=bucket, Delete=delete_payload)
            errors = response.get('Errors', [])
            if errors:
                first_err = errors[0]
                msg = f"{first_err.get('Key')}: {first_err.get('Code')} - {first_err.get('Message')}"
                raise S3StorageError(f'Failed to delete objects: {msg}')
    except ClientError as exc:
        raise S3StorageError(f'Object storage error deleting objects: {exc}') from exc
    except (BotoCoreError, OSError) as exc:
        raise S3StorageError(f'Object storage is unavailable: {exc}') from exc


def upload_content(storage_path, content, content_type=None):
    """Upload content directly to S3/Garage (for small files like ImageFields)."""
    key = storage_path.lstrip('/')
    bucket = getattr(settings, 'S3_BUCKET_NAME', '')
    guessed_type = content_type or mimetypes.guess_type(storage_path)[0] or 'application/octet-stream'
    try:
        client = get_s3_client(public=False)
        return client.put_object(
            Bucket=bucket,
            Key=key,
            Body=content,
            ContentType=guessed_type,
        )
    except ClientError as exc:
        raise S3StorageError(f'Object storage error uploading {storage_path}: {exc}') from exc
    except (BotoCoreError, OSError) as exc:
        raise S3StorageError(f'Object storage is unavailable: {exc}') from exc
