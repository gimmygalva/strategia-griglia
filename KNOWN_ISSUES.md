# Known issues — 0.1.0 candidatura locale

**Accettazione operativa Bybit Demo non superata. Non è una release definitiva.**

Aggiornamento del 12 settembre 2026: il repository GitHub è collegato e la CI è
stata eseguita su Linux, Mac Intel e Apple Silicon. Il pacchetto Apple Silicon
è stato generato, montato, copiato, aperto e riaperto, anche dopo kill del backend.
I primi errori audit WebSocket e `greenlet` sono corretti. Un test Recovery
post-build Intel ha poi rilevato una race nella fixture del saldo; corretta usando
il saldo autorevole del server di test. È in corso la nuova build di entrambe le
architetture, con verifiche aggiuntive Keychain, finestra visibile e audit dipendenze.
Le credenziali Demo ricevute restano escluse dai sorgenti e dagli artefatti.

## Blocchi esterni alla verifica

| Componente | Stato | Cosa manca |
| --- | --- | --- |
| Bybit Demo ufficiale: saldo, account, ordini, execution, mini Grid | NON VERIFICATO | REST ufficiale e WS privato hanno restituito HTTP 403 nel controllo remoto; credenziali ricevute, non utilizzate |
| Feed Bybit pubblico ufficiale | PASS nel probe remoto | Ticker BTCUSDT reale ricevuto dal WS pubblico Mainnet; feed nell'app sul conto Demo non verificato |
| Mainnet reale | NON VERIFICATO | Collaudo account senza trading reale; i test di sviluppo non inviano ordini LIVE |
| Rust/Tauri nativo | PASS su entrambe le architetture nella build precedente | Nuova build richiesta per gli ultimi controlli |
| `Grid Hedge Bot.app` / `Grid Hedge Bot.dmg` | GENERATI su Apple Silicon | Nuova build Intel/Apple Silicon con tutti i test prima dell'approvazione |
| Montaggio DMG, apertura e persistenza Mac | PASS su Apple Silicon nella build precedente | Nuova build completa e verifica Keychain in corso |
| macOS Keychain | NON VERIFICATO sulla build attuale | Collaudo nativo del backend incorporato predisposto nella nuova CI |
| Developer ID / notarizzazione | NON VERIFICATO | Certificato e credenziali Apple; build ad-hoc predisposta |
| Rendering visivo manuale delle schermate | NON VERIFICATO | WKWebView già avviata; nuova verifica finestra visibile e cattura schermo in CI, distinta dai test DOM |
| Audit vulnerabilità dipendenze Python/Rust | NON VERIFICATO sulla build attuale | Nuova CI dedicata pip-audit/cargo-audit; audit npm frontend/desktop già superati |

Gli esiti di ciascun pacchetto nativo sono nel report e nel suo manifest, associati
alla specifica architettura e build. Il controllo della struttura di firma ad-hoc
non dimostra che Gatekeeper accetti una nuova app scaricata con quarantena.
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
- `Cargo.lock` è ora conservato nel repository dalla build nativa validata;
  build e test Rust utilizzano `--locked`.

## Funzioni successive all'MVP

Il motore Grid è condivisibile con replay storico ed è collaudato su sequenze di
prezzi. Non è consegnata una UI completa di backtest, né analytics avanzate.
Drawdown e aggregazioni di execution latency, recovery success rate e Grid TP rate
non sono ancora esposti come un servizio metriche completo; gli eventi di base,
execution, fee, PnL e latenza REST sono disponibili per gli sviluppi successivi.
Notifiche applicative sono registrate e trasmesse alla UI; notifiche native desktop,
Telegram, email e un updater automatico rimangono estensioni future.
La migrazione operativa a PostgreSQL non è implementata.

Il report distingue risultati storici e build attuale. Un test critico fallito
impedisce l'approvazione del pacchetto; le verifiche Bybit e Apple mancanti restano
esplicite anche se le suite automatiche dell'app passano.
