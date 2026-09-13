# TEST REPORT — GRID HEDGE BOT 0.1.0 candidatura locale

Data report: 2026-09-12T16:04:22Z. Sorgenti applicazione compilata: `eec4ad3c41d4ceb416dc6f1f6f2c5138b21b3ab9`. Backend: `0.1.0-dev`; bundle desktop: `0.1.0`.

**Candidati installabili verificati su Mac Intel e Apple Silicon. Accettazione operativa sul conto Bybit Demo: NON SUPERATA. Non è una release definitiva.**

[Build nativa e gate finali](https://github.com/gimmygalva/strategia-griglia/actions/runs/34703106420)

## Ultima suite completa

| Test | Esito | Data UTC / prova |
| --- | --- | --- |
| Backend, integrazione, sicurezza, desktop statico su Linux | PASS: 400, zero failure/errori/skip | 2026-09-12T15:46:34Z; backend-tests.xml |
| Frontend React | PASS: 95, zero failure/pending | 2026-09-12T15:44:33Z; frontend-tests.json |
| UI/backend E2E | PASS: 1 test, 15 verifiche interne | HTTP/WS realmente avviati con Local Simulator; suite ripetuta dopo build su ogni Mac |
| Python lint/format/compile, dipendenze, schema Tauri | PASS | backend-quality.json, log e schema ufficiale della versione fissata |
| Frontend lint/format/types/build pulita, Vite avviato | PASS | frontend-quality.json e frontend-start.json |
| Freeze Linux reale | PASS | TLS dal bundle, health, API/WS autenticati, frontend incorporato, migrazioni, chiusura/riapertura e parent EOF |
| Copertura combinata righe/branch Python | 84.24% | backend-coverage.json; non sostituisce il collaudo operativo |
| Stress callback WS bloccate | PASS: 20 ripetizioni dei 2 casi | Dieci pong consumati per caso senza disconnessione; websocket-callback-stress.json |

## Pacchetti nativi effettivamente testati

| Mac | Build | Sistema verificato | Suite post-build |
| --- | --- | --- | --- |
| Intel | `2026-09-12T16:02:27Z-c731a8c109a6` | macOS-15.7.9-x86_64-i386-64bit | 399 Python PASS + 1 verifica Linux non applicabile; 95 frontend PASS; E2E PASS |
| Apple Silicon | `2026-09-12T15:56:46Z-f5bb9e8f5a1d` | macOS-15.7.9-arm64-arm-64bit | 399 Python PASS + 1 verifica Linux non applicabile; 95 frontend PASS; E2E PASS |

Per ciascun pacchetto: DMG verificato con hdiutil, montato readonly, app copiata, firma verificata con codesign e flag Hardened Runtime reali controllati. Backend incorporato e frontend WKWebView realmente aperti; database vuoto, migrazioni, integrità, permessi owner-only, chiusura, riapertura e persistenza verificati. Il backend è stato realmente ucciso con SIGKILL; il supervisor lo ha riavviato e il frontend ha acquisito il nuovo bootstrap, senza avviare ingressi. PATH/ambiente puliti impediscono dipendenze Python/Node/Docker esterne; questa prova non è una VM privata fisicamente di ogni toolchain.

Il Keychain nativo è stato collaudato attraverso il sidecar dentro la copia installata: salvataggio/rilettura di credenziali sintetiche, persistenza, namespaces DEMO/LIVE separati e assenza da API, SQLite e log. Non sono le API fornite dall’utente. Le CA TLS sono caricate dal bundle effettivo, con hostname verification e minimo TLS 1.2.

Rust: 6 test reali per architettura, cargo fmt, cargo clippy con warnings bloccanti e compilazione nativa. WKWebView: 10 verifiche DOM a ogni apertura, inclusi wizard DEMO, Home, canvas Lightweight Charts, Start offline bloccato, Attività e dettagli tecnici, tutti i tab Impostazioni, warning LIVE e campi secret vuoti. Alla riapertura la timeline viene confrontata con gli eventi reali persistiti dal backend.

Le catture schermo disponibili sono Home offline, non dati account/candele/ordini Demo. Navigazione e altre schermate sono verificate da DOM nativo; non viene dichiarata una revisione grafica manuale completa di ogni pagina. Su finestre basse la Home richiede scorrimento verticale.

## Suite Python per modulo

| Modulo | Casi locali | Esito |
| --- | ---: | --- |
| `tests.test_api` | 17 | PASS |
| `tests.test_crash_process` | 1 | PASS |
| `tests.test_exchange` | 112 | PASS |
| `tests.test_fault_server` | 38 | PASS |
| `tests.test_final_safety` | 12 | PASS |
| `tests.test_grid` | 34 | PASS |
| `tests.test_indicators` | 13 | PASS |
| `tests.test_recovery` | 30 | PASS |
| `tests.test_recovery_economics_runtime` | 4 | PASS |
| `tests.test_recovery_runtime_math` | 33 | PASS |
| `tests.test_recovery_targets` | 11 | PASS |
| `tests.test_risk` | 46 | PASS |
| `tests.test_runtime` | 4 | PASS |
| `tests.test_security_persistence` | 4 | PASS |
| `tests.test_startup_reconciliation` | 4 | PASS |
| `tests.test_state_machine` | 5 | PASS |
| `tests.test_tls` | 9 | PASS |
| `tests.test_websocket` | 12 | PASS |
| `desktop.tests.test_packaging` | 11 | PASS |

Grid: generazione, tick/qty rounding, attraversamenti ripetuti, hysteresis/debounce, TP LONG/SHORT e shift deterministico/idempotente. Recovery: media delle quantità effettivamente eseguite, injection, fee/slippage/break-even, limiti, attivazione/chiusura e funding. Risk: ambiente, account/UTA/Hedge, exposure, saldo, daily loss, stato incerto, duplicati e veto immediatamente prima dell’invio.

Integrazione con il Local Simulator: richieste REST V5 firmate, ACK, reject, 429/5xx, timeout, fill parziali 4/10, execution prima dell’order update, duplicati, WS disconnect/subscription restore, guasti DB reali, restart/reconciliation e SIGKILL di processo reale. Queste prove non sono chiamate Demo Trading.

Nuova riapertura del conto verificato: ripristino da interfaccia persistente, ordini/lotti coerenti senza Start, MAINNET ancora disabilitata, fallimento rete e cancellazione per timeout con UI locale disponibile. La rilettura Keychain nativa è verificata separatamente; il percorso sul conto ufficiale resta NON VERIFICATO.

## Sicurezza e audit dipendenze

Input, CSRF/origin/Host dove applicabile, WS non autorizzato, XSS nei dati, path/command injection, secret non restituiti/loggati/salvati plaintext e separazione DEMO/LIVE: PASS nei test. Due soli comandi IPC applicativi consentiti: bootstrap e frontend_ready. ALLOW_MAINNET_TRADING=false di default; ulteriori conferme UI/backend richieste. Nessun ordine Live inviato durante sviluppo o collaudo.

pip-audit Linux e ciascun Mac: zero vulnerabilità e nessun pacchetto saltato. npm audit frontend/desktop: zero vulnerabilità. cargo-audit sul lockfile completo: zero vulnerabilità bloccanti, sei avvisi unmaintained e un avviso unsound GLib. Grafo Cargo nativo risolto: GLib assente da entrambe le build Mac. Avvisi conservati senza --ignore; dipendenze Unicode upstream non mantenute restano un limite. [Advisory GLib](https://rustsec.org/advisories/RUSTSEC-2024-0429.html).

## Bybit ufficiale — limite esterno

[Probe Linux iniziale](https://github.com/gimmygalva/strategia-griglia/actions/runs/34698486415) e [probe indipendenti Linux/Intel/ARM](https://github.com/gimmygalva/strategia-griglia/actions/runs/34701945968). Evidenze JSON Mac scaricate e SHA-256 verificate.

| Test ufficiale | Esito |
| --- | --- |
| Public Linear Mainnet BTCUSDT WS | PASS: ticker reale ricevuto |
| REST Mainnet /v5/market/time | FAIL: HTTP 403, limite esterno |
| REST Demo ufficiale /v5/market/time | FAIL: HTTP 403, limite esterno |
| WS privato Demo /v5/private | FAIL: HTTP 403, limite esterno |
| Auth, saldo, UID, UTA/Hedge, create/fetch/cancel, execution, mini Grid e TP sul conto Demo | NON VERIFICATO |

Credenziali Demo ricevute, non utilizzate. Ordini ufficiali inviati: 0. Il REST e il WS privato hanno rifiutato l’accesso dai runner disponibili; il motivo del rifiuto non è dedotto. Nessun VPN, proxy alternativo, Testnet o altro dominio usato per aggirarlo. [Demo Trading ufficiale](https://bybit-exchange.github.io/docs/v5/demo).

## Verifiche esterne NON ESEGUIBILI / NON VERIFICATE

- Developer ID, notarizzazione e Gatekeeper dopo download con quarantena: certificati/credenziali Apple assenti; firma ad-hoc con Hardened Runtime verificata.
- macOS Monterey 12.6.8 sul dispositivo utente: target bundle/Mach-O 12.0 verificabile in build; i runner disponibili 15.7.9 non sostituiscono l'esecuzione su Monterey.
- VM clean install senza alcuna toolchain presente e upgrade effettivo tra versioni: non eseguiti; PATH/ambiente puliti, database esistente e struttura esterna al bundle verificati.
- Connessione e trading sul conto Bybit ufficiale: blocco HTTP 403 sopra; non è una mancanza delle API ricevute.

## Errori trovati, corretti e ritestati

| Tentativo | Errore rilevato | Correzione / esito successivo |
| --- | --- | --- |
| 34697731586 | Audit realtime senza ID/time; greenlet mancante nel runtime Mac | Commit prima della pubblicazione dei metadati; dipendenza async esplicita e hidden import; suite e freeze successivi PASS |
| 34698408928 Intel | Race della fixture saldo Recovery nel post-build | Saldo autorevole sul server, attesa wallet LONG/SHORT; cinque ripetizioni e suite complete successive PASS |
| 34699982993 | pip 25.0.1: 12 advisory records | Bootstrap pip 26.2.1 fissato; audit successivi Linux/Mac zero vulnerabilità |
| 34700762086 | Timeout del harness WKWebView: comando QA escluso dai permessi | Comando aggiuntivo rimosso; callback nativo per leggere risultati reali; IPC consentiti invariati |
| 34701789380 ARM | Assunzione timing heartbeat 5ms su runner condiviso | Osservati dieci pong consumati con callback bloccata; 20 ripetizioni e suite complete PASS |
| 34701789380 Intel / 34702435667 ARM | Timeline erroneamente attesa vuota alla seconda apertura | Confronto con audit reali persistiti; test native finali PASS |

Le build con test falliti non sono promosse. L’ultima candidatura usa output puliti e l’intera suite ripetuta post-build. Consultare BUILD_MANIFEST.json e CANDIDATE_MANIFEST.json per versioni, date, architetture, esiti e SHA-256 del DMG. Le sorgenti compilate e la documentazione finale possono avere commit diversi solo per l’aggiornamento dei Markdown.

**Accettazione operativa finale: NON SUPERATA finché il percorso sul conto Demo ufficiale non è dimostrato.**
