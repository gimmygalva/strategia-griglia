# GRID HEDGE BOT — 0.1.0 development

**Stato: sviluppo verificato localmente; release operativa macOS non approvata.**
Questi sono sorgenti eseguibili, test, frontend compilato e strumenti di build. Non sono
una promessa che un installer macOS o la connessione Bybit ufficiale siano già stati
collaudati. Consultare TEST_REPORT.md e KNOWN_ISSUES.md prima di ogni uso.

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

**In questa consegna tecnica non è incluso un DMG generato o verificato.** Linux non
può dimostrare installazione, apertura, Keychain o notarizzazione macOS. Nessuna chiave
Bybit Demo è stata fornita e l'accesso diretto ai domini Bybit è bloccato dalla rete.

## Sviluppo e verifiche

La procedura per sviluppatori è in docs/SETUP.md. L'utente finale di un pacchetto Mac
collaudato non dovrà installare Python, Node o Docker. scripts/build-macos.command
costruisce una candidatura locale e scripts/verify_macos_package.py monta, copia,
avvia, chiude, riapre e verifica il pacchetto su macOS. La pipeline GitHub Actions è
preparata per Intel e Apple Silicon; non è stata avviata su un repository remoto.

Documenti: docs/BYBIT_SETUP.md, docs/ARCHITECTURE.md, docs/STRATEGY.md,
docs/RECOVERY_ENGINE.md, docs/RISK_MANAGEMENT.md, docs/MACOS_BUILD.md,
docs/TESTING.md. I report e la checklist sono al livello principale.
