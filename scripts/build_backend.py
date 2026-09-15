#!/usr/bin/env python3
"""Build a genuine native frozen sidecar. A plan is never a packaged binary."""

from __future__ import annotations

import argparse
import json
import os
import platform
import shutil
import subprocess
import sys
from pathlib import Path


def native_target() -> str:
    machine = platform.machine().lower()
    if platform.system() == "Darwin":
        if machine in {"arm64", "aarch64"}:
            return "aarch64-apple-darwin"
        if machine == "x86_64":
            return "x86_64-apple-darwin"
    raise RuntimeError("The macOS backend must be frozen on the native macOS architecture")


def build_command(root: Path, target: str, signing_identity: str | None = None) -> list[str]:
    if target not in {"aarch64-apple-darwin", "x86_64-apple-darwin"}:
        raise ValueError("Only native macOS targets are supported for this package")
    output = root / "build" / "sidecar"
    command = [
        sys.executable,
        "-m",
        "PyInstaller",
        "--noconfirm",
        "--clean",
        "--onefile",
        "--name",
        "gridbot-backend",
        "--paths",
        str(root / "backend"),
        "--distpath",
        str(output),
        "--workpath",
        str(root / "build" / "pyinstaller"),
        "--specpath",
        str(root / "build" / "spec"),
        "--collect-submodules",
        "gridbot",
        "--collect-submodules",
        "sqlalchemy.dialects.sqlite",
        "--collect-submodules",
        "uvicorn",
        "--collect-submodules",
        "websockets",
        "--hidden-import",
        "aiosqlite",
        "--hidden-import",
        "greenlet",
        "--hidden-import",
        "uvicorn.logging",
        "--hidden-import",
        "uvicorn.loops.auto",
        "--hidden-import",
        "uvicorn.protocols.http.auto",
        "--hidden-import",
        "uvicorn.protocols.websockets.auto",
        "--hidden-import",
        "keyring.backends.macOS",
        "--add-data",
        f"{root / 'frontend' / 'dist'}:frontend/dist",
    ]
    for relative in ("backend/gridbot/migrations", "backend/migrations"):
        directory = root / relative
        if directory.is_dir():
            destination = "gridbot/migrations" if "gridbot" in relative else "migrations"
            command.extend(["--add-data", f"{directory}:{destination}"])
    if signing_identity:
        command.extend(
            [
                "--codesign-identity",
                signing_identity,
                "--osx-entitlements-file",
                str(root / "desktop" / "BackendEntitlements.plist"),
            ]
        )
    command.append(str(root / "backend" / "entrypoint.py"))
    return command


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--target", choices=["aarch64-apple-darwin", "x86_64-apple-darwin"])
    parser.add_argument(
        "--plan", action="store_true", help="Print a build plan only; produces no binary"
    )
    arguments = parser.parse_args()
    root = arguments.root.resolve()
    target = arguments.target or native_target()
    identity_value = os.environ.get("APPLE_SIGNING_IDENTITY", "").strip()
    identity = None if identity_value in {"", "-"} else identity_value
    command = build_command(root, target, identity)
    if arguments.plan:
        print(json.dumps({"status": "PLAN_ONLY", "target": target, "command": command}, indent=2))
        return
    if target != native_target():
        raise SystemExit("Cross-architecture Python freezing is not allowed; use a native runner")
    for path in (root / "backend" / "entrypoint.py", root / "frontend" / "dist" / "index.html"):
        if not path.is_file():
            raise SystemExit(f"Required build input is missing: {path}")
    subprocess.run(command, cwd=root, check=True)
    source = root / "build" / "sidecar" / "gridbot-backend"
    destination = root / "desktop" / "binaries" / f"gridbot-backend-{target}"
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, destination)
    destination.chmod(0o755)
    subprocess.run(["file", str(destination)], check=True)
    subprocess.run(
        [sys.executable, str(root / "scripts" / "verify_frozen_backend.py"), str(destination)],
        cwd=root,
        check=True,
    )
    print(f"Native frozen sidecar verified: {destination.name}")


if __name__ == "__main__":
    main()
