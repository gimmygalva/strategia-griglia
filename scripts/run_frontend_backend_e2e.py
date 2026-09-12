"""Run React/jsdom against real FastAPI and LOCAL SIMULATOR V5 network servers.

Both servers and the Vitest child share this one process/network namespace.
No production security gate, REST response or WebSocket is substituted.
"""

from __future__ import annotations

import argparse
import asyncio
import contextlib
import json
import os
import secrets
import shutil
import socket
import sys
import tempfile
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

ROOT = Path(__file__).resolve().parents[1]


class MarketInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    price: Decimal = Field(gt=0)


def timestamp() -> str:
    return datetime.now(UTC).isoformat()


def write_report(path: Path, evidence: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".json.pending")
    temporary.write_text(json.dumps(evidence, indent=2) + "\n", encoding="utf-8")
    temporary.replace(path)


def archive_failure(report: Path, output: Path) -> None:
    if not report.is_file():
        return
    with contextlib.suppress(ValueError, OSError):
        previous = json.loads(report.read_text(encoding="utf-8"))
        if previous.get("result") == "FAIL":
            suffix = datetime.now(UTC).strftime("%Y%m%dT%H%M%S%fZ")
            prefix = report.parent / f"e2e-attempt-{suffix}"
            shutil.copy2(report, prefix.with_suffix(".json"))
            if output.is_file():
                shutil.copy2(output, prefix.with_suffix(".log"))


def check(name: str, accepted: bool, details: str) -> dict[str, str]:
    return {"name": name, "result": "PASS" if accepted else "FAIL", "details": details}


async def run(report: Path) -> int:
    # Standalone entry point intentionally loads the project's test-only fixture.
    sys.path[:0] = [str(ROOT / "backend"), str(ROOT / "tests")]
    import httpx
    import uvicorn
    from fastapi import Request
    from gridbot.api import create_app
    from gridbot.models import Environment
    from mock_bybit import LocalBybitServer
    from test_runtime import make_runtime

    token = secrets.token_urlsafe(48)
    output = report.with_suffix(".log")
    archive_failure(report, output)
    evidence: dict[str, Any] = {
        "result": "FAIL",
        "timestamp_utc": timestamp(),
        "checks": [],
        "failure": "Orchestration did not complete.",
        "limitations": [
            "React/jsdom DOM integration is not manual browser/WKWebView or macOS installer proof.",
            "V5 network server is explicitly LOCAL SIMULATOR, never official Bybit Demo Trading.",
            "Native Tauri bridge and unavailable chart canvas renderer are substituted only.",
        ],
    }
    write_report(report, evidence)
    exchange = LocalBybitServer()
    backend = None
    backend_task: asyncio.Task | None = None
    market_task: asyncio.Task | None = None
    process: asyncio.subprocess.Process | None = None
    output_task: asyncio.Task | None = None
    sock: socket.socket | None = None
    runtime = None
    directory = tempfile.TemporaryDirectory(prefix="gridbot-dom-network-e2e-")
    local_requests: list[dict[str, Any]] = []
    maximum_listeners = 0
    exit_code = 1

    try:
        await exchange.start()
        runtime = make_runtime(Path(directory.name), exchange)
        # Start genuinely without credentials: only the production UI save can
        # populate this explicit in-memory test store before signed connection.
        for environment in Environment:
            runtime.credentials_store.delete(environment)
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.bind(("127.0.0.1", 0))
        sock.listen(128)
        port = sock.getsockname()[1]
        base_url = f"http://127.0.0.1:{port}"
        app = create_app(runtime, token, port)

        @app.middleware("http")
        async def record_local_requests(request: Request, call_next):
            nonlocal maximum_listeners
            response = await call_next(request)
            maximum_listeners = max(maximum_listeners, len(runtime.listeners))
            # Never record headers, bodies, credentials or the local bootstrap token.
            local_requests.append(
                {"method": request.method, "path": request.url.path, "status": response.status_code}
            )
            return response

        @app.get("/api/e2e/stats")
        async def stats():
            async with runtime.lock:
                ledger_orders = await runtime.store.orders()
                return {
                    "orders": [
                        {
                            key: order[key]
                            for key in (
                                "orderId",
                                "orderLinkId",
                                "reduceOnly",
                                "orderStatus",
                                "positionIdx",
                                "qty",
                            )
                        }
                        for order in exchange.state.orders.values()
                    ],
                    "positions": [
                        {key: position[key] for key in ("positionIdx", "size", "avgPrice")}
                        for position in exchange.state.positions()
                    ],
                    "executions_count": len(exchange.state.executions),
                    "ledger_executions_count": len(await runtime.store.executions()),
                    "frontend_listeners": len(runtime.listeners),
                    "private_clients": len(exchange.state.private_clients),
                    "public_clients": len(exchange.state.public_clients),
                    "market_timestamp": runtime.last_market_timestamp,
                    "reconciled": runtime.reconciled,
                    "recovery_intents": sum(
                        order["purpose"] == "RECOVERY" for order in ledger_orders
                    ),
                    "credentials_saved": {
                        environment.value: runtime.credentials_store.load(environment) is not None
                        for environment in Environment
                    },
                }

        @app.post("/api/e2e/market")
        async def move_market(body: MarketInput):
            # Only manipulate the named LOCAL SIMULATOR market source. Its actual
            # exchange WebSocket delivers the price to unmodified production logic.
            await exchange.state.advance_market(body.price, fill_limits=False)
            return {"accepted": True}

        config = uvicorn.Config(app, log_level="error", ws="websockets-sansio", lifespan="on")
        backend = uvicorn.Server(config)
        backend_task = asyncio.create_task(backend.serve(sockets=[sock]))
        deadline = asyncio.get_running_loop().time() + 10
        while not backend.started:
            if backend_task.done():
                await backend_task
                raise RuntimeError("Actual FastAPI runtime failed to start.")
            if asyncio.get_running_loop().time() >= deadline:
                raise TimeoutError("Actual FastAPI runtime startup timed out.")
            await asyncio.sleep(0.01)

        async with httpx.AsyncClient(base_url=base_url, trust_env=False, timeout=3) as client:
            unauthenticated = await client.get("/api/state")
            forbidden_origin = await client.post(
                "/api/pause",
                headers={"Authorization": f"Bearer {token}", "Origin": "https://untrusted.invalid"},
            )
        security_check = check(
            "Normal local API authentication and Origin gates retained",
            unauthenticated.status_code == 401 and forbidden_origin.status_code == 403,
            f"Actual HTTP GET without token returned {unauthenticated.status_code}; "
            f"authenticated POST with forbidden Origin returned {forbidden_origin.status_code}.",
        )

        async def keep_market_feed_fresh():
            while True:
                await exchange.state.advance_market(exchange.state.price, fill_limits=False)
                await asyncio.sleep(0.5)

        market_task = asyncio.create_task(keep_market_feed_fresh())
        child_environment = os.environ.copy()
        child_environment.update(
            GRIDBOT_E2E_URL=base_url,
            GRIDBOT_E2E_TOKEN=token,
            GRIDBOT_E2E_REPORT_PATH=str(report),
            ALLOW_MAINNET_TRADING="false",
        )
        process = await asyncio.create_subprocess_exec(
            "npm",
            "exec",
            "--",
            "vitest",
            "run",
            "--config",
            "e2e/vitest.config.ts",
            cwd=ROOT / "frontend",
            env=child_environment,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
        )

        async def capture_output():
            with output.open("w", encoding="utf-8") as log:
                while line := await process.stdout.readline():
                    text = (
                        line.decode("utf-8", errors="replace")
                        .replace(token, "[redacted local token]")
                        .replace(exchange.state.api_secret, "[redacted simulator secret]")
                    )
                    log.write(text)
                    log.flush()
                    print(text, end="", flush=True)

        output_task = asyncio.create_task(capture_output())
        child_result = await asyncio.wait_for(process.wait(), timeout=100)
        await output_task
        evidence = json.loads(report.read_text(encoding="utf-8"))
        evidence["checks"].append(security_check)

        exchange_paths = {call["path"] for call in exchange.state.calls}
        required_paths = {
            "/v5/user/query-api",
            "/v5/account/info",
            "/v5/account/wallet-balance",
            "/v5/market/instruments-info",
            "/v5/position/list",
            "/v5/order/create",
            "/v5/execution/list",
            "/v5/market/kline",
        }
        original_urls = runtime.adapter._client._transport.requested_urls if runtime.adapter else []
        private_urls = [url for url in original_urls if "/v5/market/" not in url]
        evidence["checks"].append(
            check(
                "Actual signed V5 bytes and canonical official DEMO routing",
                required_paths <= exchange_paths
                and bool(private_urls)
                and all(url.startswith("https://api-demo.bybit.com/") for url in private_urls),
                f"{len(exchange.state.calls)} actual V5 network requests reached the HMAC-validating "
                "LOCAL SIMULATOR; all required wallet/account/instrument/position/order/execution/candle "
                f"routes observed: {required_paths <= exchange_paths}; canonical private URLs retained "
                "api-demo.bybit.com before the explicit test-only network redirect.",
            )
        )
        successful_posts = {
            request["path"]
            for request in local_requests
            if request["method"] == "POST" and request["status"] == 200
        }
        required_posts = {
            "/api/credentials",
            "/api/connect",
            "/api/config",
            "/api/wizard",
            "/api/start",
            "/api/pause",
        }
        execution_ids = [execution["execId"] for execution in exchange.state.executions]
        evidence["checks"].append(
            check(
                "Real UI mutation network traffic, authenticated local WebSocket and unique ledger",
                required_posts <= successful_posts
                and maximum_listeners > 0
                and len(execution_ids) == len(set(execution_ids)) == 2
                and len(await runtime.store.executions()) == 2,
                "Real protected local API recorded credentials/connect/config/wizard/start/pause HTTP "
                f"requests: {required_posts <= successful_posts}; maximum authenticated frontend WS "
                f"listeners {maximum_listeners}; exchange executions {len(execution_ids)}, "
                f"unique IDs {len(set(execution_ids))} and persisted ledger executions "
                f"{len(await runtime.store.executions())}.",
            )
        )
        evidence["network"] = {
            "local_http_requests": len(local_requests),
            "v5_http_requests": len(exchange.state.calls),
            "v5_order_ids": sorted(exchange.state.orders),
            "v5_execution_ids": execution_ids,
            "fixture": "LOCAL SIMULATOR",
            "api_security_gates": "normal create_app; no test_origin or auth/origin bypass",
            "actual_loopback_servers": 2,
        }
        passed = (
            child_result == 0
            and evidence.get("result") == "PASS"
            and all(item.get("result") == "PASS" for item in evidence["checks"])
        )
        evidence["result"] = "PASS" if passed else "FAIL"
        evidence["vitest_exit_code"] = child_result
        exit_code = 0 if passed else 1
    except Exception as error:
        if report.exists():
            with contextlib.suppress(ValueError, OSError):
                evidence = json.loads(report.read_text(encoding="utf-8"))
        evidence["result"] = "FAIL"
        evidence["failure"] = str(error).replace(token, "[redacted local token]")
        exit_code = 1
    finally:
        if process and process.returncode is None:
            process.kill()
            await process.wait()
        if output_task:
            await output_task
        if market_task:
            market_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await market_task
        try:
            if backend:
                backend.should_exit = True
            if backend_task:
                await asyncio.wait_for(backend_task, timeout=10)
            if sock:
                sock.close()
            await exchange.stop()
        except Exception as error:
            evidence["result"] = "FAIL"
            evidence["failure"] = "Actual server shutdown failed: " + str(error).replace(
                token, "[redacted local token]"
            )
            exit_code = 1
        directory.cleanup()
        evidence["timestamp_utc"] = timestamp()
        write_report(report, evidence)
    print(
        json.dumps(
            {"result": evidence["result"], "checks": len(evidence["checks"]), "report": str(report)}
        )
    )
    return exit_code


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--report", type=Path, default=ROOT / "build/reports/frontend-backend-e2e.json"
    )
    arguments = parser.parse_args()
    raise SystemExit(asyncio.run(run(arguments.report.resolve())))


if __name__ == "__main__":
    main()
