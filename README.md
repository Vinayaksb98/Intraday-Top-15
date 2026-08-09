# BOP Top 15 — Mobile Web Version

This is a mobile-friendly Streamlit dashboard for the custom BOP research strategy.

## Test on a computer
pip install -r requirements.txt
streamlit run app.py

## Publish online
The project is deployment-ready for Streamlit Community Cloud or another Python web host.
After deployment, the host supplies a public HTTPS URL that can be opened from Android/iPhone.

## Data
The free mode uses Yahoo Finance daily data and is not a guaranteed real-time exchange feed.
True live NSE streaming requires an appropriate broker/market-data API.

Never put Zerodha passwords, PINs, OTPs, API secrets, or access tokens in the source code.
