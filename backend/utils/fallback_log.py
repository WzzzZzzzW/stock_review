"""Rate-limited logging for best-effort data-source fallbacks."""

from __future__ import annotations

import json
import logging
import threading
import time
from typing import Any


_LOGGER = logging.getLogger("stock_review.data_fallback")
_LOCK = threading.Lock()
_EVENTS: dict[tuple[str, str, str], tuple[float, int]] = {}
_MAX_EVENT_KEYS = 512


def report_data_fallback(
    source: str,
    operation: str,
    error: BaseException,
    *,
    context: dict[str, Any] | None = None,
    throttle_seconds: float = 60.0,
) -> bool:
    """Log a degraded data-source call without changing the caller's fallback.

    Returns True when a warning was emitted and False when a duplicate warning
    was suppressed inside the throttle window.
    """
    now = time.monotonic()
    key = (source, operation, type(error).__name__)
    with _LOCK:
        previous = _EVENTS.get(key)
        if previous and now - previous[0] < throttle_seconds:
            _EVENTS[key] = (previous[0], previous[1] + 1)
            return False

        suppressed = previous[1] if previous else 0
        if len(_EVENTS) >= _MAX_EVENT_KEYS and key not in _EVENTS:
            oldest = min(_EVENTS, key=lambda item: _EVENTS[item][0])
            _EVENTS.pop(oldest, None)
        _EVENTS[key] = (now, 0)

    context_text = json.dumps(
        context or {}, ensure_ascii=False, default=str, separators=(",", ":")
    )
    _LOGGER.warning(
        "data_fallback source=%s operation=%s error_type=%s error=%s "
        "suppressed=%s context=%s",
        source,
        operation,
        type(error).__name__,
        str(error),
        suppressed,
        context_text,
        exc_info=(type(error), error, error.__traceback__)
        if _LOGGER.isEnabledFor(logging.DEBUG)
        else None,
    )
    return True


def _reset_fallback_log_state() -> None:
    """Clear throttle state for deterministic tests."""
    with _LOCK:
        _EVENTS.clear()
