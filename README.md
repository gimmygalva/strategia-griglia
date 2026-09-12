# GRID HEDGE BOT — 0.1.0 candidatura locale

**Stato: collaudo nativo macOS in corso; accettazione operativa Bybit non superata.**
I pacchetti sono compilati su runner Mac reali, montati, copiati, avviati, riaperti
e sottoposti a crash del backend. Solo una build con tutti i controlli applicabili
superati produce un candidato installabile. Consultare TEST_REPORT.md,
KNOWN_ISSUES.md e il BUILD_MANIFEST.json del pacchetto per gli esiti effettivi.

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
Dopo un riavvio il bot ricostruisce lo stato ma richiede un nuovo Start per gli ingressi.

Le credenziali Demo sono state ricevute e sono escluse dai sorgenti e dagli artefatti.
Il controllo remoto del 12 settembre 2026 ha ricevuto HTTP 403 dal REST Mainnet,
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
