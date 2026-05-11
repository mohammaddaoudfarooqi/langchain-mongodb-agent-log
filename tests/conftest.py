"""Shared test fixtures.

The ``_clean_env`` autouse fixture strips environment variables that the
package keys off, so a developer's local ``.env`` cannot influence test
results.
"""
from __future__ import annotations

import os
from collections.abc import Iterator

import pytest

_ENV_KEYS_TO_CLEAR = (
    "VOYAGE_API_KEY",
    "ATLAS_URI",
)


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    for k in _ENV_KEYS_TO_CLEAR:
        monkeypatch.delenv(k, raising=False)
    # ``ATLAS_URI`` is intentionally also cleared by default; integration
    # tests opt back in by reading ``os.environ`` from a session-scoped
    # fixture defined in ``tests/integration/conftest.py``.
    yield


@pytest.fixture
def mongomock_db() -> object:
    import mongomock

    return mongomock.MongoClient()["agent_log_test"]


def _atlas_uri_set() -> bool:
    return bool(os.environ.get("ATLAS_URI"))


def skip_unless_atlas() -> None:
    if not _atlas_uri_set():
        pytest.skip("ATLAS_URI not set; integration test skipped")
