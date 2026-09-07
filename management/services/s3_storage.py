import mimetypes

import boto3
from botocore.client import Config
from botocore.exceptions import BotoCoreError, ClientError
from django.conf import settings


class S3StorageError(RuntimeError):
    pass


def _client(endpoint_url):
    return boto3.client(
        "s3",
        endpoint_url=endpoint_url,
        aws_access_key_id=settings.S3_ACCESS_KEY,
        aws_secret_access_key=settings.S3_SECRET_KEY,
        region_name=settings.S3_REGION,
        config=Config(
            signature_version="s3v4",
            s3={"addressing_style": "path"},
            connect_timeout=10,
            read_timeout=30,
            retries={"max_attempts": 3, "mode": "standard"},
        ),
    )


def _internal_client():
    return _client(settings.S3_INTERNAL_ENDPOINT)


def _public_signing_client():
    return _client(settings.S3_PUBLIC_ENDPOINT)


def _raise_storage_error(action, exc):
    if isinstance(exc, ClientError):
        error = exc.response.get("Error", {})
        code = error.get("Code", "Unknown")
        message = error.get("Message", str(exc))
        raise S3StorageError(
            f"S3 {action} failed ({code}): {message}"
        ) from exc

    raise S3StorageError(f"S3 {action} failed: {exc}") from exc


def create_signed_upload_url(storage_path):
    try:
        return _public_signing_client().generate_presigned_url(
            "put_object",
            Params={
                "Bucket": settings.S3_BUCKET_NAME,
                "Key": storage_path,
            },
            ExpiresIn=settings.S3_SIGNED_UPLOAD_TTL_SECONDS,
            HttpMethod="PUT",
        )
    except (BotoCoreError, ClientError, ValueError) as exc:
        _raise_storage_error("signed upload URL generation", exc)


def create_signed_download_url(storage_path, expires_in=None):
    try:
        return _public_signing_client().generate_presigned_url(
            "get_object",
            Params={
                "Bucket": settings.S3_BUCKET_NAME,
                "Key": storage_path,
            },
            ExpiresIn=expires_in or settings.S3_SIGNED_DOWNLOAD_TTL_SECONDS,
            HttpMethod="GET",
        )
    except (BotoCoreError, ClientError, ValueError) as exc:
        _raise_storage_error("signed download URL generation", exc)


def get_object_info(storage_path):
    try:
        response = _internal_client().head_object(
            Bucket=settings.S3_BUCKET_NAME,
            Key=storage_path,
        )
    except (BotoCoreError, ClientError) as exc:
        _raise_storage_error("object lookup", exc)

    return {
        "size": response.get("ContentLength", 0),
        "contentType": response.get("ContentType"),
        "metadata": response.get("Metadata") or {},
        "etag": response.get("ETag"),
        "lastModified": response.get("LastModified"),
    }


def delete_objects(storage_paths):
    paths = list(dict.fromkeys(path for path in storage_paths if path))
    if not paths:
        return

    client = _internal_client()

    try:
        for start in range(0, len(paths), 1000):
            batch = paths[start:start + 1000]

            response = client.delete_objects(
                Bucket=settings.S3_BUCKET_NAME,
                Delete={
                    "Objects": [{"Key": path} for path in batch],
                    "Quiet": True,
                },
            )

            errors = response.get("Errors") or []
            if errors:
                first = errors[0]
                raise S3StorageError(
                    "S3 object deletion failed "
                    f"({first.get('Code', 'Unknown')}): "
                    f"{first.get('Message', 'Unknown error')}"
                )

    except S3StorageError:
        raise
    except (BotoCoreError, ClientError) as exc:
        _raise_storage_error("object deletion", exc)


def upload_content(storage_path, content, content_type=None):
    guessed_type = (
        content_type
        or mimetypes.guess_type(storage_path)[0]
        or "application/octet-stream"
    )

    try:
        _internal_client().put_object(
            Bucket=settings.S3_BUCKET_NAME,
            Key=storage_path,
            Body=content,
            ContentType=guessed_type,
        )
    except (BotoCoreError, ClientError) as exc:
        _raise_storage_error("object upload", exc)

    return {"path": storage_path}
