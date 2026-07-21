"""
Normalizes SIRI timestamps to consistent, timezone-aware datetimes.
SIRI-SM timestamps are ISO 8601 — but we treat the offset in the string
as authoritative rather than assuming Israel local time, since the ICD
should confirm this. Verify against a real response before trusting blindly.
"""
from datetime import datetime, timezone
from typing import Optional


def parse_siri_timestamp(raw: Optional[str]) -> Optional[datetime]:
    """
    Parses an ISO 8601 SIRI timestamp string into a timezone-aware UTC datetime.
    Returns None if input is None or unparseable.
    """
    if not raw:
        return None

    try:
        dt = datetime.fromisoformat(raw)
    except ValueError:
        return None

    if dt.tzinfo is None:
        # No offset in the string — flag rather than silently assume.
        # Adjust this once the ICD confirms the source timezone.
        raise ValueError(
            f"SIRI timestamp '{raw}' has no timezone offset — "
            "confirm assumed timezone against the ICD before proceeding."
        )

    return dt.astimezone(timezone.utc)


def minutes_until(target: Optional[datetime], now: Optional[datetime] = None) -> Optional[float]:
    """Minutes from now until target datetime. None if target is None."""
    if target is None:
        return None
    now = now or datetime.now(timezone.utc)
    return (target - now).total_seconds() / 60.0