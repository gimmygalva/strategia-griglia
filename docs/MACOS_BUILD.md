# Build e verifiche macOS

## Stato della consegna

La pipeline è eseguita realmente su GitHub Actions macOS 15 Intel e Apple Silicon.
Produce bundle Tauri nativi con backend Python congelato, genera un vero DMG,
lo monta e avvia la copia dell'app. Gli esiti per ciascuna build e architettura
sono in `TEST_REPORT.md` e nel `dist/BUILD_MANIFEST.json` di quel pacchetto.
Il primo pacchetto Apple Silicon ha superato queste prove; il test post-build Intel
ha rilevato una race nella fixture del saldo Recovery, corretta prima della nuova
build. Nessun pacchetto Intel viene approvato con quel test fallito.

Una compilazione nativa che supera tutti i controlli produce un candidato locale;
la validazione con un account Bybit Demo dell'utente resta necessaria prima di
considerare completato il flusso operativo richiesto.

## Mac di compilazione

Servono macOS 13+, Xcode Command Line Tools, Rust stable con Cargo/rustfmt/clippy,
Python 3.12+ e Node 22+ con npm. Queste dipendenze servono **solo al compilatore**.
Il pacchetto contiene il frontend compilato, l'eseguibile desktop Tauri e il backend
Python congelato con PyInstaller. L'utilizzatore dell'app non deve installarle.

La build è nativa per architettura: Intel usa `x86_64-apple-darwin`, Apple Silicon
usa `aarch64-apple-darwin`. Non si dichiara una build Universal senza verificarla.
La pipeline `.github/workflows/ci.yml` prepara due runner separati, `macos-15-intel`
e `macos-15`, secondo le [architetture ufficiali dei runner GitHub](https://docs.github.com/en/actions/reference/runners/github-hosted-runners).
Sono usati macOS 15, Python 3.12, Node 22 e Rust stable; il supporto a versioni
precedenti di macOS non è dimostrato da questi runner. macOS 15.5 dell'utente
è nel requisito di sistema dichiarato ma non è la versione esatta del runner.

## Comando di build

Aprire `scripts/build-macos.command` oppure eseguire:

```bash
bash scripts/build-macos.sh
```

Per un Python di compilazione con nome diverso, impostare `GRIDBOT_BUILD_PYTHON`
al suo percorso. Il comando crea un ambiente virtuale di compilazione, installa
le versioni fissate, elimina le build precedenti ed esegue i controlli.
`ALLOW_MAINNET_TRADING=false` è imposto per tutti i test della build.

La sequenza comprende lint Python, test backend/packaging, compilazione Python,
lint/test/build frontend, E2E DOM con HTTP/WS reale, asset, congelamento backend, test dell'eseguibile senza
Python/Node nel PATH, test Rust, clippy, bundle nativo e verifiche d'installazione.
Poi ripete le suite backend, frontend e E2E DOM. Un controllo fallito termina il comando:
non viene scritto un manifest di candidato approvato.

Output atteso, soltanto dopo build macOS reale:

```text
dist/Grid Hedge Bot.app
dist/Grid Hedge Bot.dmg
dist/BUILD_MANIFEST.json
dist/reports/
```

Il manifest include hash SHA-256 del DMG, architettura, risultati leggibili delle
verifiche e limiti esterni. La classificazione è
`LOCAL_CANDIDATE_REQUIRES_BYBIT_DEMO_ACCEPTANCE`.

## Controlli sul pacchetto

`scripts/verify_macos_package.py` esegue realmente:

1. verifica e monta il DMG in sola lettura;
2. controlla l'app e il collegamento Applications;
3. copia l'app con `ditto` e verifica la struttura di firma;
   controlla anche il flag Hardened Runtime della firma effettiva;
4. avvia l'eseguibile della copia con directory dati vuota e PATH di soli tool OS;
5. attende backend autenticato e frontend nativo operativo;
6. verifica migrazioni, integrità SQLite, permessi e Mainnet disabilitata;
7. chiude la finestra attraverso il medesimo handler di chiusura dell'app;
8. verifica uscita senza backend orfano;
9. riapre l'app e verifica dati conservati;
10. uccide il sidecar, attende riavvio e nuova inizializzazione frontend, controlla
    che il trading non riparta automaticamente e chiude di nuovo.

Sui runner CI isolati, un controllo aggiuntivo usa credenziali sintetiche per
salvare e rileggere il Keychain nativo attraverso il backend dentro la copia
dell'app. Verifica separazione DEMO/LIVE, persistenza tra processi e assenza del
secret in API, database, impostazioni e log. Non autentica un conto Bybit.
Il marker frontend richiede anche che la finestra nativa sia visibile. Viene
tentata una cattura schermo reale; se il runner la impedisce l'esito visivo è
NON VERIFICATO e viene riportato separatamente. Un driver QA del wrapper clicca
i controlli dell'app installata e verifica il DOM WKWebView reale: wizard,
chiusura, tre card Home, equity mancante offline, Start disabilitato, canvas
Lightweight Charts, Attività, dettagli tecnici, tutti i pannelli Impostazioni,
avviso LIVE e campi credenziali vuoti. Il driver non modifica account, non
introduce dati simulati e non chiama Start, Close All o Connect. È accessibile
soltanto con `GRIDBOT_DESKTOP_QA=1`; ogni assertion fallita blocca il packaging.
Alla seconda apertura confronta la timeline con gli eventi effettivi restituiti
dall'API autenticata: gli audit della chiusura precedente devono essere visibili.
Il wrapper legge i risultati tramite callback nativo; i soli comandi IPC
applicativi consentiti al frontend rimangono `bootstrap` e `frontend_ready`.

Il sidecar incorpora anche le CA TLS. Il controllo sul binario reale richiede
che health abbia caricato CA non vuote dall'interno del bundle; REST e WSS
condividono quel contesto verificato. Non dipende dal percorso OpenSSL/Python
della macchina di compilazione. CA assenti o esterne al sidecar congelato
bloccano la disponibilità del backend e l'avvio del trading.

La verifica usa un flag QA esplicito e una directory temporanea; non tocca i dati
reali dell'utente, non utilizza le sue credenziali e non invia ordini Live.
`desktop-status.json` contiene stato, PID, URL loopback e generazione. Non contiene
il token locale né chiavi Bybit. Il frontend deve aver completato un fetch di stato
autenticato prima di notificare la propria disponibilità al wrapper.

Questo test avvia il binario della copia dell'app. La verifica manuale aggiuntiva
con Finder, download con quarantena Gatekeeper e un altro Mac rimane esplicita.
Non si equipara il PATH pulito a una VM di macOS priva di tutti i tool installati.

## Ciclo di vita

Il wrapper genera 256 bit casuali di token, avvia il sidecar sul solo
`127.0.0.1` con porta assegnata dal sistema e attende un evento READY più un
controllo HTTP autenticato. Il frontend riceve URL/token soltanto tramite il
comando Tauri `bootstrap`. Nessuna permission shell è concessa al frontend.

Alla chiusura della finestra o al comando Esci, il wrapper richiede pausa e
shutdown; attende l'uscita del sidecar, usa SIGTERM come fallback e SIGKILL
soltanto se il processo non termina. La chiusura non chiude posizioni sull'exchange.
Gli ordini TP esistenti restano sull'exchange; senza l'app non prosegue la gestione
locale della strategia. Dopo crash del sidecar sono consentiti tre riavvii con
attesa crescente, sempre con token nuovo e strategia inizialmente sospesa.
Il processo desktop mantiene inoltre una pipe stdin aperta verso il backend;
se il desktop termina inaspettatamente, l'EOF attiva pausa e shutdown nel backend.
Il sidecar usa un gruppo di processi dedicato per includere il processo Python
avviato dal bootloader PyInstaller nelle terminazioni di fallback.

Dati persistenti: `~/Library/Application Support/Grid Hedge Bot/`.
Credenziali: macOS Keychain; aggiornare la `.app` non cancella questi contenuti.
Il frontend è incluso sia nel bundle Tauri sia tra i dati del backend congelato.
Le dimensioni e il suffix di `externalBin` seguono la
[documentazione ufficiale Tauri sui sidecar](https://v2.tauri.app/develop/sidecar/).

## Firma e notarizzazione

Senza certificato la build usa `APPLE_SIGNING_IDENTITY=-`, firma ad-hoc locale.
La firma ad-hoc non equivale a Developer ID e non elimina le verifiche Gatekeeper.
L'app può richiedere l'autorizzazione nelle impostazioni Privacy e Sicurezza.

Per la distribuzione esterna, installare nel Keychain un certificato Developer ID
Application e impostare `APPLE_SIGNING_IDENTITY` alla sua identità. Tauri è
configurato con Hardened Runtime; PyInstaller riceve la stessa identità e gli
entitlement del backend. La firma/notarizzazione è **NON VERIFICATA** finché non
viene completata e validata sul pacchetto risultante.

Per notarizzare, Tauri supporta `APPLE_ID`, `APPLE_PASSWORD` (password specifica
per app), `APPLE_TEAM_ID`, oppure le credenziali App Store Connect API.
Non salvare questi valori nel repository. Seguono la
[procedura ufficiale di firma Tauri macOS](https://v2.tauri.app/distribute/sign/macos/).
Dopo notarizzazione controllare `xcrun stapler validate` e `spctl --assess` sul
pacchetto e ripetere installazione da download su un Mac distinto.

## Riproducibilità e aggiornamenti

`package-lock.json` desktop/frontend e i requirements fissano le dipendenze JS e
Python. `desktop/Cargo.lock` proviene dalla build nativa Apple Silicon verificata
ed è conservato nel repository per fissare anche le dipendenze Rust.
`cargo --locked` è usato nei controlli e nella build. La CI esegue pip-audit,
cargo-audit e npm audit prima di autorizzare il packaging nativo; il manifest
non sostituisce i risultati degli audit o il collaudo Bybit ufficiale.

Aggiornamenti futuri sostituiscono il bundle `.app` e applicano migrazioni al
database esterno al bundle. Eseguire sempre backup e test di upgrade con una copia
del database; non copiare dati o chiavi di API dentro `Contents/`.
