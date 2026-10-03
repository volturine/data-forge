"""Direct object-store connectivity probe for API readiness.

Namespace is the bucket. This probe does not use the worker data plane so the
API can become ready before workers register.
"""

from __future__ import annotations

import threading
import time

from backend_core.config import settings
from backend_core.namespace_storage import validate_namespace_name

# The probe performs network round trips; readiness is checked per request and
# by the container healthcheck, so results are cached briefly to keep the
# endpoint cheap under load.
_CACHE_TTL_SECONDS = 10.0

_cache_lock = threading.Lock()
_cached_bucket: str | None = None
_cached_at: float = 0.0
_client = None


def _get_client():
    global _client
    if _client is None:
        import boto3  # type: ignore[import-untyped]
        from botocore.config import Config as BotoConfig  # type: ignore[import-untyped]

        _client = boto3.client(
            's3',
            endpoint_url=settings.object_store_endpoint,
            region_name=settings.object_store_region,
            aws_access_key_id=settings.object_store_access_key,
            aws_secret_access_key=settings.object_store_secret_key,
            config=BotoConfig(s3={'addressing_style': 'path'}),
        )
    return _client


def probe_object_store(*, namespace: str | None = None) -> str:
    """Head-or-create the namespace bucket and write a tiny health object.

    Returns the bucket name on success. Raises on configuration or network failure.
    Successful results are cached briefly: repeated calls within the TTL do not
    touch the object store.
    """
    global _cached_bucket, _cached_at

    bucket = validate_namespace_name(namespace or settings.default_namespace)
    with _cache_lock:
        if _cached_bucket == bucket and time.monotonic() - _cached_at < _CACHE_TTL_SECONDS:
            return _cached_bucket

    from botocore.exceptions import ClientError  # type: ignore[import-untyped]

    client = _get_client()
    try:
        client.head_bucket(Bucket=bucket)
    except ClientError as exc:
        error = exc.response.get('Error', {}) if isinstance(exc.response, dict) else {}
        code = str(error.get('Code') or '')
        if code not in {'404', 'NoSuchBucket', 'NotFound'}:
            raise
        client.create_bucket(Bucket=bucket)
    client.put_object(Bucket=bucket, Key='health/ready', Body=b'ready', ContentType='text/plain')

    with _cache_lock:
        _cached_bucket = bucket
        _cached_at = time.monotonic()
    return bucket
