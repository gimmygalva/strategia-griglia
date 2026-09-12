# Acceptance checklist — 0.1.0-dev

Le caselle software si riferiscono a prove locali, non al servizio Bybit ufficiale.
Consultare TEST_REPORT.md per conteggi, data ed evidenze.

- [x] Backend Python compilato e avviato realmente
- [x] Frontend compilato e server Vite avviato realmente
- [x] Database vuoto, migrazioni 0001/0002 e database esistente
- [x] Adapter DEMO distinto da Testnet; endpoint immutabili e test di parità LIVE
- [x] Mainnet disabilitata per default, flag backend e doppia conferma scritta
- [x] UTA, permessi e Hedge Mode verificati contro server HTTP/WS controllato
- [x] Grid, TP, Dynamic Shift, crossing ripetuto, hysteresis e debounce
- [x] Execution parziali, duplicati e aggiornamenti fuori ordine
- [x] Matematica injection, fee, slippage, break-even e rischi
- [x] Recovery attivo, TP, chiusura e funding economico
- [x] Riconciliazione e restart; processo realmente terminato con SIGKILL
- [x] Intenti persistiti prima dell'invio; nessun reinvio cieco dopo ACK perso
- [x] Pause di sicurezza per rete, ledger, stato incerto e daily loss
- [x] Test sicurezza locale, secret non restituiti e non nel database/log/bundle
- [x] Test React di Home, Attività, Impostazioni, Wizard e conferme
- [x] Prova DOM React con backend HTTP/WS reale e controlli del bot
- [x] Backend congelato Linux con frontend incorporato, HTTP/WS e persistenza
- [x] Schema Tauri, asset icona `.icns`, script build e CI predisposti
- [ ] Collegamento e ordini sul Bybit Demo Trading ufficiale
- [ ] Mini Grid Demo ufficiale con order ID ed execution verificati
- [ ] Feed pubblico ufficiale osservato dal processo dell'app
- [ ] macOS Keychain verificato sul sistema reale
- [ ] Rust/Tauri compilato nativamente
- [ ] `Grid Hedge Bot.app` generata e aperta su Mac
- [ ] `Grid Hedge Bot.dmg` generato e montato su Mac
- [ ] Clean install macOS senza runtime esterni
- [ ] Riapertura, upgrade e persistenza nell'app Mac installata
- [ ] Sanity check manuale di UI e WKWebView

**Accettazione operativa finale: NON SUPERATA.** Mancano verifiche esterne esplicite,
non sostituite da risultati del simulatore locale.
