"""Shared correlation-id derivation for the adapter layer.

The engine stays framework-agnostic and never generates ids; the adapters
(middleware / callback / node) resolve a correlation id from the runtime
``configurable`` and fall back to a fresh uuid4 string so every logged turn
carries a join key for cross-system tracing.
"""
from __future__ import annotations

import uuid
from collections.abc import Mapping
from typing import Any


def derive_correlation_id(configurable: Mapping[str, Any]) -> str:
    """Resolve a correlation id, generating one when none is supplied.

    Precedence:
    1. explicit ``configurable["correlation_id"]``
    2. the trace-id field of a W3C ``configurable["traceparent"]``
    3. ``configurable["x_request_id"]``
    4. a fresh ``uuid4`` string (matches the format servers commonly mint).
    """
    explicit = configurable.get("correlation_id")
    if explicit:
        return str(explicit)
    traceparent = configurable.get("traceparent")
    if isinstance(traceparent, str) and traceparent:
        # version "-" trace-id "-" parent-id "-" trace-flags
        parts = traceparent.split("-")
        if len(parts) >= 2 and parts[1]:
            return parts[1]
    xreq = configurable.get("x_request_id")
    if xreq:
        return str(xreq)
    return str(uuid.uuid4())
