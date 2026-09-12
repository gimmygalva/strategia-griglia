# Gestione del rischio

Ogni richiesta di apertura o riduzione passa da `RiskEngine.validate_order` (`validateOrder` è un alias della stessa implementazione). In stato incerto il motore rifiuta l'ordine.

## Gate comuni

Ambiente richiesta e account devono coincidere. LIVE richiede contemporaneamente flag backend e conferma UI; DEMO non utilizza mai Testnet. Sono obbligatori exchange connesso, stato riconciliato, permessi trading, Hedge Mode verificato, simbolo coerente e identificativo non duplicato. Tipo ordine, prezzo/quantità positivi e finiti, qtyStep, tickSize, min/max qty, max market qty e leverage sono validati prima dell'invio. Input non valido provoca `RiskError`.

Una riduzione usa LONG/SHORT e `positionIdx` della stessa posizione di proprietà del bot. La quantità non può superare `position_qty` già riconciliata. Una posizione manuale esterna non autorizza una riduzione del bot.

Prezzo last e mark devono essere entrambi aggiornati da meno di 15 secondi.
Un funding privato ricevuto ma ancora in attesa dell'actor blocca nuovi invii
fino alla registrazione e riconciliazione. Il controllo viene ripetuto dopo
ogni attesa critica, anche dopo la transazione dell'intenzione e dopo la coda
del semaforo REST. Un veto locale certo registra ORDER_NOT_SENT e REJECTED;
un timeout dopo l'avvio HTTP mantiene invece l'esito incerto e la riserva.

## Aperture

Servono inoltre bot RUNNING, saldo non negativo e PnL giornaliero strettamente maggiore di `-max_daily_loss_usdt`. Al limite esatto nuovi ingressi sono bloccati. GRID/INITIAL rispettano Order Size; RECOVERY rispetta Max Injection e Max Recovery Exposure. Il nozionale minimo usa LTP per Market; per Limit Buy usa `min(price,1.05*LTP)`, per Limit Sell `max(price,0.95*LTP)`, secondo le [regole ufficiali Bybit](https://www.bybitglobal.com/en/help-center/article/Derivatives-Trading-RulesUnified_Trading_Risk_management).

Exposure è **lordo**: LONG e SHORT si sommano. Un hedge non nasconde consumo di margine. Il runtime deve fornire exposure di tutte le posizioni rilevanti per l'account e le riserve di ordini non ancora ricostruiti in posizioni.

Per un nuovo ordine, N avverso è `qty*max(market,limit_price)*(1+slippage)`; R è il nozionale riservato con slippage configurato. Il controllo di saldo usa `(N+R)/leverage + 2*(N+R)*taker_fee`, accantonando collateral e fee di entrata/uscita. Max Total Exposure confronta `current_exposure+N+R`; Recovery confronta anche `current_recovery_exposure+N+R`. È una stima conservativa di margine, non il calcolatore proprietario di liquidazione Bybit.

Il runtime deve aggiornare riserve ed execution in modo serializzato e transazionale. Un timeout di creazione non libera una riserva e non autorizza un reinvio alla cieca: prima si interroga l'exchange tramite orderLinkId e si riconcilia.

Durante RUNNING o Recovery attivo è modificabile soltanto Auto Recovery ON/OFF.
La modifica è serializzata, persistita e auditata con valori precedenti e nuovi;
non altera Grid, sessione, quantità o protezioni. Tutti gli altri parametri sono
bloccati. OFF impedisce nuove injection automatiche ma conserva la gestione dei
TP del blocco già attivo. ON continua a richiedere ogni gate del Risk Engine.

Il PnL giornaliero misura i movimenti dall'inizio del giorno UTC: PnL realizzato meno fee e più funding del giorno, più PnL non realizzato attuale al mark, meno PnL non realizzato a mezzanotte. Il baseline ricostruisce quantità e costo residui dalle execution precedenti al giorno e usa il mark storico di mezzanotte. Un ingresso parzialmente chiuso e poi riempito nuovamente pesa soltanto il costo residuo al nuovo fill, evitando la media cumulativa teorica dell'ordine. Storico o mark necessari non disponibili bloccano il trading; non viene azzerata arbitrariamente la perdita overnight.

## Riduzioni e stop

TP, RECOVERY_TP e CLOSE `reduceOnly` possono ridurre posizioni durante PAUSED o dopo Daily Loss, anche con saldo disponibile nullo. Mantengono i gate comuni, min qty/step e max qty. Le chiusure sono esenti da minNotional, ma restano soggette a minQty, come confermano le [regole Bybit](https://www.bybitglobal.com/en/help-center/article/Derivatives-Trading-RulesUnified_Trading_Risk_management). Una quantità residua inferiore a minQty richiede gestione esplicita; il motore non apre quantità aggiuntiva per eliminare dust.

STOP blocca nuovi ingressi e cancella soltanto richieste d'ingresso del bot ancora cancellabili. Mantiene posizioni e TP exchange. CHIUDI TUTTO è un'azione separata con conferme UI, e riduce esclusivamente le posizioni del bot sul simbolo configurato. Chiudere la finestra non invia chiusure di posizione.

I limiti impediscono nuove richieste oltre budget; non eliminano perdite o liquidazioni già possibili sulle posizioni esistenti. UTA cross margin e fondi condivisi rendono opportuno un subaccount dedicato. Il software non usa un limite di exposure netto LONG meno SHORT per autorizzare nuove richieste.
