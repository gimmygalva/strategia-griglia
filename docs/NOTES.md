# Decisioni conservative della versione di sviluppo

- Account o subaccount dedicato BTCUSDT: posizioni/ordini esterni divergenti bloccano
  gli ingressi. Il database è vincolato all'UID inizialmente verificato; cambiare conto
  non può adottare il ledger precedente.
- Una sola injection attiva alla volta. Durante Recovery gli ingressi grid sono
  sospesi, mentre feed, TP e controllo del blocco continuano. Nessuna serie DCA
  illimitata o compensazione automatica di una gamba rifiutata.
- Due gambe hedge non costituiscono un'operazione atomica Bybit. Una gamba può essere
  eseguita mentre l'altra viene rifiutata. Il bot mostra l'errore, conserva l'operazione
  confermata e blocca gli ingressi; non inventa un'operazione di compensazione.
- Funding deriva da transaction-log idempotente, campo funding con segno ricevuto/pagato;
  cashFlow o cumRealisedPnl non sostituiscono questo ledger. Net include funding e fee.
- PnL Oggi usa mark corrente e costi/quantità a mezzanotte ricostruiti dal ledger, con
  open della candela mark00:00 UTC ufficiale. Il prezzo della candela è una misura
  storica osservata al minuto, non un tick esatto esportato dal proprio account. Se
  manca, non si sostituisce con il prezzo al riavvio: nuovi ingressi bloccati.
- Supporti/resistenze sono quantitativi, senza previsioni AI. Il BE matematico rimane
  vincolante; non c'è garanzia che il mercato raggiunga il TP suggerito.
- Il lato desktop e i secret Keychain devono ancora essere compilati e provati su Mac.
  Non usare LIVE prima dei collaudi esterni indicati nella checklist.
