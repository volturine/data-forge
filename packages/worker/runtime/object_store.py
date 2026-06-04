from __future__ import annotations

from pathlib import Path
from threading import Lock
from urllib.parse import urlparse

import boto3  # type: ignore[import-untyped]
from botocore.config import Config as BotoConfig  # type: ignore[import-untyped]
from botocore.exceptions import ClientError  # type: ignore[import-untyped]

from runtime.config import settings

_S3_CLIENT = None
_S3_CLIENT_LOCK = Lock()
_BUCKET_READY = False
_BUCKET_READY_LOCK = Lock()


def is_object_store_url(value: str | None) -> bool:
    if not isinstance(value, str) or not value:
        return False
    return urlparse(value).scheme.lower() == "s3"


def parse_object_store_url(url: str) -> tuple[str, str]:
    parsed = urlparse(url)
    if parsed.scheme.lower() != "s3" or not parsed.netloc:
        raise ValueError(f"Object storage URL must be s3://bucket/key, got: {url}")
    return parsed.netloc, parsed.path.lstrip("/")


def object_store_bucket() -> str:
    return settings.object_store_bucket.strip()


def object_store_prefix() -> str:
    return settings.object_store_prefix.strip("/").strip()


def object_store_key(*parts: str) -> str:
    cleaned = [object_store_prefix(), *(part.strip("/") for part in parts if part and part.strip("/"))]
    return "/".join(part for part in cleaned if part)


def object_store_url(*parts: str, bucket: str | None = None) -> str:
    key = object_store_key(*parts)
    return f"s3://{bucket or object_store_bucket()}/{key}"


def join_object_store_url(base_url: str, *parts: str) -> str:
    bucket, key = parse_object_store_url(base_url)
    suffix = "/".join(part.strip("/") for part in parts if part and part.strip("/"))
    next_key = "/".join(part for part in [key.rstrip("/"), suffix] if part)
    return f"s3://{bucket}/{next_key}"


def object_store_storage_options() -> dict[str, object]:
    return {
        "s3.endpoint": settings.object_store_endpoint,
        "s3.access-key-id": settings.object_store_access_key,
        "s3.secret-access-key": settings.object_store_secret_key,
        "s3.region": settings.object_store_region,
        "s3.force-virtual-addressing": False,
        "py-io-impl": "pyiceberg.io.pyarrow.PyArrowFileIO",
    }


def _client():
    global _S3_CLIENT
    if _S3_CLIENT is not None:
        return _S3_CLIENT
    with _S3_CLIENT_LOCK:
        if _S3_CLIENT is None:
            _S3_CLIENT = boto3.client(
                "s3",
                endpoint_url=settings.object_store_endpoint,
                region_name=settings.object_store_region,
                aws_access_key_id=settings.object_store_access_key,
                aws_secret_access_key=settings.object_store_secret_key,
                config=BotoConfig(s3={"addressing_style": "path"}),
            )
        return _S3_CLIENT


def ensure_bucket_exists() -> None:
    global _BUCKET_READY
    if _BUCKET_READY:
        return
    with _BUCKET_READY_LOCK:
        if _BUCKET_READY:
            return
        client = _client()
        bucket = object_store_bucket()
        try:
            client.head_bucket(Bucket=bucket)
        except ClientError as exc:
            error = exc.response.get("Error", {}) if isinstance(exc.response, dict) else {}
            code = str(error.get("Code") or "")
            if code not in {"404", "NoSuchBucket", "NotFound"}:
                raise
            client.create_bucket(Bucket=bucket)
        _BUCKET_READY = True


def upload_bytes(data: bytes, target_url: str, *, content_type: str | None = None) -> str:
    ensure_bucket_exists()
    bucket, key = parse_object_store_url(target_url)
    kwargs: dict[str, object] = {"Bucket": bucket, "Key": key, "Body": data}
    if content_type is not None:
        kwargs["ContentType"] = content_type
    _client().put_object(**kwargs)
    return target_url


def download_file(source_url: str, target_path: Path) -> Path:
    bucket, key = parse_object_store_url(source_url)
    target_path.parent.mkdir(parents=True, exist_ok=True)
    _client().download_file(bucket, key, str(target_path))
    return target_path


def object_exists(source_url: str) -> bool:
    bucket, key = parse_object_store_url(source_url)
    try:
        _client().head_object(Bucket=bucket, Key=key)
    except ClientError as exc:
        error = exc.response.get("Error", {}) if isinstance(exc.response, dict) else {}
        code = str(error.get("Code") or "")
        if code in {"404", "NoSuchKey", "NotFound"}:
            return False
        raise
    return True


def list_metadata_files(base_url: str) -> list[str]:
    bucket, key = parse_object_store_url(base_url)
    prefix = key.rstrip("/")
    if prefix and not prefix.endswith("/metadata") and "/metadata/" not in prefix:
        prefix = prefix + "/metadata"
    prefix = prefix.rstrip("/") + "/"
    paginator = _client().get_paginator("list_objects_v2")
    results: list[str] = []
    for page in paginator.paginate(Bucket=bucket, Prefix=prefix):
        for item in page.get("Contents") or []:
            object_key = item.get("Key") if isinstance(item, dict) else None
            if not isinstance(object_key, str) or not object_key.endswith(".metadata.json"):
                continue
            results.append(f"s3://{bucket}/{object_key}")
    return sorted(results)
