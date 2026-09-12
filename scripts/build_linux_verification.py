#!/usr/bin/env python3
"""Build Linux runtime evidence, never a macOS deliverable or trading release."""

from __future__ import annotations

import platform
import shutil
import subprocess
import sys
from pathlib import Path


def main() -> None:
    if platform.system() != "Linux":
        raise SystemExit("This verification-only build is explicitly Linux")
    root = Path(__file__).resolve().parents[1]
    if not (root / "frontend" / "dist" / "index.html").is_file():
        raise SystemExit("Build the real frontend before freezing the runtime")
    output = root / "build" / "linux-verification"
    for directory in (output, root / "build" / "linux-pyinstaller", root / "build" / "linux-spec"):
        if directory.exists():
            shutil.rmtree(directory)
    report = root / "build" / "reports" / "linux-frozen-backend.json"
    report.unlink(missing_ok=True)
    command = [
        sys.executable,
        "-m",
        "PyInstaller",
        "--noconfirm",
        "--clean",
        "--onefile",
        "--name",
        "gridbot-backend-linux-verification",
        "--paths",
        str(root / "backend"),
        "--distpath",
        str(output),
        "--workpath",
        str(root / "build" / "linux-pyinstaller"),
        "--specpath",
        str(root / "build" / "linux-spec"),
        "--collect-submodules",
        "gridbot",
        "--collect-submodules",
        "uvicorn",
        "--collect-submodules",
        "websockets",
        "--collect-submodules",
        "sqlalchemy.dialects.sqlite",
        "--hidden-import",
        "aiosqlite",
        "--hidden-import",
        "greenlet",
        "--add-data",
        f"{root / 'frontend' / 'dist'}:frontend/dist",
        "--add-data",
        f"{root / 'backend' / 'gridbot' / 'migrations'}:gridbot/migrations",
        str(root / "backend" / "entrypoint.py"),
    ]
    subprocess.run(command, cwd=root, check=True)
    subprocess.run(
        [
            sys.executable,
            str(root / "scripts" / "verify_frozen_backend.py"),
            str(output / "gridbot-backend-linux-verification"),
            "--report",
            str(report),
        ],
        cwd=root,
        check=True,
    )
    print("Linux frozen runtime evidence only; macOS installer remains NON VERIFICATO")


if __name__ == "__main__":
    main()
