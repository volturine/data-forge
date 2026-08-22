from __future__ import annotations

import re
from datetime import datetime
from pathlib import Path
from threading import Lock
from urllib.parse import urlparse

import boto3  # type: ignore[import-untyped]
from botocore.config import Config as BotoConfig  # type: ignore[import-untyped]
from botocore.exceptions import ClientError  # type: ignore[import-untyped]

from runtime.config import settings

_S3_CLIENT = None
_S3_CLIENT_LOCK = Lock()
_BUCKETS_READY: set[str] = set()
_BUCKETS_READY_LOCK = Lock()

# Namespace name == bucket name. No rewriting.
# Lowercase letters, digits, hyphens, underscores; start/end alphanumeric.
_NAMESPACE_BUCKET_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{1,61}[a-z0-9]$")

# Product key roots inside a namespace bucket. Managed deletes only apply here.
_MANAGED_KEY_ROOTS = frozenset(
    {
        "uploads",
        "clean",
        "exports",
        "runtime-artifacts",
        "runtime-staging",
        "health",
        "tests",
    }
)


def is_object_store_url(value: str | None) -> bool:
    if not isinstance(value, str) or not value:
        return False
    parsed = urlparse(value)
    return parsed.scheme.lower() == "s3" and bool(parsed.netloc) and bool(parsed.path.lstrip("/"))


def parse_object_store_url(url: str) -> tuple[str, str]:
    parsed = urlparse(url)
    if parsed.scheme.lower() != "s3" or not parsed.netloc or not parsed.path.lstrip("/"):
        raise ValueError(f"Object storage URL must be s3://bucket/key, got: {url}")
    return parsed.netloc, parsed.path.lstrip("/")


def is_valid_namespace_bucket_name(name: str) -> bool:
    """True when ``name`` is a legal S3 bucket name and a legal product namespace."""
    if not name or len(name) < 3 or len(name) > 63:
        return False
    if ".." in name or name.startswith("xn--"):
        return False
    return _NAMESPACE_BUCKET_RE.match(name) is not None


def namespace_bucket(namespace: str) -> str:
    """The namespace is the bucket. Identity only — no prefix or folding."""
    name = namespace.strip()
    if not is_valid_namespace_bucket_name(name):
        raise ValueError(
            f"Namespace {namespace!r} is not a valid bucket name. "
            "Use 3–63 lowercase letters, digits, hyphens, or underscores; "
            "must start and end with a letter or digit."
        )
    return name


def object_store_key(*parts: str) -> str:
    cleaned = [part.strip("/") for part in parts if part and part.strip("/")]
    return "/".join(cleaned)


def object_store_url(*parts: str, namespace: str | None = None, bucket: str | None = None) -> str:
    """Build ``s3://{namespace}/{parts...}`` — namespace is the bucket."""
    if bucket is not None:
        resolved_bucket = bucket.strip()
        if not resolved_bucket:
            raise ValueError("bucket must not be empty")
        if not is_valid_namespace_bucket_name(resolved_bucket):
            raise ValueError(f"Invalid bucket name: {bucket!r}")
    else:
        if namespace is None:
            from runtime.namespace import get_namespace

            resolved_namespace = get_namespace()
        else:
            from runtime.namespace import normalize_namespace

            resolved_namespace = normalize_namespace(namespace)
        resolved_bucket = namespace_bucket(resolved_namespace)
    key = object_store_key(*parts)
    if not key:
        raise ValueError("object store key must not be empty")
    return f"s3://{resolved_bucket}/{key}"


def join_object_store_url(base_url: str, *parts: str) -> str:
    bucket, key = parse_object_store_url(base_url)
    suffix = "/".join(part.strip("/") for part in parts if part and part.strip("/"))
    next_key = "/".join(part for part in [key.rstrip("/"), suffix] if part)
    return f"s3://{bucket}/{next_key}"


def is_managed_object_store_url(url: str) -> bool:
    """Managed product objects live in a namespace bucket under known key roots."""
    if not is_object_store_url(url):
        return False
    bucket, key = parse_object_store_url(url)
    if not is_valid_namespace_bucket_name(bucket):
        return False
    root = key.split("/", 1)[0]
    return root in _MANAGED_KEY_ROOTS


def object_store_storage_options() -> dict[str, object]:
    options: dict[str, object] = {
        "s3.endpoint": settings.object_store_endpoint,
        "s3.access-key-id": settings.object_store_access_key,
        "s3.secret-access-key": settings.object_store_secret_key,
        "s3.region": settings.object_store_region,
        "s3.force-virtual-addressing": False,
        "py-io-impl": "pyiceberg.io.pyarrow.PyArrowFileIO",
    }
    if settings.object_store_session_token:
        options["s3.session-token"] = settings.object_store_session_token
    return options


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
                aws_session_token=settings.object_store_session_token or None,
                config=BotoConfig(s3={"addressing_style": "path"}),
            )
        return _S3_CLIENT


def ensure_bucket_exists(bucket: str | None = None) -> str:
    """Ensure a namespace bucket exists. Defaults to the current namespace bucket."""
    if bucket is None:
        from runtime.namespace import get_namespace

        resolved = namespace_bucket(get_namespace())
    else:
        resolved = namespace_bucket(bucket.strip())
    if resolved in _BUCKETS_READY:
        return resolved
    with _BUCKETS_READY_LOCK:
        if resolved in _BUCKETS_READY:
            return resolved
        client = _client()
        try:
            client.head_bucket(Bucket=resolved)
        except ClientError as exc:
            error = exc.response.get("Error", {}) if isinstance(exc.response, dict) else {}
            code = str(error.get("Code") or "")
            if code not in {"404", "NoSuchBucket", "NotFound"}:
                raise
            client.create_bucket(Bucket=resolved)
        _BUCKETS_READY.add(resolved)
    return resolved


def probe_object_store(*, namespace: str | None = None) -> None:
    """Fail-fast connectivity check: create/head the namespace bucket."""
    from runtime.namespace import get_namespace, normalize_namespace

    resolved = normalize_namespace(namespace) if namespace is not None else get_namespace()
    ensure_bucket_exists(namespace_bucket(resolved))


def upload_bytes(data: bytes, target_url: str, *, content_type: str | None = None) -> str:
    bucket, key = parse_object_store_url(target_url)
    ensure_bucket_exists(bucket)
    kwargs: dict[str, object] = {"Bucket": bucket, "Key": key, "Body": data}
    if content_type is not None:
        kwargs["ContentType"] = content_type
    _client().put_object(**kwargs)
    return target_url


def presigned_put_url(
    target_url: str,
    *,
    expires_seconds: int,
    endpoint_url: str | None = None,
    content_type: str | None = None,
) -> str:
    bucket, key = parse_object_store_url(target_url)
    ensure_bucket_exists(bucket)
    client = _client()
    if endpoint_url is not None and endpoint_url.rstrip("/") != settings.object_store_endpoint.rstrip("/"):
        client = boto3.client(
            "s3",
            endpoint_url=endpoint_url,
            region_name=settings.object_store_region,
            aws_access_key_id=settings.object_store_access_key,
            aws_secret_access_key=settings.object_store_secret_key,
            aws_session_token=settings.object_store_session_token or None,
            config=BotoConfig(s3={"addressing_style": "path"}),
        )
    params = {"Bucket": bucket, "Key": key}
    if content_type is not None:
        params["ContentType"] = content_type
    return str(
        client.generate_presigned_url(
            "put_object",
            Params=params,
            ExpiresIn=expires_seconds,
        )
    )


def download_bytes(source_url: str) -> bytes:
    bucket, key = parse_object_store_url(source_url)
    response = _client().get_object(Bucket=bucket, Key=key)
    body = response["Body"]
    return body.read()


def download_file(source_url: str, target_path: Path) -> Path:
    bucket, key = parse_object_store_url(source_url)
    target_path.parent.mkdir(parents=True, exist_ok=True)
    _client().download_file(bucket, key, str(target_path))
    return target_path


def delete_object(source_url: str) -> None:
    bucket, key = parse_object_store_url(source_url)
    _client().delete_object(Bucket=bucket, Key=key)


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


def list_prefixes(prefix_url: str) -> list[str]:
    bucket, key = parse_object_store_url(prefix_url)
    prefix = key.rstrip("/")
    if prefix:
        prefix = prefix + "/"
    response = _client().list_objects_v2(Bucket=bucket, Prefix=prefix, Delimiter="/")
    prefixes = response.get("CommonPrefixes") or []
    names: list[str] = []
    for item in prefixes:
        value = item.get("Prefix") if isinstance(item, dict) else None
        if not isinstance(value, str):
            continue
        suffix = value[len(prefix) :].strip("/")
        if suffix:
            names.append(suffix)
    return sorted(names)


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


def prefix_last_modified(prefix_url: str) -> datetime | None:
    """Newest LastModified among all objects under prefix, or None if empty/missing."""
    bucket, key = parse_object_store_url(prefix_url)
    prefix = key.rstrip("/")
    if prefix:
        prefix = prefix + "/"
    paginator = _client().get_paginator("list_objects_v2")
    newest: datetime | None = None
    for page in paginator.paginate(Bucket=bucket, Prefix=prefix):
        for item in page.get("Contents") or []:
            modified = item.get("LastModified") if isinstance(item, dict) else None
            if isinstance(modified, datetime) and (newest is None or modified > newest):
                newest = modified
    return newest


def delete_prefix(prefix_url: str) -> None:
    bucket, key = parse_object_store_url(prefix_url)
    prefix = key.rstrip("/")
    if prefix:
        prefix = prefix + "/"
    paginator = _client().get_paginator("list_objects_v2")
    delete_batch: list[dict[str, str]] = []
    for page in paginator.paginate(Bucket=bucket, Prefix=prefix):
        for item in page.get("Contents") or []:
            object_key = item.get("Key") if isinstance(item, dict) else None
            if not isinstance(object_key, str):
                continue
            delete_batch.append({"Key": object_key})
            if len(delete_batch) == 1000:
                _client().delete_objects(Bucket=bucket, Delete={"Objects": delete_batch})
                delete_batch = []
    if delete_batch:
        _client().delete_objects(Bucket=bucket, Delete={"Objects": delete_batch})
