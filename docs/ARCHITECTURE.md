# Architettura

Una sola logica strategica opera sugli adapter DEMO/LIVE. Gli adapter hanno endpoint
immutabili derivati da Environment e ricontrollati immediatamente prima delle richieste.
L'ambiente e l'UID verificato vincolano la persistenza. La UI non riceve mai i secret.

| Responsabilità | Moduli |
| --- | --- |
| V5 REST, firma, errori e limiti | exchange.py, account.py, environments.py |
| Credenziali | credentials.py, macOS Keychain |
| WS exchange, heartbeat, buffer e reconnect | websocket.py |
| Grid assoluta e ripetizione dei tocchi | grid.py |
| State machine, intenzioni e TP | orders.py, state_machine.py |
| Rischio prima di ogni invio | risk.py |
| Matematica Recovery e indicatori | recovery.py, indicators.py |
| PnL netto, funding, baseline UTC | pnl.py, valuation.py |
| Coordinamento e lifecycle | runtime.py, connection.py, realtime.py, recovery_coordinator.py, closure.py |
| Target Recovery dopo BE economico | recovery_targets.py, indicators.py |
| Ledger e migrazioni | persistence.py, schema.py, migrations/ |
| Riconciliazione | reconciliation.py |
| API locale e WebSocket frontend | api.py |
| Interfaccia | frontend/src/ |
| Processo desktop e pacchetto | desktop/src/, scripts/ |

## Integrità

SQLite usa WAL, synchronous FULL, foreign keys e transazioni. Prezzi, quantità e
commissioni sono Decimal in Python e stringhe decimali nel ledger, evitando il
passaggio attraverso il REAL SQLite. Le migrazioni 0001/0002 creano lo schema e il
ledger funding. Sono preparati servizi SQLAlchemy che potranno essere adattati a
PostgreSQL; la migrazione al server non è già implementata.

OrderManager salva l'intenzione e il client ID prima della mutazione exchange. Se
l'ACK viene perso, non reinvia. La riconciliazione cerca ID nell'API realtime e nella
history e recupera execution effettive. Un'intenzione persistita ma non reperibile
resta incerta e blocca gli ingressi, anche se ciò richiede review manuale.

L'applicazione conserva l'entry eseguita, le quantità residue, i costi residui e le
allocazioni realizzate dei close in una sola transazione. Un execution ID è unico;
dati contraddittori per lo stesso ID producono errore. FILLED non nasce dal desiderio
della strategia: necessita di report exchange/execution confermati. Un report Filled
che precede il ledger blocca temporaneamente gli ingressi fino alla riconciliazione.

La coda WebSocket separa la lettura/pong dal processing business. Un actor lock
serializza tick, execution, reconciliation e interventi manuali. Gli stati di
connessione vengono invalidati immediatamente, anche se l'actor è occupato.
Ogni errore che impedisce la consistenza produce DEGRADED e reconciled=false.
Un funding già letto ma ancora in coda rende indisponibile l'autorizzazione
all'invio; la lettura dei pong continua durante le attese del database.
Il veto sincrono viene ripetuto dopo la persistenza dell'intenzione e all'interno
del semaforo REST immediatamente prima della richiesta HTTP.

Lo storico REST usa finestre contigue e paginazione. L'ultima finestra omette
endTime e riserva margine rispetto agli intervalli impliciti ufficiali: 7 giorni
per execution e 24 ore per transaction log. Un piccolo ritardo del clock
sincronizzato non tronca così gli eventi appena liquidati sul server.
Lo storico execution richiede esplicitamente execType=Trade: Funding, Delivery e
Settle sono movimenti distinti dalle normali esecuzioni. Il funding entra dal
transaction ledger; una divergenza di posizione non ricostruibile sospende il bot.

## Desktop e sicurezza locale

Tauri avvia un Python sidecar congelato con porta casuale e token effimero. Il server
ascolta solo 127.0.0.1. API/WS richiedono autenticazione e origine locale autorizzata;
Host/CSP/input/path controllati. Il token è solo in memoria desktop/frontend e non è
una chiave Bybit. Nessun comando shell o percorso fornito dalla UI viene eseguito.

La finestra diventa pronta soltanto dopo health del sidecar e frontend. La chiusura
sospende la strategia e termina i processi; non chiude posizioni exchange. Una pipe
posseduta dal parent permette al backend di sospendersi anche dopo crash del wrapper.
Gli aggiornamenti sostituiscono il bundle e lasciano database/Keychain nella directory
utente. Il collaudo effettivo di questo lifecycle su Mac è ancora da eseguire.

## Confini verificabili

Il Local Simulator dei test è un server HTTP/WS reale loopback con firma V5 verificata,
fault controllati e stato separato. Non conferma compatibilità del servizio ufficiale.
Le prove software locali, il backend incorporato Linux e le prove native Mac hanno
risultati distinti nel report. Non c'è alcuna conversione di una prova non eseguita in PASS.
