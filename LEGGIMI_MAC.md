# ⚡ Guida Installazione & Avvio per macOS 12 Monterey

Questa guida ti permette di eseguire l'applicazione **Strategia Griglia Pro** in locale sul tuo Mac con **macOS 12 Monterey** (compatibile sia con processori **Intel** che **Apple Silicon M1/M2/M3**).

---

## 📋 Requisiti Minimi
1. **macOS 12 Monterey** (o versioni successive).
2. **Python 3** (consigliato Python 3.10, 3.11 o 3.12).
   - Se non hai ancora Python 3, scarica l'installer ufficiale macOS da [python.org/downloads/macos](https://www.python.org/downloads/macos/).

---

## 🚀 Come Installare e Avviare (2 Metodi Semplicissimi)

### ▶️ Metodo 1: Avvio Rapido 1-Click (Consigliato)
1. Estrai lo zip nella cartella che preferisci (es. `Desktop` o `Applicazioni`).
2. Fai **Doppio Click** sul file:
   👉 **`Avvia_Strategia_Griglia.command`**
3. Il terminale configurerà automaticamente l'ambiente e aprirà subito l'applicazione nel tuo browser (Safari, Chrome, ecc.) all'indirizzo `http://localhost:8501`.

---

### 🍏 Metodo 2: Tramite Applicazione Mac (`Strategia Griglia.app`)
1. Fai doppio click su **`Strategia Griglia.app`**.
2. L'app si avvierà in automatico e aprirà la pagina di trading.

---

## 🛠️ Risoluzione Problemi Comuni su macOS 12

### 1. Avviso "Impossibile aprire perché proviene da uno sviluppatore non identificato"
Se macOS blocca l'apertura:
1. Fai **Click Destro** (o *Control + Click*) sul file `Avvia_Strategia_Griglia.command` o su `Strategia Griglia.app`.
2. Seleziona **Apri** dal menu a tendina.
3. Clicca su **Apri** nella finestra di dialogo di conferma.

### 2. Se i permessi non sono abilitati:
Apri l'app **Terminale** del Mac, trascina la cartella dell'applicazione ed esegui:
```bash
chmod +x Avvia_Strategia_Griglia.command installa_mac.sh
./installa_mac.sh
```

---

## 🔑 Credenziali Predefinite di Accesso
- **Username:** `Galva94`
- **Password:** `Gianmarco94`
- *(È disponibile anche il pulsante **"Modalità Demo"** per accedere immediatamente senza inserire password).*
