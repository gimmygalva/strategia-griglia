# Collegamento Bybit

## DEMO ufficiale

DEMO usa un account separato del servizio **Bybit Demo Trading**, con UID e chiavi propri. Non è Testnet. Accedi al tuo account normale, passa a Demo Trading e apri la gestione API dal profilo. Genera una chiave di sistema HMAC Read/Write abilitata al trading derivatives. Queste istruzioni seguono la [documentazione Demo ufficiale](https://bybit-exchange.github.io/docs/v5/demo).

Nell'app scegli **DEMO**, inserisci API Key e API Secret e premi **Test Connessione**. Non servono chiavi del conto Live. Non usare chiavi create su Testnet.

Gli endpoint sono fissati dal codice:

| Servizio | DEMO | LIVE |
| --- | --- | --- |
| REST privato | `https://api-demo.bybit.com` | `https://api.bybit.com` |
| WebSocket privato | `wss://stream-demo.bybit.com/v5/private` | `wss://stream.bybit.com/v5/private` |
| REST di mercato | `https://api.bybit.com` | `https://api.bybit.com` |
| WebSocket linear | `wss://stream.bybit.com/v5/public/linear` | `wss://stream.bybit.com/v5/public/linear` |

Il servizio Demo supporta flussi WebSocket privati e usa i dati pubblici Mainnet; non supporta il WebSocket per inviare ordini. Gli ordini sono inviati tramite REST. I record Demo sono conservati da Bybit per sette giorni. Riferimento: [Bybit Demo Trading](https://bybit-exchange.github.io/docs/v5/demo).

## Account e posizione

Questa versione richiede BTCUSDT USDT Perpetual, **Unified Trading Account con Cross Margin** e **Hedge Mode**. Il test connessione legge lo stato UTA tramite `/v5/account/info`; sono accettati gli stati 3, 4, 5 e 6. Isolated Margin e Portfolio Margin sono bloccati perché il calcolo della disponibilità richiede regole differenti. Riferimenti: [Account Info](https://bybit-exchange.github.io/docs/v5/account/account-info), [stati UTA](https://bybit-exchange.github.io/docs/v5/enum#unifiedmarginstatus).

Prima dell'avvio verifica la modalità di posizione nelle impostazioni derivatives di Bybit. Il bot legge `/v5/position/list` per BTCUSDT e richiede gli indici **1 Long** e **2 Short**. L'indice 0 indica One-Way Mode e viene rifiutato. Il programma non cambia Hedge Mode automaticamente. La possibilità di cambiare modalità sul sito dipende da posizioni e ordini già presenti. Riferimenti: [Position Info](https://bybit-exchange.github.io/docs/v5/position), [Switch Position Mode](https://bybit-exchange.github.io/docs/v5/position/position-mode).

Main Account e Subaccount seguono gli stessi controlli, purché l'account associato alla chiave soddisfi i requisiti. Usa preferibilmente un account dedicato al bot: eventuali operazioni manuali o altri bot sullo stesso simbolo possono rendere lo stato incoerente.

## Verifica dei permessi

Il controllo firma `/v5/user/query-api` con la chiave dell'ambiente selezionato. Richiede UID valido, Read/Write e permessi ContractTrade `Order` e `Position`, oppure Derivatives `DerivativesTrade`. La documentazione Demo corrente rimanda a questo endpoint anche per le chiavi Demo. Se la chiamata è indisponibile, il bot non presume che i permessi esistano e blocca la connessione. Riferimento: [Get API Key Information](https://bybit-exchange.github.io/docs/v5/user/apikey-info).

Non abilitare prelievi per il bot. Le chiavi RSA non sono supportate in questa versione. Mantieni data e ora del Mac sincronizzate: le richieste firmate usano timestamp UTC e finestra di validità limitata. Riferimento: [autenticazione V5](https://bybit-exchange.github.io/docs/v5/guide).

## Saldo, commissioni e leva

Equity proviene dal wallet UTA. Il budget disponibile è limitato sia dalla disponibilità di margine riportata dall'exchange sia dal saldo USDT effettivo al netto dei prestiti spot. L'equity non viene trattata come denaro libero. Riferimento: [Wallet Balance](https://bybit-exchange.github.io/docs/v5/account/wallet-balance).

Quando disponibile, `/v5/account/fee-rate` fornisce maker e taker rate. Se l'endpoint risponde esplicitamente “non disponibile” in DEMO, la previsione dei costi usa **0,06% per eseguito**, marcato come stima conservativa. Un altro errore non viene ignorato. Le commissioni contabilizzate del bot provengono sempre dalle executions reali. Riferimento: [Fee Rate](https://bybit-exchange.github.io/docs/v5/account/fee-rate).

La leva iniziale è 1x. Il bot non modifica la leva con posizioni o ordini esistenti. Dopo una modifica consentita, rilegge le posizioni per verificarla. Long e Short mantengono lo stesso valore in Cross Margin. Riferimento: [Set Leverage](https://bybit-exchange.github.io/docs/v5/position/leverage).

Il funding viene letto dal transaction log UTA con ID immutabili e finestre paginate. Il campo `funding` è positivo quando ricevuto e negativo quando pagato; `cashFlow` esclude funding e commissioni. La quantità riportata in una settlement non è una nuova execution. Se lo storico non è verificabile, il bot sospende i nuovi ordini. Riferimento: [Transaction Log](https://bybit-exchange.github.io/docs/v5/account/transaction-log).

Per ricostruire il giorno dopo un riavvio, il backend può leggere l'apertura della candela mark-price a mezzanotte UTC. Timestamp e simbolo devono corrispondere esattamente; una candela assente non viene sostituita con il prezzo corrente. Riferimento: [Mark Price Kline](https://bybit-exchange.github.io/docs/v5/market/mark-kline).

## LIVE

Crea una chiave HMAC Read/Write nel conto Live e salvala nella sezione LIVE. La connessione può leggere il conto, ma ogni mutazione resta disabilitata finché il backend non ha `ALLOW_MAINNET_TRADING=true` e la UI non registra entrambe le conferme, inclusa la frase **AVVIA LIVE**. Il valore predefinito è `false`. Nessun test di sviluppo deve inviare ordini Live.

Le credenziali DEMO e LIVE hanno spazi separati nel macOS Keychain. Il secret è disponibile solo al backend e non viene restituito alla UI. In Linux di sviluppo la memorizzazione è soltanto in RAM. Se il Keychain del Mac non è accessibile, il salvataggio fallisce senza ripiego su file in chiaro.

## Problemi di collegamento

| Stato | Azione |
| --- | --- |
| Authentication Failed | Controlla chiave HMAC, secret, ambiente, scadenza e whitelist IP. |
| Permission Missing | Verifica Read/Write e trading derivatives. |
| Network Error | Controlla rete, accesso ai domini Bybit e restrizioni del tuo account. |
| Account Type Error | Verifica UTA e Cross Margin. |
| Hedge Mode Error | Attiva Hedge Mode per BTCUSDT sul sito Bybit. |
| DEGRADED / PAUSED | Riconcilia account, ordini ed executions prima di riavviare. |

Il connettore non devia automaticamente verso domini regionali o Testnet. Se il conto richiede un dominio diverso, la connessione resta bloccata e quel profilo necessita di un adattatore verificato specifico.

La correttezza del protocollo è verificata dai test locali; il collegamento con un account ufficiale è **NON VERIFICATO** finché non vengono fornite chiavi Demo e una rete che raggiunga Bybit. I test locali non sono etichettati come Bybit Demo.
