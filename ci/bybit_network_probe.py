"""Public network preflight only. No credentials and no orders are used."""

import asyncio
import json
import time
from pathlib import Path

import httpx
from websockets.asyncio.client import connect

REST_ENDPOINTS = {
    "public_mainnet": "https://api.bybit.com/v5/market/time",
    "official_demo": "https://api-demo.bybit.com/v5/market/time",
}
WS_ENDPOINTS = {
    "public_linear": "wss://stream.bybit.com/v5/public/linear",
    "official_demo_private": "wss://stream-demo.bybit.com/v5/private",
}


async def rest(name: str, url: str) -> dict:
    started = time.monotonic()
    result = {"check": name, "endpoint": url, "result": "FAIL"}
    try:
        async with httpx.AsyncClient(trust_env=False, follow_redirects=False, timeout=10) as client:
            response = await client.get(url)
            result["http_status"] = response.status_code
            if response.status_code == 200:
                body = response.json()
                if body.get("retCode") == 0 and body.get("result", {}).get("timeSecond"):
                    result["result"] = "PASS"
                else:
                    result["note"] = "Exchange did not return a valid server-time response"
            else:
                result["note"] = "Access refused or unavailable; no authenticated request will follow"
    except Exception as exc:
        result["error_type"] = type(exc).__name__
    result["seconds"] = round(time.monotonic() - started, 3)
    return result


async def websocket(name: str, url: str) -> dict:
    result = {"check": name, "endpoint": url, "result": "FAIL"}
    try:
        async with connect(url, proxy=None, open_timeout=10, close_timeout=2) as socket:
            if name == "public_linear":
                await socket.send(json.dumps({"op": "subscribe", "args": ["tickers.BTCUSDT"]}))
                deadline = asyncio.get_running_loop().time() + 10
                while asyncio.get_running_loop().time() < deadline:
                    message = json.loads(await asyncio.wait_for(socket.recv(), timeout=10))
                    if message.get("topic") == "tickers.BTCUSDT" and message.get("data", {}).get("lastPrice"):
                        result["result"] = "PASS"
                        result["note"] = "Actual public BTCUSDT ticker received"
                        break
            else:
                result["result"] = "PASS"
                result["note"] = "TLS/WebSocket handshake only; private authentication not tested"
    except Exception as exc:
        result["error_type"] = type(exc).__name__
        response = getattr(exc, "response", None)
        if response is not None:
            result["http_status"] = getattr(response, "status_code", None)
    return result


async def main() -> int:
    checks = await asyncio.gather(
        *(rest(name, url) for name, url in REST_ENDPOINTS.items()),
        *(websocket(name, url) for name, url in WS_ENDPOINTS.items()),
    )
    report = {
        "result": "PASS" if all(check["result"] == "PASS" for check in checks) else "FAIL",
        "checks": checks,
        "timestamp_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "credentials_used": False,
        "orders_sent": 0,
        "private_authentication": "NON VERIFICATO",
        "demo_is_testnet": False,
    }
    output = Path("build/reports/bybit-network.json")
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps(report, indent=2))
    return 0 if report["result"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
