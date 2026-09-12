# Known issues — 0.1.0-dev

**Questa consegna contiene sorgenti e prove locali. Non è una release macOS definitiva.**

## Blocchi esterni alla verifica

| Componente | Stato | Cosa manca |
| --- | --- | --- |
| Bybit Demo ufficiale: saldo, account, ordini, execution, mini Grid | NON VERIFICATO | Credenziali Demo dell'utente e rete utilizzabile dal processo dell'app |
| Feed Bybit pubblico ufficiale | NON VERIFICATO | Connessione esterna: REST diretto fallisce, WebSocket non risolve il dominio, proxy esplicito va in timeout |
| Mainnet reale | NON VERIFICATO | Collaudo account senza trading reale; i test di sviluppo non inviano ordini LIVE |
| Rust/Tauri nativo | NON VERIFICATO | Toolchain Rust e macOS; il codice desktop non è stato compilato in questa sessione |
| `Grid Hedge Bot.app` / `Grid Hedge Bot.dmg` | NON GENERATI | Mac Intel / Apple Silicon con toolchain nativa |
| Montaggio DMG, apertura, clean install e upgrade Mac | NON VERIFICATO | Pacchetto nativo e macchina macOS |
| macOS Keychain e permessi nativi | NON VERIFICATO | API di sistema macOS; verificata solo l'interfaccia con backend controllato |
| Developer ID / notarizzazione | NON VERIFICATO | Certificato e credenziali Apple; build ad-hoc predisposta |
| Rendering manuale e smoke UI nel browser / WKWebView | NON VERIFICATO | Il browser disponibile blocca l'URL locale; le prove React usano jsdom |
| Audit vulnerabilità dipendenze Python | NON VERIFICATO | pip-audit installato ed eseguito; la richiesta alle advisory PyPI va in timeout. Audit npm frontend/desktop eseguiti separatamente |

Un backend incorporato Linux funzionante non dimostra che un bundle Mac si apra.
Gli script e la CI preparati non sono una build macOS già eseguita. Non esiste un
file rinominato `.dmg` per nascondere questo limite.
Le prove DOM React con traffico HTTP/WS reale sostituiscono il bridge nativo Tauri
e il canvas non disponibili in jsdom: non equivalgono a un collaudo visivo dell'app Mac.

## Limiti operativi documentati

- Supportato inizialmente BTCUSDT, USDT perpetual, UTA compatibile con Hedge Mode.
  Richiesto account/subaccount dedicato: ordini o posizioni esterne divergenti
  producono blocco. Non è implementata l'importazione automatica di posizioni manuali.
- Un database è vincolato all'UID verificato. Non si riutilizza lo stesso ledger
  per un nuovo conto; conservare il database originale e usare dati separati.
- Un'intenzione persistita non trovata dall'exchange resta incerta. Non è disponibile
  una schermata per annullare manualmente l'incertezza: serve review del ledger/exchange.
  Reinviare alla cieca sarebbe incompatibile con la prevenzione dei duplicati.
- Un crash tra registrazione del blocco Recovery e registrazione dell'intenzione
  dell'injection richiede review. Il bot blocca nuovi ingressi e conserva i TP esistenti.
- Una sola injection attiva alla volta; durante Recovery gli ingressi grid sono sospesi.
  Non è implementata una sequenza automatica di injection multiple sul medesimo blocco.
- Le due gambe hedge non sono atomiche sull'exchange. Se la seconda fallisce, quella
  già confermata resta protetta e il bot si sospende; non viene compensata automaticamente.
- I TP esistono sull'exchange anche a programma chiuso. I nuovi TP richiedono il processo
  locale o la successiva riconciliazione. Tra fill e conferma del TP, oppure durante una
  sostituzione confermata, esiste un intervallo senza nuova protezione: il mercato e la
  disponibilità dell'exchange impediscono una garanzia di esecuzione atomica.
- Aggiornamenti ordine/posizione arrivati prima delle execution possono provocare una
  pausa conservativa. Dopo riconciliazione servono conferma e Avvia per nuovi ingressi.
- Alla riapertura il ledger locale viene caricato, ma la connessione account deve essere
  richiesta con Test Connessione prima di Avvia. Non è implementato un reconnect
  automatico dell'account dal Keychain durante l'inizializzazione del backend.
- Commissioni future e slippage sono stime esplicite. Funding già liquidato entra nel
  target Recovery; funding futuro e impatto del mercato non sono prevedibili. Un TP non
  garantisce il profitto finale in presenza di gap o esecuzioni differenti dal modello.
- Se la tariffa account non è leggibile viene mostrata una stima conservativa distinta
  dalle fee effettive. La compatibilità di questa lettura nel servizio Demo ufficiale
  richiede il collaudo account esterno.
- PnL Oggi usa la candela mark delle 00:00 UTC e il ledger ricostruito. Non è un tick
  storico esatto dell'account. Assenza della candela richiesta blocca nuovi ingressi.
- Su Linux le credenziali sono solo in memoria, per sviluppo. La persistenza definitiva
  dei secret è progettata per macOS Keychain, non per un keyring plaintext alternativo.
- `Cargo.lock` deve essere risolto e conservato sulla prima build nativa validata.
  La risoluzione Rust non è stata eseguita in questo ambiente privo di Cargo.

## Funzioni successive all'MVP

Il motore Grid è condivisibile con replay storico ed è collaudato su sequenze di
prezzi. Non è consegnata una UI completa di backtest, né analytics avanzate.
Drawdown e aggregazioni di execution latency, recovery success rate e Grid TP rate
non sono ancora esposti come un servizio metriche completo; gli eventi di base,
execution, fee, PnL e latenza REST sono disponibili per gli sviluppi successivi.
Notifiche applicative sono registrate e trasmesse alla UI; notifiche native desktop,
Telegram, email e un updater automatico rimangono estensioni future.
La migrazione operativa a PostgreSQL non è implementata.

Il report elenca i risultati effettivi dell'ultima suite. Non risultano test locali
falliti lasciati senza correzione alla consegna; le verifiche esterne sopra impediscono
comunque di dichiarare completato il flusso operativo macOS + Bybit Demo.
