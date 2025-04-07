
import streamlit as st
import random

st.set_page_config(page_title="Strategia Griglia Bidirezionale", layout="wide")
st.title("Strategia Griglia Bidirezionale con AI")

# --- Sezione Configurazione ---
st.header("1. Configurazione Strategia")

col1, col2 = st.columns(2)
with col1:
    range_min = st.number_input("Range Minimo (es. 30000)", value=30000)
    distanza_griglia = st.number_input("Distanza Griglia (%)", value=0.5, step=0.1)
    take_profit = st.number_input("Take Profit per Griglia (%)", value=1.0, step=0.1)
    profitto_per_griglia = st.number_input("Profitto desiderato per griglia (USDT)", value=10)
with col2:
    range_max = st.number_input("Range Massimo (es. 110000)", value=110000)
    cap_operativo_pct = st.slider("Percentuale Capitale Operativo", 10, 100, 50)
    cap_riserva_pct = 100 - cap_operativo_pct
    st.write(f"Percentuale Capitale di Riserva: {cap_riserva_pct}%")

# --- Calcoli automatici ---
st.header("2. Calcoli Automatici")

num_griglie = (range_max - range_min) / (range_min * (distanza_griglia / 100))
capitale_per_griglia = profitto_per_griglia / (take_profit / 100)
capitale_operativo = capitale_per_griglia * num_griglie
capitale_totale = capitale_operativo / (cap_operativo_pct / 100)
capitale_riserva = capitale_totale - capitale_operativo

st.metric("Numero Griglie", f"{int(num_griglie)}")
st.metric("Capitale per Griglia", f"{capitale_per_griglia:,.2f} USDT")
st.metric("Capitale Operativo Totale", f"{capitale_operativo:,.2f} USDT")
st.metric("Capitale di Riserva", f"{capitale_riserva:,.2f} USDT")
st.metric("Capitale Totale Necessario", f"{capitale_totale:,.2f} USDT")

# --- Simulazione Mensile ---
st.header("3. Simulazione Guadagno Mensile")
st.write("Inserisci quante griglie si chiuderebbero ogni mese per stimare il guadagno.")
mesi = ["Gennaio", "Febbraio", "Marzo", "Aprile", "Maggio", "Giugno",
        "Luglio", "Agosto", "Settembre", "Ottobre", "Novembre", "Dicembre"]

col1, col2, col3 = st.columns(3)
guadagni = []
for i, mese in enumerate(mesi):
    with [col1, col2, col3][i % 3]:
        griglie_chiuse = st.number_input(f"{mese}", min_value=0, value=0, key=mese)
        guadagno = griglie_chiuse * profitto_per_griglia
        guadagni.append(guadagno)
        st.write(f"Guadagno: {guadagno:.2f} USDT")

guadagno_annuale = sum(guadagni)
st.subheader(f"Guadagno Totale Annuo Stimato: {guadagno_annuale:.2f} USDT")

# --- AI simulata per rimbalzo ---
st.header("4. AI: Rilevamento Rimbalzi e Mediazioni")
ai_rimbalzo = random.choice(["Nessun segnale", "Probabile rimbalzo al rialzo", "Probabile rimbalzo al ribasso"])
st.warning(f"AI: {ai_rimbalzo}")

# --- Dashboard Posizioni Attuali ---
st.header("5. Dashboard P/L e Esposizione")

prezzo_medio_long = st.number_input("Prezzo medio posizioni LONG", value=40000)
quantita_long = st.number_input("Quantità LONG (BTC)", value=0.5)
prezzo_medio_short = st.number_input("Prezzo medio posizioni SHORT", value=80000)
quantita_short = st.number_input("Quantità SHORT (BTC)", value=0.3)
prezzo_corrente = st.number_input("Prezzo Attuale BTC", value=70000)

pl_long = (prezzo_corrente - prezzo_medio_long) * quantita_long
pl_short = (prezzo_medio_short - prezzo_corrente) * quantita_short
pl_totale = pl_long + pl_short

col1, col2, col3 = st.columns(3)
col1.metric("P/L LONG", f"{pl_long:.2f} USDT")
col2.metric("P/L SHORT", f"{pl_short:.2f} USDT")
col3.metric("P/L Totale", f"{pl_totale:.2f} USDT")

# --- Sbilanciamento ed esposizione ---
st.subheader("Esposizione e Sbilanciamento")
st.write(f"Esposizione LONG: {quantita_long:.4f} BTC")
st.write(f"Esposizione SHORT: {quantita_short:.4f} BTC")
sbilanciamento = quantita_long - quantita_short
st.write(f"Sbilanciamento netto: {sbilanciamento:.4f} BTC")
