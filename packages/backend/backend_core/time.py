from datetime import UTC, datetime


def utc_now() -> datetime:
    return datetime.now(UTC)


def naive_utc_now() -> datetime:
    return utc_now().replace(tzinfo=None)


def naive_utc(value: datetime) -> datetime:
    """Normalize an aware datetime to naive UTC; naive values are assumed to be UTC already."""
    if value.tzinfo is None:
        return value
    return value.astimezone(UTC).replace(tzinfo=None)


def aware_utc(value: datetime) -> datetime:
    """Normalize a datetime to aware UTC; naive values are assumed to be UTC already."""
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)
