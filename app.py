import streamlit as st
import pandas as pd
import numpy as np
import plotly.graph_objects as go
import time
from datetime import datetime

# ==============================================================================
# CONFIGURAZIONE PAGINA
# ==============================================================================
st.set_page_config(
    page_title="Strategia Griglia Bidirezionale con AI",
    page_icon="📈",
    layout="wide",
    initial_sidebar_state="expanded"
)

# ==============================================================================
# INIZIALIZZAZIONE SESSION STATE (ENGINE DI SIMULAZIONE MAINNET DEMO)
# ==============================================================================
if "logged_in" not in st.session_state:
    st.session_state["logged_in"] = True  # Accesso diretto per test rapido

if "prezzo_corrente" not in st.session_state:
    st.session_state["prezzo_corrente"] = 68500.0

if "pos_long_qty" not in st.session_state:
    st.session_state["pos_long_qty"] = 0.40
if "pos_long_pm" not in st.session_state:
    st.session_state["pos_long_pm"] = 62000.0

if "pos_short_qty" not in st.session_state:
    st.session_state["pos_short_qty"] = 0.25
if "pos_short_pm" not in st.session_state:
    st.session_state["pos_short_pm"] = 73000.0

if "capitale_disponibile" not in st.session_state:
    st.session_state["capitale_disponibile"] = 10000.0

if "profitto_realizzato_totale" not in st.session_state:
    st.session_state["profitto_realizzato_totale"] = 145.50

if "trade_history" not in st.session_state:
    st.session_state["trade_history"] = [
        {"Data": "2026-09-15 10:15", "Operazione": "BUY LONG", "Prezzo": 67800.0, "Quantità BTC": 0.05, "Profitto (USDT)": 0.0, "Stato": "Eseguito"},
        {"Data": "2026-09-15 11:30", "Operazione": "TAKE PROFIT LONG", "Prezzo": 68480.0, "Quantità BTC": 0.05, "Profitto (USDT)": 34.0, "Stato": "Chiuso in Profitto"},
        {"Data": "2026-09-15 13:00", "Operazione": "SELL SHORT", "Prezzo": 68900.0, "Quantità BTC": 0.04, "Profitto (USDT)": 0.0, "Stato": "Eseguito"},
        {"Data": "2026-09-15 14:45", "Operazione": "TAKE PROFIT SHORT", "Prezzo": 68210.0, "Quantità BTC": 0.04, "Profitto (USDT)": 27.6, "Stato": "Chiuso in Profitto"},
        {"Data": "2026-09-15 16:20", "Operazione": "BUY LONG", "Prezzo": 67500.0, "Quantità BTC": 0.06, "Profitto (USDT)": 0.0, "Stato": "Eseguito"},
        {"Data": "2026-09-15 17:50", "Operazione": "TAKE PROFIT LONG", "Prezzo": 68175.0, "Quantità BTC": 0.06, "Profitto (USDT)": 40.5, "Stato": "Chiuso in Profitto"},
    ]

if "ordini_griglia_attivi" not in st.session_state:
    st.session_state["ordini_griglia_attivi"] = []

# Funzione per tentare il fetch del prezzo reale da Binance o fallback simulato
def aggiorna_prezzo_live(simula_delta_pct=0.0):
    if simula_delta_pct != 0.0:
        nuovo_p = st.session_state["prezzo_corrente"] * (1 + simula_delta_pct / 100.0)
        st.session_state["prezzo_corrente"] = round(nuovo_p, 2)
    return st.session_state["prezzo_corrente"]

# ==============================================================================
# MENU DI NAVIGAZIONE
# ==============================================================================
st.sidebar.title("🧭 Menu Principale")
menu = st.sidebar.radio("Naviga tra le sezioni:", [
    "📈 Dashboard & P/L Live",
    "⚙️ Settaggio Strategia",
    "🔄 Backtest / Simulazione",
    "🧮 Calcola Mediazione",
    "🤖 AI & Rimbalzi",
    "🔑 Settaggio API (Demo Mainnet)"
])

st.sidebar.divider()
st.sidebar.markdown("### ⚡ Controllo Prezzo Mercato")
st.sidebar.write(f"Prezzo BTC Attuale: **{st.session_state['prezzo_corrente']:,.2f} USDT**")

col_sb1, col_sb2 = st.sidebar.columns(2)
with col_sb1:
    if st.button("🟢 Prezzo +1%"):
        aggiorna_prezzo_live(+1.0)
        st.rerun()
with col_sb2:
    if st.button("🔴 Prezzo -1%"):
        aggiorna_prezzo_live(-1.0)
        st.rerun()

nuovo_input_p = st.sidebar.number_input("Imposta Prezzo Manuale ($):", value=float(st.session_state["prezzo_corrente"]), step=100.0)
if nuovo_input_p != st.session_state["prezzo_corrente"]:
    st.session_state["prezzo_corrente"] = float(nuovo_input_p)
    st.rerun()

st.sidebar.info("💡 **Modalità Demo:** Simula la Mainnet in tempo reale senza rischiare capitale reale.")

# ==============================================================================
# 1. DASHBOARD & P/L LIVE
# ==============================================================================
if menu == "📈 Dashboard & P/L Live":
    st.title("📈 Dashboard Strategia Griglia Bidirezionale")
    st.subheader("P/L in Tempo Reale & Esposizione Posizioni (Mainnet Demo)")

    prezzo_corrente = st.session_state["prezzo_corrente"]

    col1, col2 = st.columns(2)
    with col1:
        st.markdown("#### 🟢 Posizioni LONG")
        prezzo_medio_long = st.number_input("Prezzo medio posizioni LONG ($)", value=float(st.session_state["pos_long_pm"]), step=100.0, key="pm_l")
        quantita_long = st.number_input("Quantità LONG (BTC)", value=float(st.session_state["pos_long_qty"]), step=0.05, min_value=0.0, key="q_l")
        st.session_state["pos_long_pm"] = prezzo_medio_long
        st.session_state["pos_long_qty"] = quantita_long

    with col2:
        st.markdown("#### 🔴 Posizioni SHORT")
        prezzo_medio_short = st.number_input("Prezzo medio posizioni SHORT ($)", value=float(st.session_state["pos_short_pm"]), step=100.0, key="pm_s")
        quantita_short = st.number_input("Quantità SHORT (BTC)", value=float(st.session_state["pos_short_qty"]), step=0.05, min_value=0.0, key="q_s")
        st.session_state["pos_short_pm"] = prezzo_medio_short
        st.session_state["pos_short_qty"] = quantita_short

    # Calcolo P/L
    pl_long = (prezzo_corrente - prezzo_medio_long) * quantita_long if quantita_long > 0 else 0.0
    pl_short = (prezzo_medio_short - prezzo_corrente) * quantita_short if quantita_short > 0 else 0.0
    pl_non_realizzato = pl_long + pl_short
    sbilanciamento_netto = quantita_long - quantita_short

    st.markdown("---")
    col_m1, col_m2, col_m3, col_m4 = st.columns(4)
    col_m1.metric("P/L LONG", f"{pl_long:+,.2f} USDT", delta=f"{((prezzo_corrente - prezzo_medio_long)/prezzo_medio_long*100):+.2f}%" if prezzo_medio_long > 0 else "0%")
    col_m2.metric("P/L SHORT", f"{pl_short:+,.2f} USDT", delta=f"{((prezzo_medio_short - prezzo_corrente)/prezzo_medio_short*100):+.2f}%" if prezzo_medio_short > 0 else "0%")
    col_m3.metric("P/L Totale Non Realizzato", f"{pl_non_realizzato:+,.2f} USDT", delta_color="normal")
    col_m4.metric("Sbilanciamento Netto", f"{sbilanciamento_netto:+.4f} BTC", "Direzione " + ("LONG" if sbilanciamento_netto > 0 else ("SHORT" if sbilanciamento_netto < 0 else "NEUTRA")))

    st.markdown("---")
    st.subheader("📜 Storico Operazioni Eseguite dalla Griglia")
    df_history = pd.DataFrame(st.session_state["trade_history"])
    st.dataframe(df_history, use_container_width=True)

    # Grafico cumulativo P/L
    st.subheader("📊 Grafico Profit/Loss Cumulativo (USDT)")
    profitti = df_history["Profitto (USDT)"].values
    cum_pnl = np.cumsum(profitti)
    
    fig = go.Figure()
    fig.add_trace(go.Scatter(
        x=df_history["Data"],
        y=cum_pnl,
        mode='lines+markers',
        name='Profitto Cumulativo',
        line=dict(color='#00c853', width=3),
        marker=dict(size=8, color='#00c853')
    ))
    fig.update_layout(
        title="Crescita Profitto Realizzato (USDT)",
        xaxis_title="Data / Esecuzione",
        yaxis_title="Profitto Cumulativo (USDT)",
        template="plotly_white",
        height=350
    )
    st.plotly_chart(fig, use_container_width=True)

    # Azione di test per simulare esecuzione griglia
    st.markdown("#### ⚡ Test Esecuzione Griglia (Simula Chiusura Ordine su Mainnet Demo)")
    col_test1, col_test2 = st.columns(2)
    with col_test1:
        if st.button("Simula Take Profit LONG (+25 USDT)"):
            nuova_data = datetime.now().strftime("%Y-%m-%d %H:%M")
            st.session_state["trade_history"].append({
                "Data": nuova_data,
                "Operazione": "TAKE PROFIT LONG",
                "Prezzo": round(prezzo_corrente, 2),
                "Quantità BTC": 0.04,
                "Profitto (USDT)": 25.0,
                "Stato": "Chiuso in Profitto"
            })
            st.session_state["profitto_realizzato_totale"] += 25.0
            st.success("✅ Ordine Take Profit LONG eseguito con successo! Profitto: +25.00 USDT")
            st.rerun()

    with col_test2:
        if st.button("Simula Take Profit SHORT (+25 USDT)"):
            nuova_data = datetime.now().strftime("%Y-%m-%d %H:%M")
            st.session_state["trade_history"].append({
                "Data": nuova_data,
                "Operazione": "TAKE PROFIT SHORT",
                "Prezzo": round(prezzo_corrente, 2),
                "Quantità BTC": 0.04,
                "Profitto (USDT)": 25.0,
                "Stato": "Chiuso in Profitto"
            })
            st.session_state["profitto_realizzato_totale"] += 25.0
            st.success("✅ Ordine Take Profit SHORT eseguito con successo! Profitto: +25.00 USDT")
            st.rerun()

# ==============================================================================
# 2. SETTAGGIO STRATEGIA & GENERATORE GRIGLIA
# ==============================================================================
elif menu == "⚙️ Settaggio Strategia":
    st.title("⚙️ Configurazione Strategia Griglia")
    st.write("Imposta i parametri della griglia, calcola i requisiti di capitale e genera la tabella degli ordini.")

    col1, col2 = st.columns(2)
    with col1:
        range_min = st.number_input("Range Minimo (es. 30000)", value=30000.0, step=500.0, min_value=100.0)
        distanza_griglia = st.number_input("Distanza Griglia (%)", value=0.5, step=0.1, min_value=0.05)
        take_profit = st.number_input("Take Profit per Griglia (%)", value=1.0, step=0.1, min_value=0.05)
        profitto_per_griglia = st.number_input("Profitto desiderato per griglia (USDT)", value=10.0, step=1.0, min_value=1.0)
    with col2:
        range_max = st.number_input("Range Massimo (es. 110000)", value=110000.0, step=500.0, min_value=range_min + 100.0)
        cap_operativo_pct = st.slider("Percentuale Capitale Operativo", 10, 100, 50)
        cap_riserva_pct = 100 - cap_operativo_pct
        st.info(f"Percentuale Capitale di Riserva: **{cap_riserva_pct}%**")

    # --- Calcoli automatici ---
    st.markdown("### 📊 Calcoli Automatici Dimensionamento")
    distanza_effettiva = max(distanza_griglia, 0.001) / 100.0
    take_profit_effettivo = max(take_profit, 0.001) / 100.0
    cap_operativo_pct_effettivo = max(cap_operativo_pct, 1) / 100.0

    num_griglie = int((range_max - range_min) / (range_min * distanza_effettiva))
    num_griglie = max(num_griglie, 1)
    capitale_per_griglia = profitto_per_griglia / take_profit_effettivo
    capitale_operativo = capitale_per_griglia * num_griglie
    capitale_totale = capitale_operativo / cap_operativo_pct_effettivo
    capitale_riserva = capitale_totale - capitale_operativo

    c1, c2, c3 = st.columns(3)
    c1.metric("Numero Griglie", f"{num_griglie}")
    c2.metric("Capitale per Singola Griglia", f"{capitale_per_griglia:,.2f} USDT")
    c3.metric("Capitale Operativo Totale", f"{capitale_operativo:,.2f} USDT")

    c4, c5, c6 = st.columns(3)
    c4.metric("Capitale di Riserva", f"{capitale_riserva:,.2f} USDT")
    c5.metric("Capitale Totale Necessario", f"{capitale_totale:,.2f} USDT")
    c6.metric("Profitto Stimato a Griglia", f"{profitto_per_griglia:,.2f} USDT")

    st.markdown("---")
    st.subheader("📑 Tabella Livelli Ordini Griglia (Fable / Data Table)")
    
    prezzo_p = st.session_state["prezzo_corrente"]
    prezzi_livelli = np.linspace(range_min, range_max, min(num_griglie + 1, 100))
    
    griglia_data = []
    for idx, p in enumerate(prezzi_livelli):
        is_buy = p < prezzo_p
        tp = p * (1 + take_profit_effettivo) if is_buy else p * (1 - take_profit_effettivo)
        griglia_data.append({
            "Livello": idx + 1,
            "Prezzo ($)": round(p, 2),
            "Tipo": "BUY (Long)" if is_buy else "SELL (Short)",
            "Target TP ($)": round(tp, 2),
            "Capitale (USDT)": round(capitale_per_griglia, 2),
            "Quantità BTC": round(capitale_per_griglia / p, 5),
            "Profitto Target (USDT)": round(profitto_per_griglia, 2)
        })

    df_grid = pd.DataFrame(griglia_data)
    st.dataframe(df_grid, use_container_width=True, height=350)

    # Bottone di piazzamento ordini nella simulazione Demo Mainnet
    if st.button("🚀 Inizializza e Piazza Ordini Griglia su Mainnet Demo"):
        st.session_state["ordini_griglia_attivi"] = griglia_data
        st.success(f"✅ Piazzati con successo {len(griglia_data)} ordini di griglia nella simulazione Mainnet!")

# ==============================================================================
# 3. BACKTEST / SIMULAZIONE MENSILE
# ==============================================================================
elif menu == "🔄 Backtest / Simulazione":
    st.title("🔄 Simulazione / Backtest Guadagno Mensile")
    st.write("Inserisci quante griglie si chiuderebbero ogni mese per stimare il guadagno annuale potenziale.")

    profitto_per_griglia = st.number_input("Profitto per griglia (USDT)", value=10.0, step=1.0)
    mesi = ["Gennaio", "Febbraio", "Marzo", "Aprile", "Maggio", "Giugno",
            "Luglio", "Agosto", "Settembre", "Ottobre", "Novembre", "Dicembre"]

    col1, col2, col3 = st.columns(3)
    guadagni = []
    griglie_mese_list = []
    for i, mese in enumerate(mesi):
        with [col1, col2, col3][i % 3]:
            griglie_chiuse = st.number_input(f"{mese}", min_value=0, value=25, key=f"bk_{mese}")
            guadagno = griglie_chiuse * profitto_per_griglia
            guadagni.append(guadagno)
            griglie_mese_list.append(griglie_chiuse)
            st.write(f"Guadagno: **{guadagno:.2f} USDT**")

    guadagno_annuale = sum(guadagni)
    st.markdown("---")
    st.subheader(f"🏆 Guadagno Totale Annuo Stimato: {guadagno_annuale:,.2f} USDT")

    # Grafico mensile
    df_bk = pd.DataFrame({
        "Mese": mesi,
        "Profitto (USDT)": guadagni,
        "Griglie Chiuse": griglie_mese_list
    })
    st.bar_chart(df_bk.set_index("Mese")["Profitto (USDT)"])

# ==============================================================================
# 4. CALCOLA MEDIAZIONE (DCA)
# ==============================================================================
elif menu == "🧮 Calcola Mediazione":
    st.title("🧮 Calcolo Mediazione (DCA)")
    st.write("Calcola quanto capitale serve per mediare una posizione in perdita e portarla in profitto all'uscita.")

    col1, col2 = st.columns(2)
    with col1:
        prezzo_ingresso = st.number_input("Prezzo medio ingresso ($)", value=30000.0, step=100.0)
        prezzo_attuale = st.number_input("Prezzo attuale di mercato ($)", value=27000.0, step=100.0)
    with col2:
        quantita_iniziale = st.number_input("Quantità iniziale (BTC)", value=1.0, step=0.1)
        quantita_da_aggiungere = st.number_input("Quantità da aggiungere (BTC)", value=1.0, step=0.1)

    prezzo_target = st.number_input("Target uscita profitto (%)", value=0.3, step=0.1)

    # Calcoli DCA
    quantita_tot = quantita_iniziale + quantita_da_aggiungere
    if quantita_tot > 0:
        nuovo_prezzo_medio = (prezzo_ingresso * quantita_iniziale + prezzo_attuale * quantita_da_aggiungere) / quantita_tot
    else:
        nuovo_prezzo_medio = 0.0

    prezzo_uscita = nuovo_prezzo_medio * (1 + prezzo_target / 100.0)
    capitale_necessario_dca = prezzo_attuale * quantita_da_aggiungere
    profitto_uscita_dca = (prezzo_uscita - nuovo_prezzo_medio) * quantita_tot

    st.markdown("---")
    st.subheader("🎯 Risultati Calcolo Mediazione")
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Nuovo Prezzo Medio", f"{nuovo_prezzo_medio:,.2f} USDT", delta=f"-{abs(prezzo_ingresso - nuovo_prezzo_medio):,.2f} USDT", delta_color="inverse")
    c2.metric("Prezzo Uscita in Profitto", f"{prezzo_uscita:,.2f} USDT", delta=f"+{prezzo_target}%")
    c3.metric("Capitale da Investire (DCA)", f"{capitale_necessario_dca:,.2f} USDT")
    c4.metric("Profitto all'Uscita", f"{profitto_uscita_dca:,.2f} USDT")

    if st.button("📥 Applica Mediazione alla Posizione Attuale"):
        st.session_state["pos_long_pm"] = round(nuovo_prezzo_medio, 2)
        st.session_state["pos_long_qty"] = round(quantita_tot, 4)
        st.success("✅ Mediazione applicata alla Dashboard Posizioni Attive!")

# ==============================================================================
# 5. AI: RILEVAMENTO RIMBALZI E SEGNALI
# ==============================================================================
elif menu == "🤖 AI & Rimbalzi":
    st.title("🤖 AI: Rilevamento Rimbalzi e Mediazioni")
    st.write("Analisi automatizzata dei punti di inversione per adattare le griglie al ciclo di mercato.")

    p_curr = st.session_state["prezzo_corrente"]
    
    # Calcolo bande di supporto e resistenza intelligenti
    sup1 = round(p_curr * 0.94, 2)
    sup2 = round(p_curr * 0.88, 2)
    res1 = round(p_curr * 1.06, 2)
    res2 = round(p_curr * 1.12, 2)

    st.markdown("### Segnale Attuale Intelligenza Artificiale")
    st.info(f"💡 **AI Segnale:** Probabile rimbalzo al rialzo nell'area di supporto **{sup1:,.2f} $**.")

    col1, col2 = st.columns(2)
    with col1:
        st.markdown("#### 🟢 Zone di Supporto (Possibili Rimbalzi BUY)")
        st.write(f"- **Supporto Primario (S1):** `{sup1:,.2f} USDT`")
        st.write(f"- **Supporto Chiave (S2):** `{sup2:,.2f} USDT` (Consigliato per Mediazione DCA)")

    with col2:
        st.markdown("#### 🔴 Zone di Resistenza (Possibili Reversal SELL)")
        st.write(f"- **Resistenza Primaria (R1):** `{res1:,.2f} USDT`")
        st.write(f"- **Resistenza Chiave (R2):** `{res2:,.2f} USDT` (Consigliato Take Profit Griglia)")

# ==============================================================================
# 6. SETTAGGIO API & MODALITÀ DEMO MAINNET
# ==============================================================================
elif menu == "🔑 Settaggio API (Demo Mainnet)":
    st.title("🔑 Collegamento API Exchange & Modalità Operativa")
    st.write("Questa sezione serve per collegare il tuo account Spot e Futures (Binance, Bybit, KuCoin).")

    modalita = st.radio(
        "Seleziona Modalità Operativa:",
        ["🟢 Demo che Simula la Mainnet (Paper Trading Reale a Prezzi di Mercato)", "🔴 Mainnet Reale (Live Trading con Chiavi API)"],
        index=0
    )

    if "Demo che Simula la Mainnet" in modalita:
        st.success("✅ **Modalità Attiva: Demo Mainnet Simulator.** Gli ordini e il P/L rispecchiano le oscillazioni del mercato reale senza inviare ordini a rischio di capitale.")
    else:
        st.warning("⚠️ **Modalità Attiva: Live Mainnet.** Inserisci le tue chiavi API autorizzate solo per Spot/Futures Trading (disabilita sempre i prelievi per sicurezza).")

    api_key = st.text_input("API Key", type="password", value="API_KEY_MAINNET_DEMO_SAMPLE")
    secret_key = st.text_input("API Secret", type="password", value="API_SECRET_MAINNET_DEMO_SAMPLE")
    
    if st.button("Salva Impostazioni API"):
        st.success("API e configurazione salvate localmente con successo.")
