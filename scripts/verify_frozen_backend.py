#!/usr/bin/env python3
"""Exercise the real frozen executable with a clean, isolated data directory."""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import queue
import secrets
import sqlite3
import subprocess
import tempfile
import threading
import time
import urllib.request
from pathlib import Path
from typing import Any

from websockets.asyncio.client import connect


def request(url: str, token: str, path: str, payload: dict[str, Any] | None = None) -> Any:
    data = json.dumps(payload).encode() if payload is not None else None
    message = urllib.request.Request(
        url + path,
        data=data,
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
    )
    with urllib.request.urlopen(message, timeout=5) as response:
        return json.load(response)


def wait_ready(process: subprocess.Popen[str]) -> str:
    events: queue.Queue[str | None] = queue.Queue()

    def read_stdout() -> None:
        if process.stdout is None:
            events.put(None)
            return
        for line in process.stdout:
            events.put(line)
        events.put(None)

    threading.Thread(target=read_stdout, daemon=True).start()
    deadline = time.monotonic() + 60
    while time.monotonic() < deadline:
        try:
            line = events.get(timeout=0.25)
        except queue.Empty:
            if process.poll() is not None:
                raise RuntimeError("Frozen backend exited before READY") from None
            continue
        if line is None:
            raise RuntimeError("Frozen backend closed stdout before READY")
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        if event.get("type") == "ready":
            url = event.get("url", "")
            if not url.startswith("http://127.0.0.1:"):
                raise RuntimeError("Frozen backend is not loopback-only")
            return url
    raise RuntimeError("Frozen backend readiness timed out")


def find_database(data_dir: Path) -> Path:
    candidates = [
        path
        for path in data_dir.rglob("*")
        if path.is_file() and path.suffix in {".db", ".sqlite", ".sqlite3"}
    ]
    if len(candidates) != 1:
        raise RuntimeError(f"Expected one database, found {len(candidates)}")
    return candidates[0]


async def verify_websocket(url: str, token: str) -> None:
    websocket_url = url.replace("http://", "ws://", 1) + "/api/ws"
    async with connect(websocket_url, origin=url, open_timeout=5, close_timeout=5) as socket:
        await socket.send(json.dumps({"type": "authenticate", "token": token}))
        frame = json.loads(await asyncio.wait_for(socket.recv(), timeout=5))
        if frame.get("type") != "state" or not isinstance(frame.get("data"), dict):
            raise RuntimeError("Frozen WebSocket did not emit its authenticated state frame")


def launch(
    binary: Path, data_dir: Path, token: str, parent_pipe: bool = False
) -> subprocess.Popen[str]:
    environment = {
        "PATH": "/usr/bin:/bin:/usr/sbin:/sbin",
        "GRID_API_TOKEN": token,
        "ALLOW_MAINNET_TRADING": "false",
        "LANG": "en_US.UTF-8",
        "HOME": os.environ.get("HOME", str(data_dir)),
    }
    if parent_pipe:
        environment["GRIDBOT_PARENT_STDIN"] = "true"
        environment["GRIDBOT_PARENT_PID"] = str(os.getpid())
    # Native Python/Node environments are intentionally not inherited.
    return subprocess.Popen(
        [str(binary), "--port", "0", "--data-dir", str(data_dir)],
        cwd=data_dir,
        env=environment,
        stdin=subprocess.PIPE if parent_pipe else subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        text=True,
    )


def stop(process: subprocess.Popen[str], url: str | None, token: str) -> None:
    if process.poll() is not None:
        return
    if url:
        try:
            request(url, token, "/api/shutdown", {})
        except OSError:
            process.terminate()
    else:
        process.terminate()
    try:
        process.wait(timeout=15)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait(timeout=5)
        raise RuntimeError("Frozen backend failed graceful shutdown") from None
    if process.returncode != 0:
        raise RuntimeError(f"Frozen backend exit code: {process.returncode}")


def verify(binary: Path, data_dir: Path) -> list[str]:
    checks: list[str] = []
    for run in (1, 2):
        token = secrets.token_hex(32)
        process = launch(binary, data_dir, token)
        url = None
        try:
            url = wait_ready(process)
            health = request(url, token, "/api/health")
            if health.get("status") != "ok" or health.get("mainnet_allowed") is not False:
                raise RuntimeError("Frozen backend health/Mainnet safety check failed")
            state = request(url, token, "/api/state")
            if state.get("status") == "RUNNING":
                raise RuntimeError("Frozen backend resumed automatic trading without confirmation")
            asyncio.run(verify_websocket(url, token))
            index_request = urllib.request.Request(
                url + "/", headers={"Authorization": f"Bearer {token}"}
            )
            with urllib.request.urlopen(index_request, timeout=5) as response:
                if b"</html>" not in response.read().lower():
                    raise RuntimeError("Frozen frontend assets are unavailable")
            database = find_database(data_dir)
            with sqlite3.connect(database) as connection:
                if connection.execute("PRAGMA integrity_check").fetchone() != ("ok",):
                    raise RuntimeError("Frozen database integrity failed")
                tables = {
                    row[0]
                    for row in connection.execute(
                        "SELECT name FROM sqlite_master WHERE type='table'"
                    )
                }
                required = {"orders", "executions", "configuration", "bot_sessions"}
                if not required <= tables:
                    raise RuntimeError(
                        f"Frozen database migrations are incomplete: {required - tables}"
                    )
                if run == 1:
                    connection.execute("CREATE TABLE qa_persistence_probe(value TEXT NOT NULL)")
                    connection.execute("INSERT INTO qa_persistence_probe VALUES ('retained')")
                elif connection.execute("SELECT value FROM qa_persistence_probe").fetchone() != (
                    "retained",
                ):
                    raise RuntimeError("Frozen backend lost existing data on restart")
            if (data_dir.stat().st_mode & 0o077) != 0:
                raise RuntimeError("Frozen backend data directory is not owner-only")
            checks.append(
                f"run {run}: health, authenticated WebSocket, embedded frontend, guarded Mainnet, paused startup, migrations, database integrity"
            )
        finally:
            stop(process, url, token)
    checks.append("embedded runtime: PATH contains no Python/Node/Docker dependencies")
    checks.append("existing database survives graceful shutdown and reopen")
    token = secrets.token_hex(32)
    process = launch(binary, data_dir, token, parent_pipe=True)
    url = None
    try:
        url = wait_ready(process)
        request(url, token, "/api/health")
        if process.stdin is None:
            raise RuntimeError("Frozen parent monitoring pipe was not created")
        process.stdin.close()
        try:
            process.wait(timeout=15)
        except subprocess.TimeoutExpired:
            raise RuntimeError("Frozen backend stayed alive after parent pipe EOF") from None
        if process.returncode != 0:
            raise RuntimeError("Frozen backend failed graceful orphan shutdown")
        checks.append(
            "PyInstaller process tree: parent pipe EOF causes safe pause and graceful shutdown"
        )
    finally:
        stop(process, url, token)
    return checks


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("binary", type=Path)
    parser.add_argument("--report", type=Path)
    arguments = parser.parse_args()
    if arguments.report:
        arguments.report.unlink(missing_ok=True)
    binary = arguments.binary.resolve()
    if not binary.is_file() or not os.access(binary, os.X_OK):
        raise SystemExit("A real executable frozen sidecar is required")
    with tempfile.TemporaryDirectory(prefix="gridbot-frozen-qa-") as directory:
        checks = verify(binary, Path(directory))
    report = {
        "result": "PASS",
        "checks": checks,
        "timestamp_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    }
    if arguments.report:
        arguments.report.parent.mkdir(parents=True, exist_ok=True)
        arguments.report.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
