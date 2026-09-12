# Smart Recovery: formule e limiti

`RecoveryEngine` separa LONG e SHORT e considera esclusivamente quantità residue già eseguite. Per ogni lato somma Q, costo nozionale `C = Σ(entry_i*qty_i)` e fee di ingresso effettivamente attribuite ai lotti residui. La media è `A = C/Q`. Una fee effettiva può essere negativa se rappresenta un rebate confermato; le stime di fee future restano nonnegative e conservative.

L'attivazione richiede una posizione contro-trend in perdita e distanza avversa dall'entry almeno pari a `recovery_threshold_pct`. Il PnL non realizzato mostrato è lordo; fee pagate e fee future sono distinte. Le quantità pending non vengono utilizzate.

## Media target

Con quantità aggiunta x al prezzo effettivo E, la media nuova è `T = (Q*A+x*E)/(Q+x)`. Risolvendo:

`x = Q*(A-T)/(T-E)`.

Per LONG in perdita deve valere `E<T<A`; per SHORT `A<T<E`. L'entry effettiva stimata è `E=M*(1+s)` per LONG e `E=M*(1-s)` per SHORT. Target al prezzo effettivo, dal lato sbagliato o oltre la media originale sono irraggiungibili e producono un errore, senza quantità di fallback.

`InjectionCalculator.calculate` riceve fee/slippage come frazioni: 0.0006 indica 0.06%, 0.001 indica 0.10%. Il piano riporta quantità, capitale nozionale al prezzo effettivo, nuova media, fee stimate e prezzo di uscita richiesto per il target netto.

## Break-even e target netto

Prima dell'attivazione, F comprende fee d'ingresso residue già pagate e fee stimate dell'injection; f è la fee futura di uscita; s lo slippage avverso di uscita; H il profitto netto desiderato.

Per un blocco già attivo, `recovery_exit_budget` ricostruisce invece il costo economico equivalente sull'intera operazione a partire dalla membership persistita e dai movimenti effettivi:

`F = fee GRID residue all'attivazione + fee effettive injection + fee chiusure dei membri dopo attivazione - PnL lordo realizzato da tali chiusure - funding effettivo dello stesso lato dopo attivazione`.

Q e A nelle formule seguenti sono quantità e media **ancora aperte**. Il PnL già realizzato durante un handoff o un TP parziale viene sottratto dal costo residuo necessario, mentre una perdita o un funding pagato lo aumenta. F può quindi essere negativo senza rappresentare un errore. Le fee allocate alle chiusure non si aggiungono di nuovo come fee d'ingresso: il costo iniziale e quello dell'injection sono già compresi una volta. Un funding non nullo successivo all'attivazione senza lato noto, o una chiusura aggregata priva di allocazioni/membership identificabile, blocca il ricalcolo invece di inventare un'attribuzione.

LONG: `P = (Q*A + F + H) / (Q*(1-s)*(1-f))`.

SHORT: `P = (Q*A - F - H) / (Q*(1+s)*(1+f))`.

P è il prezzo quotato, prima dello slippage di esecuzione. H=0 dà il vero break-even nel modello. Nel piano `InjectionPlan.break_even`, H può essere il profit target richiesto; nel blocco esposto alla UI, `break_even` usa H=0 e `tp` usa il profit target configurato. Un numeratore non positivo viene rifiutato: non si genera un TP non valido.

Il runtime valuta S/R soltanto dopo il prezzo matematico normalizzato. Con confluence almeno 50/100 può scegliere un tick prima di R1/R2 per LONG o un tick prima di S1/S2 per SHORT, entro il retrace configurato all'attivazione e senza ridurre il target netto matematico. Se non esiste un candidato compatibile mantiene il target matematico. Il punteggio S/R non è una probabilità di successo. Un TP già attivo conserva la propria generazione se la quantità residua coincide e il prezzo continua a soddisfare il target ricalcolato; un funding accreditato non causa cancellazioni inutili, un debito che rende il TP insufficiente richiede una sostituzione confermata.

## Quantità per un retrace esplicito

Per il piano automatico il target quote X è un retrace configurato dal prezzo attuale: LONG `M*(1+r)`, SHORT `M*(1-r)`. Viene prima normalizzato al tick in senso conservativo. Non è una previsione che il mercato raggiungerà quel prezzo.

Definiti E entry avversa e B exit avversa:

LONG `c = B*(1-f) - E*(1+f)` e `x = [H + F + Q*(A-B*(1-f))]/c`.

SHORT `c = E*(1-f) - B*(1+f)` e `x = [H + F + Q*(B*(1+f)-A)]/c`.

c deve essere positivo: se un'unità aggiunta non guadagna al retrace dopo entrambe le fee e gli slippage, l'injection non può recuperare il blocco. Il numeratore deve essere positivo; in caso contrario il target è già raggiungibile senza injection.

La quantità risultante viene arrotondata **verso l'alto** a qtyStep e almeno minQty. Media e TP vengono ricalcolati dopo arrotondamento. TP LONG arrotonda verso l'alto, TP SHORT verso il basso. La fattibilità viene ricontrollata sul target quotato normalizzato. Test indipendenti sostituiscono il piano nella formula del PnL netto e verificano anche che un qtyStep in meno non basti a raggiungere H.

## Autorizzazione separata dal calcolo

Il piano controlla max qty/market qty, minNotional, Max Injection, Max Recovery Exposure e Max Total Exposure. `safe=true` significa che questi controlli dimensionali e matematici passano; **non autorizza da solo un ordine**. Il Risk Engine deve sempre verificare saldo reale, ordini riservati, daily loss, ambiente, permessi, connessione e riconciliazione immediatamente prima dell'invio.

Con Auto Recovery OFF il piano è consultivo. Con ON l'orchestratore può inviare l'injection solo dopo Risk Engine. I TP normali non devono essere rimossi finché un piano sostitutivo non è validato; cancellation e nuovo TP richiedono conferme exchange, non solamente acknowledgement REST.

`progress` resta null finché non esiste un baseline di attivazione persistito dal runtime. Un calcolatore stateless non può inventare una percentuale di avanzamento. Fee future e slippage sono stime; funding futuro e impatto d'ordine non sono predetti da queste formule. Funding contabilizzato realmente deve essere distinto nel PnL e nel target runtime.

## Attribuzione del portafoglio

Il runtime persiste i link dei lotti effettivi appartenenti al blocco, il timestamp di attivazione e le fee GRID residue riclassificate. Il PnL Recovery comprende costi dell'injection, PnL non realizzato dei membri e chiusure successive dei membri; il profitto GRID già realizzato prima dell'attivazione resta GRID. Le fee d'ingresso residue originali vengono trasferite una sola volta da GRID a Recovery, così il Recovery netto non nasconde quel costo.

Le riduzioni registrano allocazioni effettive per lotto e permettono di attribuire anche una CHIUDI TUTTO che include contemporaneamente quantità GRID e Recovery. Il funding effettivo resta un componente distinto: `Grid + Recovery + Funding = Net`. Rebate e funding mantengono il segno economico del ledger; non vengono convertiti in costi positivi per il rendiconto.

Dopo l'handoff, i TP temporanei cancellati non sono trattati come protezione corrente. Un TP Recovery parzialmente eseguito continua a coprire soltanto la quantità residua; il target tiene conto delle chiusure già avvenute e del funding liquidato. La riparazione di un TP corrente cancellato richiede stato exchange terminale confermato, riconciliazione, Risk Engine e una nuova generazione persistita del client order ID: non riutilizza il vecchio identificativo cancellato.
