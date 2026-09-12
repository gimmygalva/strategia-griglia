from __future__ import annotations

import sys
from pathlib import Path

import pytest_asyncio

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))
sys.path.insert(0, str(ROOT / "tests"))

# Fixture import follows test-only path bootstrap.
from mock_bybit import LocalBybitServer  # noqa: E402


@pytest_asyncio.fixture
async def local_bybit_server():
    """Actual HTTP+WS local simulator. Never replaces official Bybit DEMO."""
    server = await LocalBybitServer().start()
    try:
        yield server
    finally:
        await server.stop()
