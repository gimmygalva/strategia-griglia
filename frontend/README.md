# Grid Hedge Bot frontend

React 19, TypeScript, Tailwind 4 and TradingView Lightweight Charts 5. The interface contains Home, Attività, Impostazioni and a ten-step first-run wizard.

## Development checks

```sh
npm ci
npm run lint
npm run format:check
npm test
npm run build
```

The production bundle is written to `frontend/dist/`. The Python backend serves this bundle on its authenticated local origin. Open the development bootstrap URL printed by a backend started with `GRID_DEVELOPMENT_BOOTSTRAP=true`; this sets the HttpOnly cookie used by browser requests. The desktop wrapper instead provides the endpoint and a memory-only token through Tauri `bootstrap`.

## Data and controls

- All market candles and prices come from the backend's Bybit feed. Empty connections show unknown financial amounts, with an explicit disconnected status.
- Portfolio equity is account equity. Grid, Recovery, Long and Short PnL are the backend's executed bot ledger. Funding and commissions are shown separately in the expanded breakdown.
- Both exchange feeds, account validation and a reconciled backend state are required before Start is enabled.
- LIVE requires the backend safety flag, an acknowledgment and the exact written confirmation `AVVIA LIVE`. Close All requires a separate acknowledgment and `CHIUDI TUTTO`.
- API credentials are sent once to the backend OS credential store. Successful storage clears both inputs. The frontend provides no credential-read API and uses no localStorage for credentials or auth tokens.
- A sidecar restart invalidates the cached endpoint/token, reopens the state socket and announces frontend readiness for the new generation. Restart never invokes Start.
- State snapshots are validated before use. A newer WebSocket snapshot supersedes an older REST response.

## Test boundaries

Vitest tests use fixtures explicitly named Local Simulator. Fixtures are excluded from the production entry point and are never presented as Bybit Demo Trading. The suite covers config constraints, numeric display, environment selection, API inputs, secret handling, auth bootstrap, error handling, realtime event deduplication, reconnect, stale-response prevention, all screens, the ten-step wizard, Start/Pause, Recovery and Live/Close confirmations.

Manual browser rendering and macOS native UI verification require their corresponding permitted runtime. They must be reported separately from component tests. Real Bybit Demo order tests require genuine Demo credentials and exchange connectivity.
