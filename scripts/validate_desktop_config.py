#!/usr/bin/env python3
"""Validate Tauri configuration against the actual pinned CLI JSON schema."""

from __future__ import annotations

import json
from pathlib import Path

import jsonschema


def validate(root: Path) -> None:
    schema_path = root / "desktop" / "node_modules" / "@tauri-apps" / "cli" / "config.schema.json"
    if not schema_path.is_file():
        raise RuntimeError("Install the pinned desktop CLI with npm --prefix desktop ci first")
    schema = json.loads(schema_path.read_text(encoding="utf-8"))
    config = json.loads((root / "desktop" / "tauri.conf.json").read_text(encoding="utf-8"))
    jsonschema.validate(config, schema)


if __name__ == "__main__":
    validate(Path(__file__).resolve().parents[1])
    print("Pinned Tauri configuration JSON schema: PASS")
