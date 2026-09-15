#!/usr/bin/env bash
# Script di configurazione iniziale per macOS 12 Monterey

DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
cd "$DIR"

echo "=========================================================="
echo "🍏 Installazione & Configurazione Strategia Griglia per Mac"
echo "   (Compatibile con macOS 12 Monterey - Intel & Apple Silicon)"
echo "=========================================================="
echo ""

# Rendi eseguibili gli script
chmod +x "$DIR/Avvia_Strategia_Griglia.command"
chmod +x "$DIR/Strategia Griglia.app/Contents/MacOS/launcher" 2>/dev/null || true

# Rimuovi eventuali attributi di quarantena di macOS
xattr -cr "$DIR" 2>/dev/null || true

# Verifica Python 3
if command -v python3 &>/dev/null; then
    echo "✅ Python 3 è installato: $(python3 --version)"
else
    echo "⚠️ Python 3 non trovato. Scaricalo da https://www.python.org/downloads/macos/"
    exit 1
fi

# Crea ambiente virtuale locale
echo "📦 Creazione ambiente virtuale isolato..."
python3 -m venv "$DIR/.venv_mac"

# Installa requisiti
echo "📥 Installazione librerie (Streamlit, Pandas, NumPy, Plotly)..."
"$DIR/.venv_mac/bin/pip" install --upgrade pip
"$DIR/.venv_mac/bin/pip" install -r "$DIR/requirements.txt"

echo ""
echo "=========================================================="
echo "🎉 INSTALLAZIONE COMPLETATA CON SUCCESSO!"
echo "👉 Ora puoi avviare l'app semplicemente facendo DOPPIO CLICK su:"
echo "   'Avvia_Strategia_Griglia.command'"
echo "   oppure su 'Strategia Griglia.app'"
echo "=========================================================="
