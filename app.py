
import streamlit as st
import pandas as pd
import numpy as np
import yfinance as yf

st.set_page_config(page_title="BOP-PRE NSE Scanner", layout="wide")

MIN_MARKET_CAP_CR = 10000
TOP_N = 15

st.title("BOP-PRE NSE Pre-Breakout Scanner")
st.caption("Universe: NIFTY 500 | Market Cap ≥ ₹10,000 Cr | Top 15 candidates")

@st.cache_data(ttl=3600)
def load_universe(uploaded_file=None):
    if uploaded_file is not None:
        df = pd.read_csv(uploaded_file)
    else:
        path = "data/nifty500_marketcap.csv"
        try:
            df = pd.read_csv(path)
        except FileNotFoundError:
            return pd.DataFrame()

    df.columns = [str(c).strip().lower() for c in df.columns]
    rename = {
        "ticker":"symbol", "nse_symbol":"symbol",
        "market cap":"market_cap_crore", "market_cap":"market_cap_crore",
        "marketcap":"market_cap_crore"
    }
    df = df.rename(columns=rename)

    required = {"symbol", "market_cap_crore"}
    if not required.issubset(df.columns):
        st.error("Universe CSV must contain: symbol, market_cap_crore")
        return pd.DataFrame()

    if "index" in df.columns:
        df = df[df["index"].astype(str).str.upper().eq("NIFTY 500")]

    df["market_cap_crore"] = pd.to_numeric(df["market_cap_crore"], errors="coerce")
    df = df[df["market_cap_crore"] >= MIN_MARKET_CAP_CR].copy()
    df["symbol"] = df["symbol"].astype(str).str.upper().str.replace(".NS","",regex=False)
    return df.drop_duplicates("symbol").reset_index(drop=True)

def rsi(s, n=14):
    d = s.diff()
    up = d.clip(lower=0).ewm(alpha=1/n, adjust=False).mean()
    dn = (-d.clip(upper=0)).ewm(alpha=1/n, adjust=False).mean()
    rs = up / dn.replace(0, np.nan)
    return (100 - 100/(1+rs)).fillna(50)

def indicators(df, market):
    x = df.copy()
    x["EMA20"] = x["Close"].ewm(span=20, adjust=False).mean()
    x["EMA50"] = x["Close"].ewm(span=50, adjust=False).mean()
    x["RSI"] = rsi(x["Close"])
    x["ROC5"] = x["Close"].pct_change(5) * 100
    prev = x["Close"].shift(1)
    tr = pd.concat([
        x["High"]-x["Low"],
        (x["High"]-prev).abs(),
        (x["Low"]-prev).abs()
    ], axis=1).max(axis=1)
    x["ATR"] = tr.ewm(alpha=1/14, adjust=False).mean()
    x["ATRpct"] = 100*x["ATR"]/x["Close"]
    mid = x["Close"].rolling(20).mean()
    sd = x["Close"].rolling(20).std()
    x["BBWidth"] = 4*sd/mid.replace(0,np.nan)
    x["BBRank"] = x["BBWidth"].rolling(60).rank(pct=True)
    x["RVOL"] = x["Volume"]/x["Volume"].rolling(20).mean()
    direction = np.sign(x["Close"].diff()).fillna(0)
    x["OBV"] = (direction*x["Volume"]).cumsum()
    x["OBVSlope"] = x["OBV"].pct_change(5)
    x["BOP"] = (x["Close"]-x["Open"])/(x["High"]-x["Low"]).replace(0,np.nan)
    x["BOP5"] = x["BOP"].rolling(5).mean()
    x["Resistance"] = x["High"].shift(1).rolling(20).max()
    x["DistRes"] = 100*(x["Resistance"]-x["Close"])/x["Close"]
    x["MFI"] = 50.0
    if market is not None and not market.empty:
        mroc = market["Close"].pct_change(5).reindex(x.index) * 100
        x["RS5"] = x["ROC5"] - mroc
    else:
        x["RS5"] = 0.0
    return x.dropna()

def score_and_targets(x):
    r = x.iloc[-1]
    prev = x.iloc[-2]
    score = 0
    reasons = []

    checks = [
        (r.Close > r.EMA20, 5, "above EMA20"),
        (r.EMA20 > r.EMA50, 5, "EMA20 above EMA50"),
        (r.Close > r.EMA50, 5, "above EMA50"),
        (r.EMA20 > prev.EMA20, 5, "EMA20 rising"),
        (52 <= r.RSI <= 68, 6, "constructive RSI"),
        (r.RSI > prev.RSI, 4, "RSI rising"),
        (r.ROC5 > 0, 5, "positive ROC"),
        (r.BBRank <= .35, 10, "volatility compression"),
        (r.ATRpct <= prev.ATRpct, 5, "ATR contracting"),
        (.65 <= r.RVOL <= 1.35, 5, "healthy volume"),
        (r.OBVSlope > 0, 5, "OBV rising"),
        (r.BOP5 > 0, 5, "positive BOP"),
        (r.BOP > 0, 5, "today BOP positive"),
        (0 <= r.DistRes <= 3, 10, "within 3% of resistance"),
        (0 <= r.DistRes <= 1.5, 5, "very close to breakout"),
        (r.RS5 > 0, 5, "positive relative strength"),
    ]
    for ok, pts, txt in checks:
        if bool(ok):
            score += pts
            reasons.append(txt)

    risk = max(.75*r.ATR, .0125*r.Close)
    low10 = x["Low"].rolling(10).min().iloc[-1]
    stop = min(low10-.25*r.ATR, r.Close-risk)
    risk_abs = r.Close-stop
    t1 = r.Close + 1.5*risk_abs
    if pd.notna(r.Resistance) and r.Resistance > r.Close:
        t1 = max(r.Close+.75*risk_abs, min(r.Resistance, t1))
    t2 = max(r.Close+2.5*risk_abs, t1+.5*risk_abs)

    entry_high = min(r.Close+.5*r.ATR,
                     r.Resistance if pd.notna(r.Resistance) else r.Close+r.ATR)
    signal = "PRE-BREAKOUT A" if score >= 80 else (
             "PRE-BREAKOUT B" if score >= 70 else (
             "WATCH" if score >= 60 else "IGNORE"))

    return {
        "Score": min(score,100), "Signal": signal,
        "Close": r.Close, "Entry Low": r.Close, "Entry High": entry_high,
        "Stop Loss": stop, "Target 1": t1, "Target 2": t2,
        "RR T1": (t1-r.Close)/risk_abs if risk_abs else np.nan,
        "RR T2": (t2-r.Close)/risk_abs if risk_abs else np.nan,
        "Resistance": r.Resistance, "Distance to Resistance %": r.DistRes,
        "RSI": r.RSI, "ROC5 %": r.ROC5, "ATR %": r.ATRpct,
        "RVOL": r.RVOL, "BOP": r.BOP, "OBV 5D": r.OBVSlope,
        "Relative Strength 5D": r.RS5, "Reasons": "; ".join(reasons)
    }

@st.cache_data(ttl=900)
def get_history(symbol):
    return yf.download(symbol + ".NS", period="1y", interval="1d",
                       auto_adjust=False, progress=False)

@st.cache_data(ttl=900)
def get_nifty():
    return yf.download("^NSEI", period="1y", interval="1d",
                       auto_adjust=False, progress=False)

uploaded = st.file_uploader(
    "Upload current NIFTY 500 universe CSV (columns: symbol, market_cap_crore; optional: index)",
    type=["csv"]
)
universe = load_universe(uploaded)

if universe.empty:
    st.warning(
        "No universe file is loaded. Put data/nifty500_marketcap.csv in the repository "
        "or upload a CSV with symbol and market_cap_crore."
    )
    st.stop()

st.success(f"Eligible universe: {len(universe)} stocks (NIFTY 500, market cap ≥ ₹{MIN_MARKET_CAP_CR:,} Cr).")

if st.button("Run BOP-PRE Scan", type="primary"):
    nifty = get_nifty()
    if isinstance(nifty.columns, pd.MultiIndex):
        nifty.columns = nifty.columns.get_level_values(0)
    results = []
    progress = st.progress(0)

    for i, row in universe.iterrows():
        symbol = row["symbol"]
        try:
            hist = get_history(symbol)
            if hist.empty:
                continue
            if isinstance(hist.columns, pd.MultiIndex):
                hist.columns = hist.columns.get_level_values(0)
            hist = hist[["Open","High","Low","Close","Volume"]].dropna()
            if len(hist) < 100:
                continue
            x = indicators(hist, nifty)
            if len(x) < 2:
                continue
            result = score_and_targets(x)
            result["Symbol"] = symbol
            result["Market Cap (Cr)"] = row["market_cap_crore"]
            results.append(result)
        except Exception as e:
            pass
        progress.progress((i+1)/len(universe))

    if results:
        out = pd.DataFrame(results).sort_values(
            ["Score","Distance to Resistance %"], ascending=[False,True]
        ).head(TOP_N)
        st.subheader("Top 15 Pre-Breakout Candidates")
        st.dataframe(out, use_container_width=True, hide_index=True)
        st.download_button(
            "Download Top 15 CSV",
            out.to_csv(index=False).encode("utf-8"),
            "bop_pre_top15.csv",
            "text/csv"
        )
    else:
        st.error("No results were produced. Check the universe CSV and market-data access.")
