
import streamlit as st
import pandas as pd
import numpy as np
import random

# ---------------------- LOGIN ----------------------
def check_login():
    with st.form("login_form", clear_on_submit=False):
        st.subheader("Accesso richiesto")
        username = st.text_input("Username")
        password = st.text_input("Password", type="password")
        login_button = st.form_submit_button("Accedi")
        if login_button:
            if username == "Galva94" and password == "Gianmarco94":
                st.session_state["logged_in"] = True
                st.experimental_rerun()
            else:
                st.error("Credenziali errate.")
                st.stop()

if "logged_in" not in st.session_state:
    check_login()

# ---------------------- MENU NAVIGAZIONE ----------------------
st.sidebar.title("Menu")
menu = st.sidebar.radio("Naviga tra le sezioni:", [
    "Dashboard", "Backtest", "Settaggio Strategia", "Settaggio API", "Calcola Mediazione"
])

# ---------------------- DASHBOARD ----------------------
if menu == "Dashboard":
    st.title("📈 Dashboard")
    st.subheader("Storico Operazioni (Esempio)")
    df = pd.DataFrame({
        "Data": pd.date_range(end=pd.Timestamp.today(), periods=10).strftime('%Y-%m-%d'),
        "Operazione": ["LONG", "SHORT"] * 5,
        "Profitto (USDT)": np.random.randint(-30, 100, size=10)
    })
    st.dataframe(df)

    st.subheader("Grafico Profit/Loss")
    st.line_chart(df["Profitto (USDT)"].cumsum())

# ---------------------- BACKTEST ----------------------
elif menu == "Backtest":
    st.title("🔄 Simulazione / Backtest")
    st.write("Simula un'azione di prezzo e vedi il guadagno mensile potenziale.")

    profitto_per_griglia = st.number_input("Profitto per griglia (USDT)", value=10)
    mesi = ["Gennaio", "Febbraio", "Marzo", "Aprile", "Maggio", "Giugno",
            "Luglio", "Agosto", "Settembre", "Ottobre", "Novembre", "Dicembre"]

    col1, col2, col3 = st.columns(3)
    guadagni = []
    for i, mese in enumerate(mesi):
        with [col1, col2, col3][i % 3]:
            griglie = st.number_input(f"{mese}", value=0, min_value=0, key=mese)
            guadagno = griglie * profitto_per_griglia
            guadagni.append(guadagno)
            st.write(f"Guadagno: {guadagno:.2f} USDT")

    st.success(f"Guadagno Totale Annuo: {sum(guadagni):,.2f} USDT")

# ---------------------- SETTAGGIO STRATEGIA ----------------------
elif menu == "Settaggio Strategia":
    st.title("⚙️ Configurazione Strategia")
    range_min = st.number_input("Range Minimo", value=30000)
    range_max = st.number_input("Range Massimo", value=110000)
    distanza_griglia = st.number_input("Distanza Griglia (%)", value=0.5)
    take_profit = st.number_input("Take Profit per Griglia (%)", value=1.0)
    profitto_target = st.number_input("Profitto per Griglia (USDT)", value=10)
    capitale_operativo_pct = st.slider("Percentuale Capitale Operativo", 10, 100, 50)
    capitale_riserva_pct = 100 - capitale_operativo_pct

    num_griglie = (range_max - range_min) / (range_min * (distanza_griglia / 100))
    cap_griglia = profitto_target / (take_profit / 100)
    cap_op = cap_griglia * num_griglie
    cap_tot = cap_op / (capitale_operativo_pct / 100)

    st.markdown("### Calcoli automatici")
    st.metric("Numero Griglie", f"{int(num_griglie)}")
    st.metric("Capitale per Griglia", f"{cap_griglia:,.2f} USDT")
    st.metric("Capitale Totale Richiesto", f"{cap_tot:,.2f} USDT")
    st.metric("Riserva (non impegnata)", f"{cap_tot - cap_op:,.2f} USDT")

# ---------------------- SETTAGGIO API ----------------------
elif menu == "Settaggio API":
    st.title("🔑 Collegamento API Exchange")
    st.info("Questa sezione serve per collegare il tuo account Spot e Futures.")
    api_key = st.text_input("API Key", type="password")
    secret_key = st.text_input("API Secret", type="password")
    if st.button("Salva API"):
        st.success("API salvate localmente (simulato).")

# ---------------------- CALCOLA MEDIAZIONE ----------------------
elif menu == "Calcola Mediazione":
    st.title("🧮 Calcolo Mediazione")
    st.write("Calcola quanto capitale serve per mediare una posizione in perdita e portarla in profitto.")

    prezzo_ingresso = st.number_input("Prezzo medio ingresso", value=30000)
    prezzo_attuale = st.number_input("Prezzo attuale", value=27000)
    quantita_iniziale = st.number_input("Quantità iniziale (BTC)", value=1.0)
    quantita_da_aggiungere = st.number_input("Quantità da aggiungere (BTC)", value=1.0)

    nuovo_prezzo_medio = (prezzo_ingresso * quantita_iniziale + prezzo_attuale * quantita_da_aggiungere) / (quantita_iniziale + quantita_da_aggiungere)
    prezzo_target = st.number_input("Target uscita profitto (%)", value=0.3)
    prezzo_uscita = nuovo_prezzo_medio * (1 + prezzo_target / 100)

    st.metric("Nuovo prezzo medio", f"{nuovo_prezzo_medio:,.2f} USDT")
    st.metric("Prezzo uscita in profitto", f"{prezzo_uscita:,.2f} USDT")
