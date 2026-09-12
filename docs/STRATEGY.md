# Strategia Grid Hedge

La stessa `GridEngine` riceve prezzi reali in DEMO/LIVE oppure eventi storici nei test. DEMO indica esclusivamente Bybit Demo Trading. Il motore non produce prezzi né risultati sintetici per l'interfaccia.

## Reticolo assoluto

Il prezzo iniziale `P0` resta fisso per la sessione. Con spaziatura frazionaria `s = spacing_pct/100`, il passo è `d = P0*s`. Il livello intero `i` ha prezzo `floor_tick(P0 + i*d)`. La finestra contiene X livelli sotto il centro e X sopra; il centro corrisponde alla cella del prezzo osservato. I prezzi dei livelli sovrapposti non cambiano quando la finestra scorre. Gli indici possono essere negativi.

La classificazione della cella usa i prezzi già normalizzati al tick: anche con un passo non multiplo del tick, i livelli della finestra restano X sotto e X sopra il mercato. Il reticolo iniziale deve avere prezzi positivi, passo almeno pari al tick e `2*hysteresis < d`. Una finestra futura non valida provoca un errore e richiede sospensione della strategia.

## Attraversamenti e riuso

Un livello L ha due confini, `L-h` e `L+h`. Il primo evento arma il lato senza generare ordini. Un attraversamento valido passa da un lato armato al confine del lato opposto; la semplice uguaglianza con L e le vibrazioni interne alla fascia non generano coppie.

Ogni livello conserva una sequenza crescente e l'ultimo timestamp di touch. Un attraversamento entro `debounce_ms` viene consumato senza creare una coppia: non viene rinviato al termine del debounce. Quando la finestra scorre, il confine della cella appena attraversato resta osservato internamente, così l'attraversamento inverso dello stesso livello non viene perso. La lista pubblica rimane di 2X livelli.

Un salto di prezzo genera touch solamente dei livelli precedentemente attivi, in ordine crescente in salita e decrescente in discesa. I livelli aggiunti dopo il salto vengono armati al nuovo prezzo senza retroattivamente generare ordini. Eventi duplicati o con timestamp precedente all'ultimo prezzo applicato non modificano lo stato.

Snapshot JSON e ripristino conservano anchor, finestra, hysteresis, debounce, lato armato, sequenze e ultimo touch. L'orchestratore persiste lo snapshot e il claim del touch prima di inviare la coppia; riconciliazione exchange e identificativi deterministici sono necessari per l'idempotenza degli ordini.

## Coppie e take profit

Ogni touch autorizzato propone un LONG (`positionIdx=1`, Buy) e uno SHORT (`positionIdx=2`, Sell). Ogni singola richiesta passa dal Risk Engine. Una coppia non è una transazione atomica Bybit: se una gamba viene rifiutata o ha stato incerto, nuovi ingressi devono essere sospesi e riconciliati.

Il TP deriva dall'entry effettivamente eseguita: LONG `entry*(1+tp_pct/100)`, SHORT `entry*(1-tp_pct/100)`. Si arrotonda verso l'alto per LONG e verso il basso per SHORT, per non ridurre il TP lordo richiesto. Il TP usa il lato di chiusura e `reduceOnly` sullo stesso indice hedge della posizione.

Le quantità richieste o ancora pending non entrano nel prezzo medio né nel Recovery. L'assenza di stop loss automatico non evita perdite, liquidazione o esaurimento del margine; i limiti bloccano nuovi ingressi e non garantiscono un rendimento.

## Supporti e resistenze

`SupportResistanceEngine` valida OHLCV reali, ordina i timestamp e rifiuta duplicati o candele incoerenti. L'ultima candela è esclusa perché può essere ancora aperta. Usa pivot confermati con due barre a sinistra e destra, ATR14 Wilder, EMA20 inizializzata con SMA, estremi delle ultime 20 barre e high/low della barra precedente.

I candidati vengono raggruppati entro `max(0.35*ATR, 0.0001*price)`. La media dei candidati forma un livello. S1/S2 sono i due livelli più vicini sotto il prezzo; R1/R2 quelli sopra. Lo score 0–100 somma confluence delle fonti (fino a 30), recency (20), volume osservato relativo al massimo (20) e touch storici (fino a 30). È uno score tecnico deterministico, non una probabilità di successo. Dati insufficienti producono `null`, non livelli inventati. S/R non sostituisce il calcolo del TP netto Recovery.

La riproduzione di eventi storici nei test verifica la medesima logica grid; non costituisce un backtest di rendimento con order-book, latenza e funding realistici.
