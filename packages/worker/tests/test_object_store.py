from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from threading import Barrier, Lock

import pytest

from runtime import object_store


def test_namespace_is_the_bucket() -> None:
    assert object_store.namespace_bucket("default") == "default"
    assert object_store.namespace_bucket("analytics") == "analytics"
    assert object_store.namespace_bucket("team_a") == "team_a"


def test_namespace_bucket_rejects_invalid_names() -> None:
    with pytest.raises(ValueError, match="not a valid bucket name"):
        object_store.namespace_bucket("Team_A")
    with pytest.raises(ValueError, match="not a valid bucket name"):
        object_store.namespace_bucket("ab")
    with pytest.raises(ValueError, match="not a valid bucket name"):
        object_store.namespace_bucket("_leading")


def test_object_store_url_is_namespace_bucket_plus_key() -> None:
    url = object_store.object_store_url("uploads", "file.csv", namespace="analytics")
    assert url == "s3://analytics/uploads/file.csv"


def test_managed_urls_are_namespace_bucket_product_roots() -> None:
    assert object_store.is_managed_object_store_url("s3://default/uploads/a.csv")
    assert object_store.is_managed_object_store_url("s3://analytics/clean/x")
    assert not object_store.is_managed_object_store_url("s3://default/other/a.csv")
    assert not object_store.is_managed_object_store_url("s3://NotValid/uploads/a.csv")


def test_presigned_put_uses_engine_visible_endpoint_and_signed_content_type(monkeypatch) -> None:
    generated: dict[str, object] = {}
    created: dict[str, object] = {}

    class Client:
        def generate_presigned_url(self, operation, *, Params, ExpiresIn):
            generated.update(operation=operation, params=Params, expires=ExpiresIn)
            return "http://host.docker.internal:9000/tenant/runtime-staging/result.parquet"

    def create_client(service_name, **options):
        created.update(service_name=service_name, **options)
        return Client()

    monkeypatch.setattr(object_store, "ensure_bucket_exists", lambda _bucket: None)
    monkeypatch.setattr(object_store.boto3, "client", create_client)

    url = object_store.presigned_put_url(
        "s3://tenant/runtime-staging/result.parquet",
        expires_seconds=3600,
        endpoint_url="http://host.docker.internal:9000",
        content_type="application/octet-stream",
    )

    assert url.startswith("http://host.docker.internal:9000/")
    assert created["endpoint_url"] == "http://host.docker.internal:9000"
    assert generated == {
        "operation": "put_object",
        "params": {
            "Bucket": "tenant",
            "Key": "runtime-staging/result.parquet",
            "ContentType": "application/octet-stream",
        },
        "expires": 3600,
    }


def test_bucket_readiness_does_not_serialize_different_buckets(monkeypatch) -> None:
    started = Barrier(2)
    state_lock = Lock()
    active = 0
    max_active = 0
    calls: list[str] = []

    class Client:
        def head_bucket(self, *, Bucket):
            nonlocal active, max_active
            with state_lock:
                active += 1
                max_active = max(max_active, active)
                calls.append(Bucket)
            try:
                started.wait(timeout=1)
            finally:
                with state_lock:
                    active -= 1

    client = Client()
    monkeypatch.setattr(object_store, "_client", lambda: client)
    object_store.reset_object_store_client()

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(object_store.ensure_bucket_exists, ("alpha", "bravo")))

    assert results == ["alpha", "bravo"]
    assert sorted(calls) == ["alpha", "bravo"]
    assert max_active == 2


def test_multipart_object_upload_streams_bounded_parts_and_commits(monkeypatch) -> None:
    calls: list[tuple[str, dict[str, object]]] = []

    class Client:
        def create_multipart_upload(self, **kwargs):
            calls.append(("create", kwargs))
            return {"UploadId": "upload-1"}

        def upload_part(self, **kwargs):
            calls.append(("part", kwargs))
            return {"ETag": f'"{kwargs["PartNumber"]}"'}

        def complete_multipart_upload(self, **kwargs):
            calls.append(("complete", kwargs))

    monkeypatch.setattr(object_store, "ensure_bucket_exists", lambda _bucket: None)
    monkeypatch.setattr(object_store, "_client", lambda: Client())
    monkeypatch.setattr(object_store, "_MULTIPART_PART_SIZE", 4)

    upload = object_store.MultipartObjectUpload("s3://analytics/uploads/data.csv", content_type="text/csv", max_bytes=6)
    upload.write(b"abcd")
    upload.write(b"ef")
    result = upload.commit()
    upload.abort()

    assert result == "s3://analytics/uploads/data.csv"
    assert [call[1]["Body"] for call in calls if call[0] == "part"] == [b"abcd", b"ef"]
    assert calls[-1] == (
        "complete",
        {
            "Bucket": "analytics",
            "Key": "uploads/data.csv",
            "UploadId": "upload-1",
            "MultipartUpload": {
                "Parts": [
                    {"PartNumber": 1, "ETag": '"1"'},
                    {"PartNumber": 2, "ETag": '"2"'},
                ]
            },
        },
    )


def test_multipart_object_upload_aborts_after_limit_exceeded(monkeypatch) -> None:
    calls: list[str] = []

    class Client:
        def create_multipart_upload(self, **_kwargs):
            return {"UploadId": "upload-1"}

        def abort_multipart_upload(self, **_kwargs):
            calls.append("abort")

    monkeypatch.setattr(object_store, "ensure_bucket_exists", lambda _bucket: None)
    monkeypatch.setattr(object_store, "_client", lambda: Client())
    upload = object_store.MultipartObjectUpload("s3://analytics/uploads/data.csv", content_type=None, max_bytes=3)

    with pytest.raises(ValueError, match="exceeds 3 byte limit"):
        upload.write(b"four")
    upload.abort()

    assert calls == ["abort"]
