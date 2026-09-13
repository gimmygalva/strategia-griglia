from __future__ import annotations

import pytest

from scripts.verify_macos_compatibility import (
    parse_macho_minimum_versions,
    reject_newer_minimums,
    version_key,
)


def test_version_key_normalizes_macos_versions() -> None:
    assert version_key("12") == (12, 0, 0)
    assert version_key("12.6.8") == (12, 6, 8)
    with pytest.raises(ValueError):
        version_key("12.beta")


def test_parses_modern_and_legacy_macho_minimum_commands() -> None:
    output = """
Load command 8
      cmd LC_BUILD_VERSION
  cmdsize 32
 platform 1
    minos 12.0
      sdk 15.5
Load command 9
      cmd LC_VERSION_MIN_MACOSX
  cmdsize 16
  version 10.13
      sdk 11.3
"""
    assert parse_macho_minimum_versions(output) == ["12.0", "10.13"]


def test_monterey_gate_accepts_older_or_equal_binaries() -> None:
    reject_newer_minimums(
        [
            {"path": "Contents/MacOS/app", "minimum_system_versions": ["12.0"]},
            {"path": "Contents/MacOS/backend", "minimum_system_versions": ["11.0"]},
        ],
        "12.0",
    )


def test_monterey_gate_rejects_ventura_binary_and_missing_metadata() -> None:
    with pytest.raises(RuntimeError, match="newer than 12.0"):
        reject_newer_minimums(
            [{"path": "Contents/MacOS/app", "minimum_system_versions": ["13.0"]}],
            "12.0",
        )
    with pytest.raises(RuntimeError, match="no readable minimum OS"):
        reject_newer_minimums(
            [{"path": "Contents/MacOS/backend", "minimum_system_versions": []}],
            "12.0",
        )
