"""Single source of 'now' so tests can move time forward (lockout, session expiry)."""

from datetime import datetime, timezone


def now() -> datetime:
    return datetime.now(timezone.utc)
