"""UTC boundaries for scheduler, database and Jobs API timestamps."""
from datetime import datetime, timezone
from typing import Optional


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def as_utc(value: datetime) -> datetime:
    # Legacy naive database values follow the existing UTC convention. New
    # writes keep their offset; don't reinterpret historical values as local.
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def serialize_utc(value: Optional[datetime]) -> Optional[str]:
    return as_utc(value).isoformat().replace('+00:00', 'Z') if value else None
