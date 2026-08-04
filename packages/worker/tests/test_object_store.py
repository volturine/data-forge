from __future__ import annotations

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
