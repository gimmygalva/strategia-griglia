# TEST REPORT — GRID HEDGE BOT 0.1.0-dev

Data report: **2026-09-12T13:32:33Z**. Ambiente: Linux x86_64, Python 3.12, Node 24.

**Esito delle prove locali: PASS. Accettazione operativa macOS + Bybit Demo:
NON SUPERATA. Questa è una consegna di sorgenti, non una release definitiva.**

## Ultima esecuzione completa

- Backend, integrazione, sicurezza e verifiche statiche desktop: **383
  test PASS**, 0 FAIL, 0 errori,
  0 saltati.
- Frontend React: **92 test PASS**,
  0 FAIL, 0 non eseguiti.
- E2E DOM React con backend e WebSocket realmente avviati: **1 test PASS,
  15 verifiche interne PASS** (non contate come test aggiuntivi);
  `build/reports/frontend-backend-e2e.json`, 2026-09-12T13:29:14.106162+00:00.
- Copertura Python di righe e branch combinati: **83.53%**. La copertura
  non sostituisce le prove di apertura del sidecar congelato, eseguite separatamente.
- La suite completa è stata ripetuta dopo le ultime correzioni. Il frontend è
  stato ricostruito dopo la rimozione di dist; il freeze Linux ha eliminato i vecchi
  output prima di incorporare il frontend attuale. Le sorgenti sono rimaste identiche
  durante test e build: `build/reports/source-consistency.json`.

I risultati precedenti, compresi i fallimenti poi corretti, sono conservati in
`build/reports/attempt-*`. Non vengono usati per attribuire PASS alla versione attuale.

## Suite backend e desktop statico

Data e durata dell'esecuzione: `build/reports/backend-tests.xml`.

| Modulo test | Test eseguiti | Risultato |
| --- | ---: | --- |
| `desktop.tests.test_packaging` | 11 | PASS |
| `tests.test_api` | 14 | PASS |
| `tests.test_crash_process` | 1 | PASS |
| `tests.test_exchange` | 112 | PASS |
| `tests.test_fault_server` | 38 | PASS |
| `tests.test_final_safety` | 12 | PASS |
| `tests.test_grid` | 34 | PASS |
| `tests.test_indicators` | 13 | PASS |
| `tests.test_recovery` | 30 | PASS |
| `tests.test_recovery_economics_runtime` | 4 | PASS |
| `tests.test_recovery_runtime_math` | 32 | PASS |
| `tests.test_recovery_targets` | 11 | PASS |
| `tests.test_risk` | 46 | PASS |
| `tests.test_runtime` | 4 | PASS |
| `tests.test_security_persistence` | 4 | PASS |
| `tests.test_state_machine` | 5 | PASS |
| `tests.test_websocket` | 12 | PASS |

## Compilazione, lint e dipendenze

| Verifica | Risultato | Data UTC | Evidenza |
| --- | --- | --- | --- |
| python-dependencies | PASS | 2026-09-12T13:28:46Z | `build/reports/python-dependencies.log` |
| python-lint | PASS | 2026-09-12T13:28:46Z | `build/reports/python-lint.log` |
| python-format | PASS | 2026-09-12T13:28:46Z | `build/reports/python-format.log` |
| python-compile | PASS | 2026-09-12T13:28:46Z | `build/reports/python-compile.log` |
| desktop-schema | PASS | 2026-09-12T13:28:46Z | `build/reports/desktop-schema.log` |
| backend-tests | PASS | 2026-09-12T13:31:17Z | `build/reports/backend-tests.log` |
| frontend-install | PASS | 2026-09-12T13:28:49Z | `build/reports/frontend-install.log` |
| frontend-lint | PASS | 2026-09-12T13:28:53Z | `build/reports/frontend-lint.log` |
| frontend-format | PASS | 2026-09-12T13:28:54Z | `build/reports/frontend-format.log` |
| frontend-tests | PASS | 2026-09-12T13:28:57Z | `build/reports/frontend-tests.log` |
| frontend-build | PASS | 2026-09-12T13:29:02Z | `build/reports/frontend-build.log` |
| frontend-e2e-types | PASS | 2026-09-12T13:29:05Z | `build/reports/frontend-e2e-types.log` |
| frontend-local-e2e | PASS | 2026-09-12T13:29:14Z | `build/reports/frontend-local-e2e.log` |
| frontend-dependency-audit | PASS | 2026-09-12T13:29:25Z | `build/reports/frontend-dependency-audit.log` |
| desktop-dependency-audit | PASS | 2026-09-12T13:29:34Z | `build/reports/desktop-dependency-audit.log` |

Gli audit npm frontend e desktop hanno restituito zero vulnerabilità. L'audit
advisory Python ha esito **NON VERIFICATO**, perché pip-audit non ha ricevuto una
risposta completa da PyPI entro il timeout; vedere `python-dependency-audit.json`
e relativo log. `pip check` verifica compatibilità delle dipendenze, non vulnerabilità.
Rust/Cargo non sono compilati o sottoposti ad audit in questo ambiente.

## Prove funzionali e fault effettivamente eseguiti

Il Local Simulator è un server HTTP/WebSocket loopback controllato, con firme V5
verificate. Usa esclusivamente credenziali di fixture. Non è Bybit Demo Trading.

| Verifica | Risultato | Metodo ed evidenza |
| --- | --- | --- |
| Backend avviato, API e WS locale | PASS | Uvicorn/processi reali; auth, stato, errori, mutation gates e WS |
| Frontend server avviato | PASS | Vite reale, HTTP 200 su `/` e modulo TS; `2026-09-12T13:31:25Z` |
| SQLite vuoto, migrazioni e database esistente | PASS | Alembic 0001/0002, integrità, transazioni, permessi e reopen |
| Ordini, ACK e TP | PASS | HTTP V5 loopback, ACK distinto da fill, execution effettive e reduceOnly con positionIdx 1/2 |
| Grid e Dynamic Shift | PASS | Prezzi assoluti, sequenze crescenti/decrescenti, crossing ripetuto, hysteresis e debounce |
| Partial fill | PASS | 10 richiesti, 4 eseguiti e 6 pending; media/exposure/recovery su quantità reali |
| Eventi duplicati e fuori ordine | PASS | Execution prima di order; ID duplicato una sola volta; contraddizioni bloccanti |
| Timeout, 429, 5xx e ACK perso | PASS | Fault HTTP reali, retry limitati per letture, nessun reinvio cieco di mutazioni |
| WS disconnect, reconnect e heartbeat | PASS | Socket reali, restore subscriptions, coda limitata; callback lenta non blocca pong |
| Veto all'ultimo momento | PASS | Disconnect/funding durante commit e revoca durante semaforo REST: nessun HTTP ordine |
| Daily loss, mark e fondi | PASS | Mark stale blocca; baseline UTC ricostruito; lordo hedge, riserve e fee/slippage |
| Injection, break-even e S/R | PASS | Formule indipendenti, tick/qtyStep conservativi, limiti e target netto prima di S/R |
| Recovery completo LONG/SHORT | PASS | TP parziali, handoff, restart, funding; saldo finale ricomputato da cash flow reali del simulatore |
| Funding appena liquidato e clock | PASS | Clock -1000 ms, finestre storiche contigue, paginazione e tail con margine server |
| Restart e reconciliation | PASS | Ledger persistito, ordini remoti e posizioni confrontati prima di riabilitare ingressi |
| Crash processo | PASS | SIGKILL reale, restart con stesso DB e server remoto; nessun ordine duplicato o auto-start |
| STOP e CHIUDI TUTTO | PASS | Stop conserva posizioni/TP; conferme close riducono entrambi i lati senza riaprire |
| Sicurezza API/secret | PASS | Bearer/cookie, Host/Origin/CSRF, input, path traversal; secret esclusi da risposta, ledger e log |
| Home/Attività/Impostazioni/Wizard | PASS | React/jsdom; offline, errori, restart, realtime e conferme scritte |
| UI con backend reale | PASS | React/jsdom e traffico HTTP/WS reale; controlli e dati derivati dal Local Simulator; native bridge e canvas sostituiti |
| Configurazione Tauri e icona | PASS | Schema ufficiale del CLI pinned, capabilities, container icns e script gates; prove statiche |
| Sidecar incorporato Linux | PASS | `2026-09-12T13:32:15Z`; HTTP/WS/static, DB, reopen e parent-pipe EOF |

La prova E2E DOM usa il backend reale, la stessa logica strategica e socket TCP;
non mocka state, ordini o API. Sostituisce soltanto bridge Tauri e rendering canvas
non disponibili in jsdom. Non è una verifica visiva manuale o un test WKWebView.

La prova del sidecar Linux usa PATH privo di Python, Node e Docker e avvia il
binario PyInstaller con il frontend incorporato. Dimostra il runtime congelato
Linux; **non dimostra** l'installazione pulita di una `.app` Mac.
Le deprecation warning di Starlette TestClient/AnyIO restano nel log;
non vengono nascoste o trasformate in errori ignorati del motore.

## Verifiche esterne non eseguibili

| Test richiesto | Risultato | Limite effettivo |
| --- | --- | --- |
| API Bybit Demo ufficiale, wallet/UID/UTA/Hedge Mode | NON VERIFICATO | Nessuna credenziale Demo fornita; REST esterno non raggiungibile |
| Feed mercato pubblico Bybit ufficiale | NON VERIFICATO | REST ConnectError, WS gaierror, proxy esplicito ReadTimeout |
| Demo order create/fetch/cancel e execution | NON VERIFICATO | Account e rete mancanti; ID del simulatore non sono ID ufficiali |
| Mini Grid e TP su Bybit Demo | NON VERIFICATO | Stessi limiti; nessun trading LIVE usato come sostituto |
| Recovery controllato su Demo ufficiale | NON VERIFICATO | Verificato localmente; non forzate operazioni per provocarlo sul conto |
| Mainnet account reale | NON VERIFICATO | Adapter/gates locali verificati; nessun ordine con denaro reale inviato |
| Rust/Tauri build nativa | NON VERIFICATO | Linux senza Cargo/Rust e toolchain Apple |
| Grid Hedge Bot.app e Grid Hedge Bot.dmg | NON GENERATI | Richiedono build nativa macOS; nessun pacchetto fittizio |
| Mount/copy/open/close/reopen DMG | NON VERIFICATO | Mancano macOS e pacchetto nativo |
| Clean install e upgrade Mac | NON VERIFICATO | Mancano Mac Intel/Apple Silicon e bundle da installare |
| macOS Keychain e permissions reali | NON VERIFICATO | Solo interfaccia controllata e permessi Linux verificati |
| Developer ID, hardened runtime effettivo e notarizzazione | NON VERIFICATO | Supporto predisposto; certificati/toolchain Apple non disponibili |
| Rendering manuale UI/WKWebView e sanity UX | NON VERIFICATO | Browser locale bloccato con ERR_BLOCKED_BY_CLIENT; nessuna prova visiva manuale dichiarata |
| Audit advisory Python e Rust | NON VERIFICATO | Timeout PyPI; Cargo assente |
| GitHub Actions su runner remoto | NON VERIFICATO | Pipeline predisposta, nessun repository remoto con esecuzione CI |

Per gli esiti ambiente originali vedere `build/reports/environment.json`.
La procedura di completamento delle verifiche ufficiali/native è in
`docs/TESTING.md`, `docs/BYBIT_SETUP.md` e `docs/MACOS_BUILD.md`.
`KNOWN_ISSUES.md` descrive anche i limiti operativi del motore e le funzioni rinviate.

## Dettagli E2E e artefatto frontend

L'E2E ha eseguito realmente il wizard completo, il salvataggio delle credenziali
di fixture, la connessione firmata V5, Start, due fill e due TP, la timeline audit
e la pausa. Ha verificato Auto Recovery ON/OFF durante RUNNING senza cambiare
grid o sessione e senza creare ordini; una successiva valutazione RUNNING con
Auto ON ha rifiutato la recovery oltre il limite di injection. L'interfaccia
mostra gli ID e gli stati letti dall'API SQLite. Il remount riapre il WebSocket e
rilegge lo stato in pausa mantenendo ordini ed execution. Il crash del backend
è una prova separata, non viene dedotto dal remount dell'interfaccia.

`build/reports/frontend-bundle-security.json` attesta che le credenziali note
delle fixture sono assenti nei tre asset JavaScript della build finale e che
non sono pubblicate source map. Non sostituisce la verifica del Keychain Mac
o un audit di vulnerabilità delle dipendenze Python.

## Decisione

Zero test locali falliti nell'ultima suite. **MVP operativo finale non completato**:
servono il conto Demo ufficiale collaudato e una vera installazione Mac verificata.
DEMO seleziona `api-demo.bybit.com`; LIVE seleziona `api.bybit.com`, disabilitato
per default con `ALLOW_MAINNET_TRADING=false`. Testnet non compare nella UI.
