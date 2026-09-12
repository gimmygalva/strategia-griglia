#!/usr/bin/env python3
"""Mount/copy/open/reopen the actual Mac package. Never report success on Linux."""

from __future__ import annotations

import argparse
import json
import os
import platform
import plistlib
import signal
import sqlite3
import subprocess
import tempfile
import time
from pathlib import Path
from typing import Any

if __package__:
    from .verify_frozen_backend import find_database
else:
    from verify_frozen_backend import find_database


def wait_marker(
    data_dir: Path, process: subprocess.Popen[bytes], generation: int = 1
) -> dict[str, Any]:
    deadline = time.monotonic() + 75
    marker = data_dir / "desktop-status.json"
    while time.monotonic() < deadline:
        if process.poll() is not None:
            raise RuntimeError("macOS application exited before UI/backend readiness")
        if marker.is_file():
            try:
                state = json.loads(marker.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                state = {}
            if state.get("error"):
                raise RuntimeError(f"macOS application startup error: {state['error']}")
            if (
                state.get("app_pid") == process.pid
                and state.get("ready")
                and state.get("frontend_ready")
                and state.get("generation", 0) >= generation
            ):
                if "token" in state or "secret" in state:
                    raise RuntimeError("Desktop QA marker leaked a credential")
                return state
        time.sleep(0.2)
    raise RuntimeError("macOS frontend/backend readiness timed out")


def pid_exists(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    return True


def close_window(data_dir: Path, process: subprocess.Popen[bytes], child_pid: int) -> None:
    (data_dir / "qa-request-close").write_text("close", encoding="utf-8")
    try:
        process.wait(timeout=30)
    except subprocess.TimeoutExpired:
        raise RuntimeError("Window close did not complete safe shutdown") from None
    if process.returncode != 0:
        raise RuntimeError(f"Desktop exit code: {process.returncode}")
    if pid_exists(child_pid):
        raise RuntimeError("Window close left an orphan backend process")


def verify(dmg: Path, root: Path) -> list[str]:
    checks: list[str] = []
    mount = root / "mount"
    mount.mkdir()
    subprocess.run(["hdiutil", "verify", str(dmg)], check=True, capture_output=True)
    subprocess.run(
        ["hdiutil", "attach", str(dmg), "-nobrowse", "-readonly", "-mountpoint", str(mount)],
        check=True,
        capture_output=True,
    )
    try:
        source = mount / "Grid Hedge Bot.app"
        if not source.is_dir() or not (mount / "Applications").exists():
            raise RuntimeError("DMG is missing its application/Applications drag-drop link")
        copied = root / "Installed" / "Grid Hedge Bot.app"
        copied.parent.mkdir()
        subprocess.run(["ditto", str(source), str(copied)], check=True)
        subprocess.run(
            ["codesign", "--verify", "--deep", "--strict", str(copied)],
            check=True,
            capture_output=True,
        )
        checks.append(
            "DMG verified, mounted, Applications link present, application copied, signature structure verified"
        )
    finally:
        subprocess.run(["hdiutil", "detach", str(mount)], check=True, capture_output=True)
    with (copied / "Contents" / "Info.plist").open("rb") as stream:
        info = plistlib.load(stream)
    executable = copied / "Contents" / "MacOS" / info["CFBundleExecutable"]
    sidecar = copied / "Contents" / "MacOS" / "gridbot-backend"
    if not executable.is_file() or not sidecar.is_file():
        raise RuntimeError("Application executable or frozen backend was not bundled")
    data_dir = root / "clean-user-data"
    data_dir.mkdir(mode=0o700)
    environment = {
        "PATH": "/usr/bin:/bin:/usr/sbin:/sbin",
        "HOME": os.environ["HOME"],
        "LANG": "en_US.UTF-8",
        "ALLOW_MAINNET_TRADING": "false",
        "GRIDBOT_DATA_DIR": str(data_dir),
        "GRIDBOT_DESKTOP_QA": "1",
    }
    for run in (1, 2):
        process = subprocess.Popen(
            [str(executable)],
            cwd=root,
            env=environment,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        marker: dict[str, Any] = {}
        try:
            marker = wait_marker(data_dir, process)
            if marker.get("bot_status") == "RUNNING" or marker.get("mainnet_allowed") is not False:
                raise RuntimeError(
                    "Installed app auto-started trading or enabled Mainnet by default"
                )
            database = find_database(data_dir)
            with sqlite3.connect(database) as connection:
                if connection.execute("PRAGMA integrity_check").fetchone() != ("ok",):
                    raise RuntimeError("Installed app database integrity failed")
                required = {"configuration", "orders", "executions", "bot_sessions"}
                tables = {
                    row[0]
                    for row in connection.execute(
                        "SELECT name FROM sqlite_master WHERE type='table'"
                    )
                }
                if not required <= tables:
                    raise RuntimeError("Installed app fresh migrations failed")
                if run == 1:
                    connection.execute("CREATE TABLE qa_package_probe(value TEXT NOT NULL)")
                    connection.execute("INSERT INTO qa_package_probe VALUES ('upgrade-safe')")
                elif connection.execute("SELECT value FROM qa_package_probe").fetchone() != (
                    "upgrade-safe",
                ):
                    raise RuntimeError("Existing database was erased on reopening")
            if run == 2:
                initial_generation = marker["generation"]
                os.killpg(marker["backend_pid"], signal.SIGKILL)
                marker = wait_marker(data_dir, process, initial_generation + 1)
                if marker.get("bot_status") == "RUNNING":
                    raise RuntimeError("Backend crash resumed trading automatically")
                checks.append(
                    "Actual frozen backend killed; supervisor restarted; JS reacquired bootstrap; startup stays paused"
                )
            if data_dir.stat().st_mode & 0o077:
                raise RuntimeError("Installed app data directory permissions are not owner-only")
            close_window(data_dir, process, marker["backend_pid"])
            checks.append(
                f"installed app run {run}: actual native UI, authenticated backend, migrations, SQLite, permissions, window close without orphan process"
            )
        finally:
            if process.poll() is None:
                process.kill()
                process.wait(timeout=5)
                if marker.get("backend_pid") and pid_exists(marker["backend_pid"]):
                    os.killpg(marker["backend_pid"], signal.SIGKILL)
    checks.append(
        "Clean app uses no installed Python/Node/Docker; same database survives close/reopen"
    )
    return checks


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("dmg", type=Path)
    parser.add_argument("--report", type=Path, required=True)
    arguments = parser.parse_args()
    arguments.report.unlink(missing_ok=True)
    if platform.system() != "Darwin":
        raise SystemExit("NON VERIFICATO: mounting and opening a .dmg requires macOS")
    if not arguments.dmg.is_file():
        raise SystemExit("A generated real DMG is required")
    with tempfile.TemporaryDirectory(prefix="gridbot-package-qa-") as directory:
        checks = verify(arguments.dmg.resolve(), Path(directory))
    report = {
        "result": "PASS",
        "checks": checks,
        "timestamp_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "platform": platform.platform(),
        "architecture": platform.machine(),
        "limitations": [
            "Bybit Demo order/execution verification requires user-provided Demo credentials",
            "Gatekeeper download quarantine and notarization require signed release and external install",
        ],
    }
    arguments.report.parent.mkdir(parents=True, exist_ok=True)
    arguments.report.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
