from datetime import UTC, datetime, timedelta
from unittest.mock import patch

from runtime.compute_service import prune_superseded_revisions


def _make_objects(*ages_seconds: int, now: datetime):
    return [now - timedelta(seconds=a) for a in ages_seconds]


def test_prunes_only_aged_non_kept_revisions() -> None:
    now = datetime.now(UTC)
    aged = _make_objects(7200, now=now)
    fresh = _make_objects(60, now=now)

    def fake_list_prefixes(base: str) -> list[str]:
        return ["revision_0001", "revision_0002", "master"]

    seen: dict[str, datetime | None] = {}

    def fake_last_modified(url: str) -> datetime | None:
        seen[url] = aged[0] if url.endswith("revision_0001") else fresh[0]
        return seen[url]

    deleted: list[str] = []
    with (
        patch("runtime.compute_service.list_prefixes", side_effect=fake_list_prefixes),
        patch("runtime.compute_service.prefix_last_modified", side_effect=fake_last_modified),
        patch("runtime.compute_service.delete_prefix", side_effect=lambda url: deleted.append(url)),
    ):
        prune_superseded_revisions(
            "s3://bucket/exports/ds-1/master",
            keep_urls=frozenset({"s3://bucket/exports/ds-1/master/revision_0002"}),
            now=now,
        )

    assert deleted == ["s3://bucket/exports/ds-1/master/revision_0001"]


def test_keeps_everything_when_within_grace() -> None:
    now = datetime.now(UTC)
    with (
        patch("runtime.compute_service.list_prefixes", return_value=["revision_0001"]),
        patch("runtime.compute_service.prefix_last_modified", return_value=now - timedelta(seconds=10)),
        patch("runtime.compute_service.delete_prefix") as delete,
    ):
        prune_superseded_revisions("s3://bucket/exports/ds-1/master", now=now)
    delete.assert_not_called()


def test_listing_failure_is_swallowed() -> None:
    with (
        patch("runtime.compute_service.list_prefixes", side_effect=RuntimeError("store down")),
        patch("runtime.compute_service.delete_prefix") as delete,
    ):
        prune_superseded_revisions("s3://bucket/exports/ds-1/master")
    delete.assert_not_called()
