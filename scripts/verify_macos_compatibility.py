#!/usr/bin/env python3
"""Reject a macOS bundle when any executable requires newer than Monterey."""

from __future__ import annotations

import argparse
import json
import platform
import plistlib
import re
import subprocess
import tempfile
import time
from pathlib import Path
from typing import Any

MONTEREY_TARGET = "12.0"
_VERSION = re.compile(r"^[0-9]+(?:\.[0-9]+){0,2}$")


def version_key(value: str) -> tuple[int, int, int]:
    if not _VERSION.fullmatch(value):
        raise ValueError(f"Invalid macOS version: {value!r}")
    parts = [int(part) for part in value.split(".")]
    return tuple((parts + [0, 0])[:3])  # type: ignore[return-value]


def parse_macho_minimum_versions(otool_output: str) -> list[str]:
    """Extract every architecture's minimum OS from ``otool -l`` output."""

    versions: list[str] = []
    command: str | None = None
    for raw_line in otool_output.splitlines():
        line = raw_line.strip()
        if line.startswith("cmd "):
            command = line.removeprefix("cmd ").strip()
            continue
        if command == "LC_BUILD_VERSION" and line.startswith("minos "):
            versions.append(line.split(maxsplit=1)[1])
            command = None
        elif command == "LC_VERSION_MIN_MACOSX" and line.startswith("version "):
            versions.append(line.split(maxsplit=1)[1])
            command = None
    return versions


def reject_newer_minimums(records: list[dict[str, Any]], target: str) -> None:
    target_key = version_key(target)
    for record in records:
        versions = record.get("minimum_system_versions", [])
        if not versions:
            raise RuntimeError(f"Mach-O has no readable minimum OS: {record['path']}")
        newer = [value for value in versions if version_key(value) > target_key]
        if newer:
            raise RuntimeError(
                f"Mach-O requires macOS {max(newer, key=version_key)}, newer than {target}: "
                f"{record['path']}"
            )


def _macho_records(app: Path) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for candidate in sorted(app.rglob("*")):
        if not candidate.is_file() or candidate.is_symlink():
            continue
        description = subprocess.run(
            ["file", "-b", str(candidate)],
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()
        if "Mach-O" not in description:
            continue
        commands = subprocess.run(
            ["otool", "-l", str(candidate)],
            check=True,
            capture_output=True,
            text=True,
        ).stdout
        records.append(
            {
                "path": str(candidate.relative_to(app)),
                "file_description": description,
                "minimum_system_versions": parse_macho_minimum_versions(commands),
            }
        )
    return records


def _onefile_macho_records(executable: Path) -> list[dict[str, Any]]:
    """Inspect Mach-O payloads compressed inside a PyInstaller one-file executable."""

    from PyInstaller.archive.readers import CArchiveReader

    archive = CArchiveReader(str(executable))
    binary_names = [
        name for name, entry in archive.toc.items() if entry[-1] == "b"
    ]
    if not binary_names:
        raise RuntimeError("PyInstaller backend archive contains no binary payloads")
    records: list[dict[str, Any]] = []
    with tempfile.TemporaryDirectory(prefix="gridbot-carchive-") as directory:
        root = Path(directory)
        for index, name in enumerate(binary_names):
            candidate = root / f"payload-{index:04d}"
            candidate.write_bytes(archive.extract(name))
            description = subprocess.run(
                ["file", "-b", str(candidate)],
                check=True,
                capture_output=True,
                text=True,
            ).stdout.strip()
            if "Mach-O" not in description:
                continue
            commands = subprocess.run(
                ["otool", "-l", str(candidate)],
                check=True,
                capture_output=True,
                text=True,
            ).stdout
            records.append(
                {
                    "path": f"{executable.relative_to(executable.parents[2])}::{name}",
                    "archive_entry": name,
                    "file_description": description,
                    "minimum_system_versions": parse_macho_minimum_versions(commands),
                    "container": "pyinstaller-carchive",
                }
            )
    if not records:
        raise RuntimeError("No Mach-O payloads were readable inside the PyInstaller backend")
    return records


def verify_app(app: Path, target: str = MONTEREY_TARGET) -> dict[str, Any]:
    app = app.resolve()
    info_path = app / "Contents" / "Info.plist"
    if not app.is_dir() or not info_path.is_file():
        raise RuntimeError(f"A complete .app bundle is required: {app}")
    with info_path.open("rb") as stream:
        info = plistlib.load(stream)
    declared = info.get("LSMinimumSystemVersion")
    if declared != target:
        raise RuntimeError(
            f"Bundle declares LSMinimumSystemVersion={declared!r}; expected {target!r}"
        )
    records = _macho_records(app)
    if not records:
        raise RuntimeError("No Mach-O executables were found in the application bundle")
    sidecar = app / "Contents" / "MacOS" / "gridbot-backend"
    if not sidecar.is_file():
        raise RuntimeError("Bundled PyInstaller backend is missing")
    embedded_records = _onefile_macho_records(sidecar)
    records.extend(embedded_records)
    reject_newer_minimums(records, target)
    observed = [value for record in records for value in record["minimum_system_versions"]]
    return {
        "result": "PASS",
        "target": target,
        "bundle_minimum_system_version": declared,
        "macho_binary_count": len(records),
        "pyinstaller_embedded_macho_count": len(embedded_records),
        "maximum_macho_minimum_system_version": max(observed, key=version_key),
        "macho_binaries": records,
        "checks": [
            f"Bundle declares macOS {target}",
            (
                f"All {len(records)} Mach-O executables, including "
                f"{len(embedded_records)} compressed PyInstaller payloads, "
                f"declare macOS {target} or older"
            ),
        ],
        "timestamp_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "build_platform": platform.platform(),
        "build_architecture": platform.machine(),
        "runtime_limit": (
            "The bundle was inspected and opened on the available build runner; "
            "execution on the user's physical macOS 12.6.8 remains an external acceptance test."
        ),
    }


def verify_and_write(app: Path, report: Path, target: str = MONTEREY_TARGET) -> dict[str, Any]:
    report.parent.mkdir(parents=True, exist_ok=True)
    try:
        result = verify_app(app, target)
    except (OSError, ValueError, RuntimeError, subprocess.SubprocessError) as error:
        report.write_text(
            json.dumps(
                {
                    "result": "FAIL",
                    "target": target,
                    "failure": str(error),
                    "timestamp_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                },
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )
        raise
    report.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    return result


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("app", type=Path)
    parser.add_argument("--target", default=MONTEREY_TARGET)
    parser.add_argument("--report", type=Path, required=True)
    arguments = parser.parse_args()
    if platform.system() != "Darwin":
        raise SystemExit("NON VERIFICATO: Mach-O compatibility inspection requires macOS")
    result = verify_and_write(arguments.app, arguments.report, arguments.target)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
