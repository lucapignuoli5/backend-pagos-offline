from __future__ import annotations

from datetime import datetime, timezone
from typing import Callable


Clock = Callable[[], datetime]


def utc_now() -> datetime:
    """Single replaceable wall-clock source for application code."""
    return datetime.now(timezone.utc)
