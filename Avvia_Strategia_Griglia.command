#!/usr/bin/env bash
# ==============================================================================
# Strategia Griglia Pro - Launcher per macOS (Compatibile con macOS 12 Monterey)
# ==============================================================================

# Spostati nella cartella in cui si trova questo script
DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
cd "$DIR"

echo "========================================================"
echo "   ⚡ AVVIO STRATEGIA GRIGLIA PRO (macOS 12+)"
echo "========================================================"
echo ""

# 1. Verifica presenza di Python 3
PYTHON_BIN=""
if command -v python3 &>/dev/null; then
    PYTHON_BIN="python3"
elif command -v /usr/local/bin/python3 &>/dev/null; then
    PYTHON_BIN="/usr/local/bin/python3"
elif command -v /opt/homebrew/bin/python3 &>/dev/null; then
    PYTHON_BIN="/opt/homebrew/bin/python3"
fi

if [ -z "$PYTHON_BIN" ]; then
    echo "❌ Errore: Python 3 non trovato sul tuo Mac."
    echo "👉 Su macOS 12 Monterey puoi installarlo facilmente:"
    echo "   1. Scaricando l'installer ufficiale da: https://www.python.org/downloads/macos/"
    echo "   2. Oppure tramite Terminale con: brew install python"
    echo ""
    read -p "Premi INVIO per uscire..."
    exit 1
fi

echo "✅ Python rilevato: $($PYTHON_BIN --version)"

# 2. Creazione ambiente virtuale isolato se non esiste
if [ ! -d "$DIR/.venv_mac" ]; then
    echo "📦 Creazione ambiente virtuale locale (.venv_mac)..."
    $PYTHON_BIN -m venv "$DIR/.venv_mac"
    if [ $? -ne 0 ]; then
        echo "❌ Impossibile creare l'ambiente virtuale."
        read -p "Premi INVIO per uscire..."
        exit 1
    fi
fi

# Attiva l'ambiente virtuale
source "$DIR/.venv_mac/bin/activate"

# 3. Installazione / Aggiornamento dipendenze
echo "🔄 Verifica e installazione dipendenze (Streamlit, Pandas, Plotly)..."
pip install --upgrade pip --quiet
pip install -r "$DIR/requirements.txt" --quiet

if [ $? -ne 0 ]; then
    echo "⚠️ Alcuni pacchetti potrebbero non essersi installati correttamente."
fi

# 4. Avvio dell'applicazione Streamlit
echo ""
echo "🚀 Avvio applicazione in corso..."
echo "🌐 L'interfaccia si aprirà automaticamente nel tuo browser (Safari / Chrome)"
echo "👉 Indirizzo locale: http://localhost:8501"
echo ""
echo "Premi CTRL + C in questa finestra del Terminale per arrestare il bot."
echo "========================================================"
echo ""

# Apre automaticamente il browser su macOS
(sleep 2 && open "http://localhost:8501") &

# Avvia Streamlit
streamlit run "$DIR/app.py" --server.port 8501 --server.address 127.0.0.1 --server.headless false
