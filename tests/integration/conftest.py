"""Integration-tier fixtures.

Atlas-gated tests skip cleanly when ``ATLAS_URI`` is unset so
``uv run pytest -m integration`` is a no-op without live infra.
"""
from __future__ import annotations

import os

import pytest


@pytest.fixture(scope="session")
def atlas_uri() -> str:
    uri = os.environ.get("ATLAS_URI")
    if not uri:
        pytest.skip("ATLAS_URI not set; integration test skipped")
    return uri
