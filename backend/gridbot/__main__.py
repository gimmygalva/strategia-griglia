import argparse
import asyncio
import json
import logging
import os
import secrets
import socket
import sys
from pathlib import Path

import uvicorn

from .api import create_app
from .runtime import BotRuntime


class AuditFormatter(logging.Formatter):
    def format(self, record):
        from .persistence import utcnow

        # Error messages/request payloads and exception repr are deliberately omitted.
        return json.dumps(
            {
                "timestamp": utcnow(),
                "module": record.name,
                "event": getattr(record, "event", "runtime"),
                "level": record.levelname,
                "environment": getattr(record, "environment", None),
                "error_type": getattr(record, "error_type", None),
                **{
                    key: getattr(record, key, None)
                    for key in ("correlation_id", "order_id", "pair_id", "level_id", "symbol")
                },
            }
        )


def default_data_dir() -> Path:
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / "Grid Hedge Bot"
    return Path.home() / ".local" / "share" / "grid-hedge-bot"


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=0)
    parser.add_argument("--host", default="127.0.0.1", choices=["127.0.0.1"])
    parser.add_argument(
        "--data-dir",
        type=Path,
        default=Path(os.getenv("GRIDBOT_DATA_DIR", str(default_data_dir()))),
    )
    args = parser.parse_args()
    args.data_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
    # A second process must not own the same ledger, independent of environment.
    import fcntl

    instance = (args.data_dir / "process.lock").open("a+")
    try:
        fcntl.flock(instance, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        print(json.dumps({"type": "error", "code": "ALREADY_RUNNING"}), flush=True)
        return 2
    logs = args.data_dir / "logs"
    logs.mkdir(exist_ok=True, mode=0o700)
    handler = logging.FileHandler(logs / "runtime.jsonl")
    handler.setFormatter(AuditFormatter())
    logging.getLogger().addHandler(handler)
    logging.getLogger().setLevel(logging.INFO)
    (logs / "runtime.jsonl").chmod(0o600)
    token = os.getenv("GRID_API_TOKEN") or secrets.token_urlsafe(48)
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.bind(("127.0.0.1", args.port))
    sock.setblocking(False)
    port = sock.getsockname()[1]
    runtime = BotRuntime(args.data_dir)
    frozen_root = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parents[2]))
    frontend = Path(os.getenv("GRID_FRONTEND_DIR", str(frozen_root / "frontend" / "dist")))
    if not frontend.is_dir() and not hasattr(sys, "_MEIPASS"):
        frontend = Path(__file__).resolve().parents[2] / "frontend" / "dist"
    server = None
    app = create_app(runtime, token, port, frontend, lambda: setattr(server, "should_exit", True))
    config = uvicorn.Config(
        app,
        host="127.0.0.1",
        port=port,
        log_level="warning",
        access_log=False,
        ws="websockets-sansio",
    )
    server = uvicorn.Server(config)

    async def run():
        task = asyncio.create_task(server.serve(sockets=[sock]))
        while not server.started:
            if task.done():
                await task
                return
            await asyncio.sleep(0.03)
        print(
            json.dumps({"type": "ready", "url": f"http://127.0.0.1:{port}", "port": port}),
            flush=True,
        )
        # Development bootstrap path is shown only on explicit request; no persistent token file.
        if os.getenv("GRID_DEVELOPMENT_BOOTSTRAP") == "true":
            print(
                json.dumps(
                    {
                        "type": "development_bootstrap",
                        "url": f"http://127.0.0.1:{port}/bootstrap/{token}",
                    }
                ),
                flush=True,
            )

        async def parent_watchdog():
            if os.getenv("GRIDBOT_PARENT_STDIN") == "true":
                loop = asyncio.get_running_loop()
                closed = loop.create_future()
                fd = sys.stdin.fileno()

                def observe_pipe():
                    try:
                        chunk = os.read(fd, 1)
                        if not chunk and not closed.done():
                            closed.set_result(None)
                    except OSError:
                        if not closed.done():
                            closed.set_result(None)

                loop.add_reader(fd, observe_pipe)
                try:
                    await closed
                finally:
                    loop.remove_reader(fd)
            else:
                parent_value = os.getenv("GRIDBOT_PARENT_PID")
                if parent_value is None:
                    return
                try:
                    parent_id = int(parent_value)
                    if parent_id <= 1:
                        raise ValueError("Invalid desktop parent")
                    while not server.should_exit:
                        try:
                            os.kill(parent_id, 0)
                        except ProcessLookupError:
                            break
                        await asyncio.sleep(1)
                except (ValueError, PermissionError):
                    server.should_exit = True
                    return
            runtime.status = "PAUSED"
            try:
                await runtime.pause()
            except Exception as exc:
                await runtime.fail_safe(exc)
            finally:
                server.should_exit = True

        watchdog = asyncio.create_task(parent_watchdog())
        try:
            await task
        finally:
            watchdog.cancel()
            await asyncio.gather(watchdog, return_exceptions=True)

    try:
        asyncio.run(run())
    finally:
        sock.close()
        instance.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
