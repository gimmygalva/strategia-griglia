# Installazione e primo avvio

## Disponibilità attuale

I pacchetti sono costruiti e collaudati nativamente sui runner Mac Intel e Apple
Silicon. Il manifest di ciascun pacchetto riporta la build e i test effettivi.
È una candidatura locale finché non è superata l'accettazione operativa del
conto Bybit Demo. I controlli REST e WS privati del runner hanno ricevuto HTTP 403:
saldo e trading sul conto ufficiale restano NON VERIFICATI. Consultare
`TEST_REPORT.md` e `KNOWN_ISSUES.md` per i risultati attuali e i limiti Apple.

## Uso del pacchetto macOS validato

Quando il pacchetto nativo ha superato i controlli descritti in `MACOS_BUILD.md`:

1. aprire `Grid Hedge Bot.dmg`;
2. trascinare **Grid Hedge Bot** nella cartella **Applications**;
3. aprire l'app da Applicazioni;
4. scegliere **DEMO**, selezionata per default;
5. inserire le API generate nel vero Bybit Demo Trading;
6. premere **Test Connessione**;
7. verificare UID, UTA, saldo, permessi e Hedge Mode;
8. configurare Grid, Recovery e limiti di rischio;
9. controllare il riepilogo e premere **Avvia Bot**.

Le chiavi si inseriscono nell'app, non nella chat. **Demo Trading ≠ Testnet**.
Leggere `BYBIT_SETUP.md` per creare le chiavi nell'ambiente corretto.
Senza una connessione valida la UI mostra dati mancanti e il bot non apre ordini.

L'app validata incorpora tutti i runtime. L'uso quotidiano non richiede Terminale,
Python, Node, npm, FastAPI o Docker. Per le build ad-hoc locali Gatekeeper può
richiedere l'autorizzazione in Privacy e Sicurezza; una distribuzione con Developer
ID e notarizzazione segue la procedura di `MACOS_BUILD.md`.

## Pausa, chiusura e riapertura

**STOP / Pausa** blocca nuovi ingressi e conserva le posizioni e i TP esistenti.
**Chiudi Tutto** è un'azione separata, con doppia conferma, che chiude le posizioni
del simbolo selezionato. Non viene usata dai test di sviluppo Live.

Chiudere la finestra richiede pausa e spegnimento dei processi locali. Posizioni e
ordini sull'exchange non scompaiono chiudendo il programma. Alla riapertura è
necessaria riconciliazione prima di riabilitare la strategia: non riparte da sola.
Gli errori di connessione o di stato incerto impediscono nuovi ordini.

## Dati e aggiornamenti

Il database, le impostazioni, i log e la cache risiedono in:

`~/Library/Application Support/Grid Hedge Bot/`

Le credenziali DEMO e LIVE usano voci distinte di macOS Keychain. Il secret è
scrivibile attraverso l'app e non può essere recuperato dal frontend.
Per aggiornare l'app sostituire il bundle in Applicazioni: la directory dati e il
Keychain restano esterni al bundle. Eseguire un backup della directory dati con
l'app chiusa prima degli upgrade e non cancellarla durante la disinstallazione
se si intende conservare lo storico.

## Modalità LIVE

LIVE impiega l'adapter Mainnet reale e lo stesso Strategy Engine di DEMO.
L'abilitazione backend `ALLOW_MAINNET_TRADING=true` deve essere una decisione
esplicita dell'operatore; il valore predefinito è `false`. L'indicatore LIVE rosso,
la conferma scritta e la seconda conferma della UI sono richiesti in aggiunta.
La modalità LIVE non è stata usata per i test di trading dello sviluppo.

## Avvio per sviluppatori

Su una macchina di sviluppo con Python 3.12+ e Node 22+:

```bash
python3.12 -m venv .venv
.venv/bin/python -m pip install -r backend/requirements-dev.txt -r scripts/requirements-packaging.txt
npm --prefix frontend ci
npm --prefix desktop ci
npm --prefix frontend run build
```

Avviare il backend con `PYTHONPATH=backend`, `ALLOW_MAINNET_TRADING=false`, un
`GRID_API_TOKEN` effimero e `GRID_DEVELOPMENT_BOOTSTRAP=true`; il modulo è
`python -m gridbot --port 0 --data-dir /percorso/assoluto/test`.
L'avvio emette il bootstrap locale soltanto con il flag di sviluppo esplicito.
Usare un terminale privato e non incollare quell'URL in log o chat: contiene il
token locale di sessione, non le chiavi Bybit. Il frontend è servito dal backend
dopo la build; in sviluppo React si può usare `npm --prefix frontend run dev`.

Per il pacchetto senza dipendenze dell'utente utilizzare esclusivamente la build
nativa `scripts/build-macos.command` e tutti i controlli di `MACOS_BUILD.md`.
