# Known issues — 0.1.0 candidatura locale

**Accettazione operativa Bybit Demo non superata. Non è una release definitiva.**

Entrambi i candidati Intel/Apple Silicon hanno superato build nativa, montaggio/copia
DMG, apertura/riapertura WKWebView, Keychain, CA incorporate, persistenza e crash
sidecar, con suite complete post-build. Le build fallite precedenti sono escluse.

## Verifiche non completate

| Componente | Stato | Limite reale |
| --- | --- | --- |
| Conto Bybit Demo: saldo, UTA/Hedge, ordini, execution, Grid/TP | NON VERIFICATO | REST Mainnet/Demo e WS privato Demo HTTP 403 da Linux e Mac; API ricevute ma non usate |
| Feed pubblico ufficiale | PASS nei probe remoti | Ticker BTCUSDT reale; dati account e feed dentro l'app con conto Demo non verificati |
| LIVE account / trading | NON VERIFICATO | Default disabilitata; nessun ordine reale durante sviluppo |
| Developer ID, notarizzazione, Gatekeeper download | NON VERIFICATO | Certificati Apple assenti; firma ad-hoc Hardened Runtime verificata |
| macOS 15.5 esatto / dispositivo utente | NON VERIFICATO | Runner Mac 15.7.9 reali verificati, hardware utente non disponibile |
| Clean VM senza toolchain / upgrade tra versioni | NON VERIFICATO | Ambiente/PATH senza runtime esterni e riapertura con DB persistente verificati |
| Revisione grafica manuale completa | NON VERIFICATO | Catture Home offline e controlli DOM WKWebView; non screenshot di tutte le pagine |

Su finestre basse la Home richiede scorrimento per tutte le card/PnL.

Gli audit pip/npm e cargo non hanno vulnerabilità bloccanti. Cargo conserva sei
avvisi di dipendenze non mantenute e l'avviso GLib RUSTSEC-2024-0429. I grafi nativi
Mac provano GLib assente; i crate Unicode upstream presenti restano un limite di
manutenzione. Nessun avviso è ignorato con opzioni dell'audit.

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
- Alla riapertura un conto già verificato viene riconnesso dal Keychain e riconciliato
  senza riattivare ingressi. Un timeout entro 20 secondi o credenziali non accessibili
  lascia l'app aperta in pausa di sicurezza; serve risolvere l'errore prima di Avvia.
  Il primo conto richiede ancora Test Connessione. Su Linux development le credenziali
  non persistono e il collegamento va richiesto dopo ogni riavvio.
- Commissioni future e slippage sono stime esplicite. Funding già liquidato entra nel
  target Recovery; funding futuro e impatto del mercato non sono prevedibili. Un TP non
  garantisce il profitto finale in presenza di gap o esecuzioni differenti dal modello.
- Se la tariffa account non è leggibile viene mostrata una stima conservativa distinta
  dalle fee effettive. La compatibilità di questa lettura nel servizio Demo ufficiale
  richiede il collaudo account esterno.
- PnL Oggi usa la candela mark delle 00:00 UTC e il ledger ricostruito. Non è un tick
  storico esatto dell'account. Assenza della candela richiesta blocca nuovi ingressi.
- Su Linux le credenziali sono solo in memoria, per sviluppo. Su macOS i secret
  persistono nel Keychain nativo, collaudato con il backend incorporato nell'app.
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
