# GRID HEDGE BOT — 0.1.0 candidatura locale

**Stato: candidati Intel/Apple Silicon installabili collaudati; accettazione operativa Bybit non superata.**

Il repository conserva i due script e il `requirements.txt` originali. Sono
esclusi dal pacchetto desktop e dal presente collaudo; i sorgenti dell'app
consegnata sono in `backend/`, `frontend/` e `desktop/`, con dipendenze fissate
nelle rispettive cartelle.
I pacchetti sono compilati su runner Mac reali, montati, copiati, avviati, riaperti
e sottoposti a crash del backend. Solo una build con tutti i controlli applicabili
superati produce un candidato installabile. Consultare TEST_REPORT.md,
KNOWN_ISSUES.md e il BUILD_MANIFEST.json del pacchetto per gli esiti effettivi.
La variante Monterey dichiara macOS 12.0 come target minimo e la pipeline analizza
ogni eseguibile Mach-O incorporato; la prova finale sul Mac dell'utente con macOS
12.6.8 resta un test esterno distinto dalla compilazione sui runner macOS 15.

L'applicazione usa realmente le API V5 Bybit quando l'account e la rete sono disponibili.
Non contiene un exchange simulato nella UI o nel processo desktop. Il server di prova è
solo in tests/ ed è denominato Local Simulator. DEMO è il servizio ufficiale Bybit
Demo Trading, distinto da Testnet. LIVE è disabilitato per impostazione predefinita e
richiede anche le conferme nella UI.

## Percorso operativo previsto

Installare il DMG verificato per il proprio Mac, aprire l'app, scegliere DEMO, salvare
le API Demo nel Keychain e premere Test Connessione. Il wizard verifica account UTA,
permessi e Hedge Mode prima della configurazione di Grid, Recovery e limiti di rischio.
Start esegue una nuova riconciliazione. STOP sospende gli ingressi e cancella soltanto
gli ingressi pending del bot; conserva posizioni e TP. CHIUDI TUTTO richiede due conferme.
Dopo un riavvio un conto già verificato viene riconnesso dal Keychain e riconciliato;
gli ingressi richiedono un nuovo Start. Se il collegamento fallisce, l'app si apre
in pausa di sicurezza con l'errore visibile.

Le credenziali Demo sono state ricevute e sono escluse dai sorgenti e dagli artefatti.
I controlli remoti Linux/Mac Intel/Apple Silicon del 12 settembre 2026 hanno ricevuto HTTP 403 dal REST Mainnet,
dal REST Demo ufficiale e dal WebSocket privato Demo. Il feed pubblico BTCUSDT
Mainnet ha invece fornito un ticker reale. Non sono state utilizzate credenziali
e non sono stati inviati ordini: saldo, UTA, Hedge Mode e mini Grid sul conto Demo
restano NON VERIFICATI. Questo impedisce di dichiarare completato l'MVP operativo.

## Sviluppo e verifiche

La procedura per sviluppatori è in docs/SETUP.md. L'utente finale di un pacchetto Mac
collaudato non dovrà installare Python, Node o Docker. scripts/build-macos.command
costruisce una candidatura locale e scripts/verify_macos_package.py monta, copia,
avvia, chiude, riapre e verifica il pacchetto su macOS. La pipeline GitHub Actions
è stata eseguita su Intel e Apple Silicon. I risultati storici e la build attuale
sono distinti nel report. La build usa firma ad-hoc, senza Developer ID o
notarizzazione Apple: un'autorizzazione iniziale di macOS può essere richiesta.

Documenti: docs/BYBIT_SETUP.md, docs/ARCHITECTURE.md, docs/STRATEGY.md,
docs/RECOVERY_ENGINE.md, docs/RISK_MANAGEMENT.md, docs/MACOS_BUILD.md,
docs/TESTING.md. I report e la checklist sono al livello principale.

Build applicazione verificata: `eec4ad3c41d4ceb416dc6f1f6f2c5138b21b3ab9`. [Run finale](https://github.com/gimmygalva/strategia-griglia/actions/runs/34703106420). I DMG e il report generato sono consegnati separatamente dai sorgenti, con digest nel manifest.
