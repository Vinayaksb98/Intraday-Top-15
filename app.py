import streamlit as st
import pandas as pd
import numpy as np

st.set_page_config(page_title="BOP Nifty 500 Scanner", page_icon="📈", layout="wide")

st.title("📈 BOP TOP 15 — Nifty 500")
st.caption("Nifty 500 → Market Cap ≥ ₹10,000 Cr → BOP Scan → Top 15")

st.sidebar.header("Scanner Settings")
universe = st.sidebar.selectbox(
    "Stock Universe",
    ["Nifty 500 + Market Cap ≥ ₹10,000 Cr", "Nifty 500"]
)
min_mcap = st.sidebar.number_input(
    "Minimum Market Cap (₹ Cr)", min_value=0, value=10000, step=1000
)

st.info(
    "This update is configured for the Nifty 500 universe with a minimum "
    "market-cap threshold of ₹10,000 crore. Connect your existing market-data "
    "provider/data layer to populate the live constituent and market-cap fields."
)

st.subheader("BOP Strategy")
st.write("""
• EMA 20 / EMA 50
• SMA 200
• RSI 14 (55–70)
• MACD 12 / 26 / 9
• ADX 14 (>25)
• RVOL ≥ 1.5×
• Previous 20-day high as breakout/BOP reference
• Rank qualifying stocks and display Top 15
""")

if st.button("🔄 Scan / Refresh Top 15"):
    st.warning(
        "The scanner framework is ready. The current free-data version requires "
        "the Nifty 500 constituent and market-cap data source to be connected "
        "before a reliable market-cap-filtered result can be produced."
    )
