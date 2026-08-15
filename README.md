# BOP-PRE NSE Scanner v3

## Important change
This version **does not ask the user to upload a CSV**.

At startup it automatically:
1. Downloads the current NIFTY 500 constituent list from Nifty Indices.
2. Gets current market-cap data.
3. Applies `NIFTY 500 AND Market Cap >= ₹10,000 Cr`.
4. Runs the BOP-PRE technical scanner.
5. Returns the Top 15 candidates with Entry, Stop Loss, Target 1 and Target 2.

Market-cap lookup uses the public Nifty 500 constituent pages from Screener, with a yfinance fallback when a symbol is missing.

## GitHub / Streamlit Cloud files

Upload:
- `app.py`
- `requirements.txt`
- `README.md`

No CSV upload is required.

## Run

```bash
pip install -r requirements.txt
streamlit run app.py
```

## Why this is better
The previous version used a Streamlit file uploader and therefore repeatedly asked for a CSV. That was unnecessary for your intended scanner. This version builds the universe automatically.

The scanner also reports skipped stocks and their errors instead of silently returning "No results".

## Strategy
Universe:
- NIFTY 500
- Market cap >= ₹10,000 Cr

Indicators:
- BOP
- RSI
- EMA20/EMA50
- ATR
- Bollinger compression
- Relative volume
- OBV
- Relative strength vs NIFTY
- 20-day resistance

Outputs:
- Score
- Entry zone
- Stop loss
- Target 1
- Target 2
- Risk/reward
- Supporting indicators

This is a research/decision-support scanner, not a guarantee of next-day price movement.
