# React DOM + backend + V5 network integration

Run from the project root with the project's Python environment:

```sh
python scripts/run_frontend_backend_e2e.py
```

The orchestrator starts a fresh SQLite-backed production FastAPI runtime and the
explicitly named **Local Simulator** V5 server on two ephemeral loopback ports. It
then starts the dedicated Vitest/jsdom test in the same process/network namespace.
Production `api.ts`, `useBot`, React components, requests, responses, exchange
signing, order manager, positions, recovery, persistence and WebSocket messages are
used directly. Normal API authentication and Host/Origin security gates remain
active. Missing URL/token/report configuration fails; no test is skipped.

The test completes the ten-step wizard, saves fixture credentials, tests the real
connection, validates UTA/Hedge Mode, starts real Local Simulator LONG/SHORT
orders, checks execution confirmation and two reduce-only TPs, toggles Home Auto
Recovery while running, displays wallet/order IDs/audit events, pauses while
preserving positions/TPs, displays an unsafe losing recovery suggestion and checks
backend rejection, then reconnects the DOM and local WebSocket without new orders.
It also resumes through the UI with Auto ON and the unsafe losing block, processes
a real exchange tick without a grid crossing, verifies zero recovery intents or
new V5 orders, and pauses again before reconnecting.

Evidence is written to `build/reports/frontend-backend-e2e.json`, including every
mandatory check, UTC timestamp, actual network counts and explicit limitations.
The dedicated test is excluded from the default frontend unit suite.

Only native Tauri bootstrap/event communication and Lightweight Charts' unavailable
canvas renderer are substituted. The bridge supplies the actual ephemeral server
URL and local API token; no real Bybit credential is passed to Vitest. jsdom's
genuine WebSocket sends the actual window Origin. Node's real fetch uses the
desktop bearer path, so browser-generated REST CORS is outside this test.
Vitest's VM pool keeps Node's `Event`/`EventTarget` in undici's host realm and DOM
events in the jsdom realm; it does not replace or fabricate WebSockets. Runner
output is saved beside the report and failing attempts are archived before rerun.

This verifies a DOM flow against real local network services. It does **not** prove
manual visual rendering, WKWebView/Tauri native lifecycle, a macOS installer,
official Bybit Demo Trading, Live trading or successful recovery execution. The
Local Simulator is never presented as Bybit Demo Trading. Backend crash recovery
and packaged native startup have separate verification procedures.
