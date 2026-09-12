# Testing and release evidence

This project is financial automation software. A successful compilation is insufficient
release evidence. See `TEST_REPORT.md` for results actually obtained on the current
build and `KNOWN_ISSUES.md` for unresolved limits. A test that was not executed is
**NON VERIFICATO**, never PASS.

## Scope of the local automated suite

The strategy uses one implementation for official Bybit DEMO and LIVE. The test-only
**LOCAL SIMULATOR** is not Bybit Demo Trading and is never selected by the production
UI or exchange configuration.

`tests/mock_bybit.py` runs an actual FastAPI/uvicorn server on a fresh loopback port,
including actual HTTP and WebSocket connections. Private REST requests must contain
a valid V5 HMAC signature over the exact query/body bytes. Private WebSocket clients
must authenticate before subscribing. HTTPX's test transport bridge records the
production URL first, then forwards bytes to loopback; production endpoints remain
immutable. The fixture cannot access or trade on Bybit.

The fixture can inject:

| Condition | Control |
|---|---|
| HTTP 429 | `state.inject_fault(path, '429', count=...)` |
| HTTP 503 | `state.inject_fault(path, '5xx', count=...)` |
| V5 rate limit envelope | `state.inject_fault(path, 'api_rate_limit')` |
| Business rejection | `state.reject_next_create = True` |
| Delay before request | `state.latency = seconds` |
| Accepted order followed by lost ACK | `state.inject_fault('/v5/order/create', 'accepted_timeout', delay=seconds)` |
| Delayed execution | `state.fill_delay = seconds` |
| Partial execution | `state.fill_fraction = Decimal('0.4')` or `await state.fill(id, qty)` |
| Execution before filled order update | `state.execution_first = True` |
| Duplicate execution frame | `state.duplicate_executions = True` |
| Stale NEW frame after FILLED | `state.stale_order_after_fill = True` |
| Private stream interruption | `await state.disconnect_private()` |
| Market movement and limit TP fills | `await state.advance_market(Decimal(price))` |
| Pagination | `state.page_size = 1` |
| Signed funding settlement | `await state.settle_funding('Buy', Decimal('-5'))` |
| Historical UTC opening mark | `state.midnight_mark = Decimal('68000')`; set `None` for unavailable |

Each fixture has isolated credentials, order IDs, executions, positions and fault
queues. Simulator credentials are explicitly test-only and do not identify a Bybit
account. Inherited proxy settings are disabled for loopback tests.

## Development commands

Use Python 3.12 or later in an isolated environment. These commands are for
maintainers; the packaged macOS app embeds its runtime and requires no Terminal for
daily use.

```sh
python -m venv .venv
.venv/bin/python -m pip install -r backend/requirements-dev.txt
.venv/bin/python -m pytest tests -q
.venv/bin/python -m ruff check backend tests
.venv/bin/python -m ruff format --check backend tests
```

For individual actual-network fault and independent accounting tests:

```sh
.venv/bin/python -m pytest tests/test_fault_server.py -q
.venv/bin/python -m pytest tests/test_recovery_economics_runtime.py -q
```

Frontend checks:

```sh
cd frontend
npm ci
npm run lint
npm run test
npm run build
```

End-to-end browser tests must start the actual backend and compiled frontend;
component tests alone do not verify application startup.

Generate fresh machine-readable evidence instead of retaining a previous successful
build's results:

```sh
.venv/bin/python -m pytest tests -q --junitxml=dist/backend-tests.xml
```

A failing assertion blocks a release candidate. Fix the cause, rerun the relevant
test, then rerun the entire suite on a clean build.

## Independent invariants

Tests assert externally meaningful invariants rather than duplicating source code:

- A timed-out order that was accepted by the exchange has exactly one create call,
  one exchange ID and no duplicate execution. Its final state is recovered from
  realtime/history queries before further trading.
- A partial execution protects only actual filled quantity. Requested pending
  quantity never participates in average entry, exposure or recovery capital.
- An execution arriving before its order update remains valid. Repeated `execId`
  contributes exactly once to order fills, position quantities, fees and PnL.
- A filled order report with missing execution records blocks new entries. Terminal
  status cannot release exposure that is not yet accounted for.
- After an entry fills ten units at 100, closes four at 110, then fills ten at 200,
  the sixteen remaining units cost 2600: their average is 162.5. Previously closed
  units cannot dilute a later fill. Fees allocated to the remaining lot follow the
  same quantity accounting.
- Cumulative realized gross PnL equals actual closing cash flows minus actual entry
  cash flows when a lot is fully closed. Signed fee records, including real maker
  rebates, remain separate from gross PnL. Signed funding settlements are
  deduplicated by provider transaction ID and included in net PnL and daily loss.
- Invalid numeric events, contradictory order IDs and contradictory hedge position
  indices cannot partially commit database updates.
- A LONG reduce-only TP uses `positionIdx=1` and does not change the SHORT block.
  Pausing cancels pending bot entries and retains protective reduce-only orders.
- Daily loss reconstructs inventory at UTC midnight from actual executed history
  and the official mark-price opening candle. Existing positions after app downtime
  cannot reset an intraday loss baseline to the current price. An unavailable
  opening mark blocks risk validation; it is never substituted with current price.
- A definitively rejected injection with zero executions retains the previous TP
  and clears its active recovery flag. An uncertain injection remains blocked until
  reconciliation; that state never permits an automatic duplicate injection.
- A same-side funding debit after recovery activation reprices an insufficient
  recovery TP only after its cancellation is confirmed and exchange state is
  reconciled. The replacement preserves actual position quantity, advances a
  persisted generation and creates no further injection. Positive funding retains
  an existing TP that already covers the net target. Repeated reconciliation does
  not duplicate orders or settlements. Both hedge sides are closed in the local
  server and their final net PnL is independently recomputed from signed executed
  notionals, every actual fee and settled funding.
- A populated trade database is bound to its verified account UID across restarts.
  New credentials for another main account/subaccount cannot adopt an old ledger,
  even when aggregate position quantities happen to match.
- DEMO private requests use `api-demo.bybit.com`; its public market requests use
  `api.bybit.com`. No testnet endpoint is selected. LIVE mutation calls require both
  backend authorization and explicit user confirmation.
- Nonmonotonic public quote timestamps cannot replace a current price or refresh
  its freshness. Invalid numeric quotes pause trading without poisoning the last
  valid price. Unknown or divergent position events immediately block new entries.
- Aggregated market closures cannot cancel protective TPs before closure is feasible
  within instrument size limits; large closures use valid chunks.
- Loss, exposure, reserved orders, fee/slippage allowances and instrument rules must
  pass before every create request. Unknown state blocks new entries.
- Fresh last price cannot authorize an order when mark price is stale. A private
  disconnect or funding received during the durable intent transaction prevents
  HTTP creation even while the actor is busy; queued funding does not block pongs.
- History pagination keeps explicit older intervals contiguous and leaves a recent
  tail inside the server's documented implicit interval. Actual loopback fills and
  funding remain visible with a synchronized clock lag of one second. Contradictory
  rows for the same execution ID must block reconciliation rather than overwrite
  evidence.

## Crash and restart

The restart test must retain the same database and simulator/exchange state while
recreating or killing the backend process. It must verify that reopening does not
resume entries, migrations preserve data, reconciliation rebuilds actual fills,
positions agree and persisted client IDs are never sent twice. An orderly Python
object recreation is useful integration evidence, but is not equivalent to a
SIGKILL subprocess test; report the two separately.

## DOM frontend/backend integration

Run `python scripts/run_frontend_backend_e2e.py` after installing project test
dependencies and frontend npm dependencies. It starts the normal authenticated
FastAPI app and the signed V5 Local Simulator, then runs the dedicated Vitest
configuration within the same loopback network namespace. Evidence is written to
`build/reports/frontend-backend-e2e.json`. Production api.ts/useBot use real HTTP
requests and real local WebSockets; no API/state fixture is substituted.
Only the native Tauri bridge and unavailable canvas renderer are substituted.
This verifies controls and data flow in jsdom, not visual browser/WKWebView behavior.

## Official Bybit Demo verification

Official Demo tests require user-provided API credentials created inside normal
Bybit **Demo Trading**, outbound connectivity and a compatible UTA hedge account.
Do not print or place those credentials in the source tree, JSON fixtures, reports
or command-line arguments.

Use only official DEMO for trading verification:

1. Verify authenticated account identity, UTA, permissions, USDT balance and hedge
   indices; retrieve instrument rules and mainnet public market data.
2. Verify private WebSocket authentication/subscriptions and public market frames.
3. Create a small valid order; retain the actual Bybit order ID and acknowledgement.
4. Query that order, verify its authoritative status and cancel a pending test order.
5. Verify actual executions and fees for any intentional executed demo order.
6. Run a small grid, inspect IDs in both UI and Bybit Demo, pause and cancel test
   pending entries. Existing positions and protective TPs must be inspected explicitly.
7. Restart, reconcile and verify no duplicated client IDs, orders or executions.

Missing credentials or blocked external connectivity make those checks
**NON VERIFICATO**. Passing the local simulator does not change that status.
Never send LIVE orders as part of this test procedure. Recovery is first verified
mathematically and with the local simulator; do not create forced risky exchange
positions just to trigger it.

## macOS installer verification

Building and testing the macOS application requires a macOS runner. Linux cannot
verify an Apple Keychain, mount an Apple DMG or run a native `.app`. Do not create a
renamed Linux binary or claim cross-platform build evidence as a macOS launch test.

On a macOS runner, build from a clean checkout, mount the resulting DMG, copy the app
to a temporary Applications directory and launch it. Verify the actual app process,
embedded backend readiness, rendered frontend, database migrations and restrictive
file permissions. Close the app, reopen it and verify persisted settings and database.
Run again with a fresh data directory and no user Python, Node or Docker dependency.
Run upgrade verification against an existing database and Keychain identity.

Developer ID signing and notarization require the owner's Apple certificate and
notarization profile. Report ad-hoc launch verification separately from Apple signed
and notarized verification. Archive the logs and machine-readable test results with
the resulting package.

## Acceptance decision

Release sign-off is based on the documented operational flow, not a test count. All
critical executed checks must pass, official Demo must be demonstrated on a real
compatible account, and the actual macOS package must pass install/open/restart
checks. External prerequisites must appear explicitly as NON VERIFICATO. A development
handoff with such limits must not be called a finished or verified financial release.
