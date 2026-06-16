from __future__ import annotations

from urllib.parse import urlparse

from backend_core.config import settings


def is_object_store_url(value: str | None) -> bool:
    if not isinstance(value, str) or not value:
        return False
    return urlparse(value).scheme.lower() == 's3'


def parse_object_store_url(url: str) -> tuple[str, str]:
    parsed = urlparse(url)
    if parsed.scheme.lower() != 's3' or not parsed.netloc:
        raise ValueError(f'Object storage URL must be s3://bucket/key, got: {url}')
    return parsed.netloc, parsed.path.lstrip('/')


def object_store_bucket() -> str:
    return settings.object_store_bucket.strip()


def object_store_prefix() -> str:
    return settings.object_store_prefix.strip('/').strip()


def object_store_key(*parts: str) -> str:
    cleaned = [object_store_prefix(), *(part.strip('/') for part in parts if part and part.strip('/'))]
    return '/'.join(part for part in cleaned if part)


def object_store_url(*parts: str, bucket: str | None = None) -> str:
    key = object_store_key(*parts)
    return f's3://{bucket or object_store_bucket()}/{key}'


def join_object_store_url(base_url: str, *parts: str) -> str:
    bucket, key = parse_object_store_url(base_url)
    suffix = '/'.join(part.strip('/') for part in parts if part and part.strip('/'))
    next_key = '/'.join(part for part in [key.rstrip('/'), suffix] if part)
    return f's3://{bucket}/{next_key}'


def is_managed_object_store_url(url: str) -> bool:
    if not is_object_store_url(url):
        return False
    bucket, key = parse_object_store_url(url)
    if bucket != object_store_bucket():
        return False
    managed_prefix = object_store_prefix()
    return key == managed_prefix or key.startswith(managed_prefix + '/')
