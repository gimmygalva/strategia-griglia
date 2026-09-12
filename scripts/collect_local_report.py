"""Create a source-delivery report from passed local evidence, never a Mac release."""

from __future__ import annotations

import json
import time
import xml.etree.ElementTree as ET
from collections import Counter
from pathlib import Path

from scripts.write_build_manifest import frontend_summary, junit_summary


def load(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def main() -> None:
    root = Path(__file__).resolve().parents[1]
    reports = root / "build" / "reports"
    backend = junit_summary(reports / "backend-tests.xml")
    frontend = frontend_summary(reports / "frontend-tests.json")
    if backend["skipped"] or frontend["numPendingTests"]:
        raise SystemExit("Report requires all available local tests to have executed")
    stages = load(reports / "backend-quality.json") + load(reports / "frontend-quality.json")
    if not stages or any(row["result"] != "PASS" for row in stages):
        raise SystemExit("A local quality gate has not passed")
    frozen = load(reports / "linux-frozen-backend.json")
    vite = load(reports / "frontend-start.json")
    if frozen["result"] != "PASS" or vite["result"] != "PASS":
        raise SystemExit("Actual local launch evidence is required")
    ui_e2e = load(reports / "frontend-backend-e2e.json")
    if ui_e2e["result"] != "PASS" or not ui_e2e["checks"]:
        raise SystemExit("Real frontend/backend local integration evidence is required")
    snapshot = load(reports / "source-consistency.json")
    if snapshot["result"] != "PASS":
        raise SystemExit("Sources changed after the final suite began")
    version = load(root / "desktop" / "package.json")["version"] + "-dev"
    timestamp = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    coverage = load(reports / "backend-coverage.json")["totals"]["percent_covered"]
    groups = Counter(
        row.get("classname", "unknown")
        for row in ET.parse(reports / "backend-tests.xml").iter("testcase")
    )
    table = "\n".join(f"| `{name}` | {count} | PASS |" for name, count in sorted(groups.items()))
    stage_table = "\n".join(
        f"| {row['check']} | PASS | {row['timestamp_utc']} | `{row['log']}` |" for row in stages
    )
    document = f"""# TEST REPORT — GRID HEDGE BOT {version}

Data report: **{timestamp}**. Ambiente: Linux x86_64, Python 3.12, Node 24.

**Esito delle prove locali: PASS. Accettazione operativa macOS + Bybit Demo:
NON SUPERATA. Questa è una consegna di sorgenti, non una release definitiva.**

## Ultima esecuzione completa

- Backend, integrazione, sicurezza e verifiche statiche desktop: **{backend["tests"]}
  test PASS**, {backend["failures"]} FAIL, {backend["errors"]} errori,
  {backend["skipped"]} saltati.
- Frontend React: **{frontend["numPassedTests"]} test PASS**,
  {frontend["numFailedTests"]} FAIL, {frontend["numPendingTests"]} non eseguiti.
- E2E DOM React con backend e WebSocket realmente avviati: **PASS**;
  `build/reports/frontend-backend-e2e.json`, {ui_e2e["timestamp_utc"]}.
- Copertura Python di righe e branch combinati: **{coverage:.2f}%**. La copertura
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
{table}

## Compilazione, lint e dipendenze

| Verifica | Risultato | Data UTC | Evidenza |
| --- | --- | --- | --- |
{stage_table}

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
| Frontend server avviato | PASS | Vite reale, HTTP 200 su `/` e modulo TS; `{vite["timestamp_utc"]}` |
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
| Sidecar incorporato Linux | PASS | `{frozen["timestamp_utc"]}`; HTTP/WS/static, DB, reopen e parent-pipe EOF |

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

## Decisione

Zero test locali falliti nell'ultima suite. **MVP operativo finale non completato**:
servono il conto Demo ufficiale collaudato e una vera installazione Mac verificata.
DEMO seleziona `api-demo.bybit.com`; LIVE seleziona `api.bybit.com`, disabilitato
per default con `ALLOW_MAINNET_TRADING=false`. Testnet non compare nella UI.
"""
    (root / "TEST_REPORT.md").write_text(document, encoding="utf-8")
    manifest = {
        "version": version,
        "build": timestamp,
        "classification": "DEVELOPMENT_SOURCES_LOCAL_TESTED_RELEASE_BLOCKED",
        "backend": backend,
        "frontend": frontend,
        "frontend_backend_dom_e2e": ui_e2e,
        "local_checks_passed": True,
        "official_bybit_demo_verified": False,
        "macos_package_generated": False,
        "macos_package_verified": False,
        "mainnet_trades_sent": False,
    }
    (reports / "LOCAL_BUILD_MANIFEST.json").write_text(
        json.dumps(manifest, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps(manifest))


if __name__ == "__main__":
    main()
