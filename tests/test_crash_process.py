import asyncio
import json
import os
import signal
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


async def spawn_worker(server, data, start=False):
    env = {**os.environ, "PYTHONPATH": str(ROOT / "backend") + os.pathsep + str(ROOT / "tests")}
    command = [
        sys.executable,
        str(ROOT / "tests" / "crash_worker.py"),
        "--data",
        str(data),
        "--server",
        server.base_url,
    ]
    if start:
        command.append("--start")
    child = await asyncio.create_subprocess_exec(
        *command, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE, env=env
    )
    try:
        line = await asyncio.wait_for(child.stdout.readline(), 12)
        if not line:
            errors = await child.stderr.read()
            raise AssertionError("Worker failed before READY: " + errors.decode()[-2000:])
        return child, json.loads(line)
    except BaseException:
        if child.returncode is None:
            child.kill()
        await child.wait()
        raise


@pytest.mark.asyncio
async def test_sigkill_restart_actual_remote_state_no_duplicate_orders(
    local_bybit_server, tmp_path
):
    server = local_bybit_server
    first, report = await spawn_worker(server, tmp_path / "ledger", True)
    second = None
    try:
        assert report == {"status": "RUNNING", "orders": 4, "lots": 2, "environment": "DEMO"}
        first.send_signal(signal.SIGKILL)
        assert await first.wait() == -signal.SIGKILL
        count = len(server.state.orders)
        second, recovered = await spawn_worker(server, tmp_path / "ledger")
        assert recovered == {"status": "READY", "orders": 4, "lots": 2, "environment": "DEMO"}
        await asyncio.sleep(0.2)
        assert len(server.state.orders) == count == 4
        assert len({row["orderLinkId"] for row in server.state.orders.values()}) == 4
        assert len(server.state.executions) == 2
        assert all(
            row["orderStatus"] == "New" for row in server.state.orders.values() if row["reduceOnly"]
        )
    finally:
        for child in [first, second]:
            if child and child.returncode is None:
                child.kill()
                await child.wait()
