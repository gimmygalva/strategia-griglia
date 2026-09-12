"""Subprocess worker against an explicitly named LOCAL SIMULATOR only."""

import argparse
import asyncio
import json
from pathlib import Path
from types import SimpleNamespace

from gridbot.models import Environment, StrategyConfig
from test_runtime import make_runtime, wait_for


async def run(args):
    server = SimpleNamespace(
        base_url=args.server,
        ws_url=args.server.replace("http://", "ws://"),
        state=SimpleNamespace(api_key="local-simulator-key", api_secret="local-simulator-secret"),
    )
    runtime = make_runtime(Path(args.data), server)
    await runtime.initialize()
    await runtime.connect(Environment.DEMO)
    await wait_for(lambda: runtime.public_connected and runtime.private_connected)
    if args.start:
        await runtime.configure(StrategyConfig(levels=2))
        await runtime.start()

        async def settle():
            while (
                len(await runtime.store.orders()) < 4 or len(await runtime.store.executions()) < 2
            ):
                if runtime.error:
                    raise RuntimeError(runtime.error)
                await asyncio.sleep(0.03)

        await asyncio.wait_for(settle(), 10)
    state = await runtime.state()
    print(
        json.dumps(
            {
                "status": state["status"],
                "orders": len(state["orders"]),
                "lots": len(state["positions"]),
                "environment": state["environment"],
            }
        ),
        flush=True,
    )
    await asyncio.Event().wait()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--data", required=True)
    parser.add_argument("--server", required=True)
    parser.add_argument("--start", action="store_true")
    args = parser.parse_args()
    if not args.server.startswith("http://127.0.0.1:"):
        raise SystemExit("Worker is exclusively a loopback test fixture")
    asyncio.run(run(args))
