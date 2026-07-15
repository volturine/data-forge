from datetime import UTC, datetime


def utc_now() -> datetime:
    return datetime.now(UTC)


def naive_utc_now() -> datetime:
    return utc_now().replace(tzinfo=None)
