# BOP-PRE NSE Scanner

Streamlit scanner for:

**NIFTY 500 → Market Cap ≥ ₹10,000 Cr → Pre-breakout scoring → Top 15 → Entry/SL/Targets**

## Files

- `app.py` — main Streamlit application
- `requirements.txt` — dependencies
- `README.md` — instructions
- `data/nifty500_marketcap.csv` — universe input

## Required universe CSV

The CSV must contain:

```csv
symbol,market_cap_crore,index
RELIANCE,1500000,NIFTY 500
TCS,1300000,NIFTY 500
```

The app automatically keeps only:

- index = NIFTY 500
- market_cap_crore >= 10000

If you upload the CSV through Streamlit, it overrides the repository CSV.

## Run locally

```bash
pip install -r requirements.txt
streamlit run app.py
```

## GitHub / Streamlit Cloud

Upload the files to your repository root:

```text
app.py
requirements.txt
README.md
data/nifty500_marketcap.csv
```

Set the Streamlit main file to `app.py`.

## Strategy outputs

The scanner ranks eligible stocks and reports:

- BOP-PRE score
- Entry Low / Entry High
- Stop Loss
- Target 1
- Target 2
- Risk/reward
- Resistance distance
- RSI
- Relative strength
- Volume and volatility information

Targets are research estimates based on volatility and market structure; they are not guaranteed prices.
