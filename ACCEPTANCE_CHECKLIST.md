# Acceptance checklist — 0.1.0 candidatura locale

Le caselle indicano il preciso ambito verificato, non l'accettazione sul conto
Bybit ufficiale. Risultati e date in TEST_REPORT.md e BUILD_MANIFEST.json.

- [x] Backend compilato/avviato e API/WS locali autenticati
- [x] Frontend compilato, Vite realmente avviato, 95 test React ed E2E reale con Local Simulator
- [x] SQLite vuoto/esistente, migrazioni, integrità, transazioni e guasti DB
- [x] DEMO ufficiale distinto da Testnet; endpoints, namespaces e parità adapter LIVE
- [x] Mainnet false di default; conferme UI scritte e veto backend
- [x] UTA/permessi/Hedge validati nel Local Simulator; LONG/SHORT positionIdx distinti
- [x] Grid/TP/shift/crossing ripetuti/hysteresis/debounce nei test condivisi
- [x] Fills parziali, duplicati, fuori ordine, 429/5xx/timeout/WS reconnect
- [x] Recovery/injection/fee/slippage/break-even/exposure/daily loss matematici e integrati
- [x] Crash/reconciliation/persistenza, SIGKILL reale, nessun reinvio cieco
- [x] Riapertura automatica conto verificato da interfaccia persistente senza Start
- [x] Secret protetti nei test API/frontend/DB/log; Keychain nativo con credenziali sintetiche
- [x] CA TLS incorporate e handshake HTTPS/WSS reali, hostname/CA errati bloccati
- [x] Rust/Tauri nativi Intel/ARM; 6 test Rust e clippy per architettura
- [x] Grid Hedge Bot.app / .dmg reali generati per Intel e Apple Silicon
- [x] DMG montato, app copiata/aperta/chiusa/riaperta, DB persistente e sidecar kill/restart
- [x] WKWebView reale: 10 controlli a entrambe le aperture, timeline confrontata con backend
- [x] App usa PATH/ambiente puliti senza richiedere Python/Node/Docker esterni
- [x] Firma ad-hoc valida e Hardened Runtime effettivo
- [x] Audit dipendenze senza vulnerabilità bloccanti; avvisi Rust conservati
- [x] Probe WS ufficiale pubblico BTCUSDT con ticker reale
- [ ] Auth/saldo/UID/UTA/Hedge/ordini/execution/mini Grid/TP sul Bybit Demo ufficiale
- [ ] Feed/account Demo ufficiale osservati dal processo della app
- [ ] macOS Monterey 12.6.8 esatto sul dispositivo utente
- [ ] Clean VM privata fisicamente di ogni toolchain
- [ ] Upgrade reale tra versioni diverse
- [ ] Developer ID, notarizzazione, Gatekeeper dopo download con quarantena
- [ ] Sanity check grafico manuale completo di ogni schermata con conto Demo

**Accettazione operativa finale: NON SUPERATA.** Il probe HTTP 403 è un limite
esterno; non è mascherato da PASS o da una simulazione chiamata Demo.
