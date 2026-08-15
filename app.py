
import streamlit as st
import pandas as pd
import numpy as np
import yfinance as yf
import requests
from io import StringIO
import time

st.set_page_config(page_title="BOP-PRE NSE Scanner", layout="wide")

MIN_MARKET_CAP_CR = 10000
TOP_N = 15

st.title("BOP-PRE NSE Pre-Breakout Scanner")
st.caption("Automatic universe: NIFTY 500 → Market Cap ≥ ₹10,000 Cr → Top 15")

@st.cache_data(ttl=12*3600)
def fetch_nifty500_constituents():
    urls = [
        "https://www.niftyindices.com/IndexConstituent/ind_nifty500list.csv",
        "https://www.niftyindices.com/IndexConstituent/ind_nifty500list.csv?download=1",
    ]
    headers = {
        "User-Agent": "Mozilla/5.0",
        "Referer": "https://www.niftyindices.com/",
        "Accept": "text/csv,application/octet-stream,*/*"
    }
    last_error = None
    for url in urls:
        try:
            r = requests.get(url, headers=headers, timeout=30)
            r.raise_for_status()
            df = pd.read_csv(StringIO(r.text))
            df.columns = [str(c).strip() for c in df.columns]
            sym = next((c for c in df.columns if c.lower() in ["symbol", "ticker"]), None)
            if sym is None:
                raise ValueError("Nifty 500 CSV did not contain a Symbol column.")
            out = pd.DataFrame({"symbol": df[sym].astype(str).str.upper().str.strip()})
            return out.drop_duplicates("symbol").reset_index(drop=True)
        except Exception as e:
            last_error = e
    raise RuntimeError(f"Could not download the current NIFTY 500 constituent list: {last_error}")

@st.cache_data(ttl=6*3600)
def fetch_market_caps(symbols):
    """
    Market-cap source: Screener Nifty 500 public constituent pages.
    Fallback: yfinance Ticker.info for symbols not found.
    """
    rows = []
    headers = {"User-Agent": "Mozilla/5.0"}
    for page in range(1, 21):
        try:
            url = f"https://www.screener.in/company/CNX500/?page={page}&order=desc&sort=market+capitalization"
            html = requests.get(url, headers=headers, timeout=20).text
            tables = pd.read_html(StringIO(html))
            table = next((t for t in tables if any("Mar Cap" in str(c) for c in t.columns)), None)
            if table is None:
                continue
            # Typical Screener columns: Name, CMP Rs., P/E, Mar Cap Rs.Cr., ...
            name_col = next((c for c in table.columns if str(c).lower().startswith("name")), None)
            cap_col = next((c for c in table.columns if "mar cap" in str(c).lower()), None)
            if name_col is None or cap_col is None:
                continue
            for _, rr in table.iterrows():
                name = str(rr[name_col])
                cap = pd.to_numeric(str(rr[cap_col]).replace(",",""), errors="coerce")
                m = name.upper()
                # Match against known symbols by finding the symbol in the name field.
                matched = next((s for s in symbols if re_search_symbol(s, m)), None)
                if matched and pd.notna(cap):
                    rows.append({"symbol": matched, "market_cap_crore": float(cap)})
        except Exception:
            pass
    caps = pd.DataFrame(rows).drop_duplicates("symbol") if rows else pd.DataFrame(columns=["symbol","market_cap_crore"])

    # Fallback for any missing symbols. This is slower but avoids a hard failure.
    missing = [s for s in symbols if s not in set(caps["symbol"])]
    for i, s in enumerate(missing):
        try:
            info = yf.Ticker(s + ".NS").fast_info
            # fast_info normally has market_cap on current yfinance versions.
            mc = info.get("market_cap", np.nan)
            if pd.notna(mc):
                caps.loc[len(caps)] = [s, float(mc)/1e7]  # INR -> crore
        except Exception:
            try:
                info = yf.Ticker(s + ".NS").info
                mc = info.get("marketCap", np.nan)
                if pd.notna(mc):
                    caps.loc[len(caps)] = [s, float(mc)/1e7]
            except Exception:
                pass
        if i and i % 25 == 0:
            time.sleep(.2)
    return caps.drop_duplicates("symbol").reset_index(drop=True)

def re_search_symbol(symbol, text):
    import re
    return re.search(rf"(?<![A-Z0-9]){re.escape(symbol)}(?![A-Z0-9])", text) is not None

def get_universe():
    cons = fetch_nifty500_constituents()
    caps = fetch_market_caps(cons["symbol"].tolist())
    u = cons.merge(caps, on="symbol", how="inner")
    u = u[pd.to_numeric(u.market_cap_crore, errors="coerce") >= MIN_MARKET_CAP_CR].copy()
    u["market_cap_crore"] = pd.to_numeric(u["market_cap_crore"], errors="coerce")
    return u.sort_values("market_cap_crore", ascending=False).reset_index(drop=True)

def rsi(s, n=14):
    d=s.diff()
    up=d.clip(lower=0).ewm(alpha=1/n, adjust=False).mean()
    dn=(-d.clip(upper=0)).ewm(alpha=1/n, adjust=False).mean()
    rs=up/dn.replace(0,np.nan)
    return (100-100/(1+rs)).fillna(50)

def prepare(df, market):
    x=df.copy()
    x["EMA20"]=x.Close.ewm(span=20,adjust=False).mean()
    x["EMA50"]=x.Close.ewm(span=50,adjust=False).mean()
    x["RSI"]=rsi(x.Close)
    x["ROC5"]=x.Close.pct_change(5)*100
    p=x.Close.shift(1)
    tr=pd.concat([x.High-x.Low,(x.High-p).abs(),(x.Low-p).abs()],axis=1).max(axis=1)
    x["ATR"]=tr.ewm(alpha=1/14,adjust=False).mean()
    x["ATRpct"]=100*x.ATR/x.Close
    mid=x.Close.rolling(20).mean(); sd=x.Close.rolling(20).std()
    x["BBWidth"]=4*sd/mid.replace(0,np.nan)
    x["BBRank"]=x.BBWidth.rolling(60).rank(pct=True)
    x["RVOL"]=x.Volume/x.Volume.rolling(20).mean()
    x["OBV"]=(np.sign(x.Close.diff()).fillna(0)*x.Volume).cumsum()
    x["OBVSlope"]=x.OBV.pct_change(5)
    x["BOP"]=(x.Close-x.Open)/(x.High-x.Low).replace(0,np.nan)
    x["BOP5"]=x.BOP.rolling(5).mean()
    x["Resistance"]=x.High.shift(1).rolling(20).max()
    x["DistRes"]=100*(x.Resistance-x.Close)/x.Close
    if market is not None and len(market):
        x["RS5"]=x.ROC5-(market.Close.pct_change(5).reindex(x.index)*100)
    else: x["RS5"]=0
    return x.replace([np.inf,-np.inf],np.nan).dropna()

def score(x):
    r=x.iloc[-1]; p=x.iloc[-2]; s=0; why=[]
    tests=[
        (r.Close>r.EMA20,5,"above EMA20"),(r.EMA20>r.EMA50,5,"EMA20>EMA50"),
        (r.Close>r.EMA50,5,"above EMA50"),(r.EMA20>p.EMA20,5,"EMA20 rising"),
        (52<=r.RSI<=68,6,"constructive RSI"),(r.RSI>p.RSI,4,"RSI rising"),
        (r.ROC5>0,5,"positive ROC"),(r.BBRank<=.35,10,"volatility compression"),
        (r.ATRpct<=p.ATRpct,5,"ATR contracting"),(.65<=r.RVOL<=1.35,5,"healthy volume"),
        (r.OBVSlope>0,5,"OBV rising"),(r.BOP5>0,5,"positive BOP"),
        (r.BOP>0,5,"today BOP positive"),(0<=r.DistRes<=3,10,"within 3% resistance"),
        (0<=r.DistRes<=1.5,5,"very close breakout"),(r.RS5>0,5,"positive relative strength")
    ]
    for ok,pts,msg in tests:
        if bool(ok): s+=pts; why.append(msg)
    risk=max(.75*r.ATR,.0125*r.Close)
    low10=x.Low.rolling(10).min().iloc[-1]
    stop=min(low10-.25*r.ATR,r.Close-risk)
    risk_abs=max(r.Close-stop,0.01)
    t1=r.Close+1.5*risk_abs
    if pd.notna(r.Resistance) and r.Resistance>r.Close:
        t1=max(r.Close+.75*risk_abs,min(r.Resistance,t1))
    t2=max(r.Close+2.5*risk_abs,t1+.5*risk_abs)
    entry_hi=min(r.Close+.5*r.ATR,r.Resistance if pd.notna(r.Resistance) else r.Close+r.ATR)
    score=min(s,100)
    confidence = ("VERY HIGH" if score>=85 else "HIGH" if score>=80 else
                  "MODERATE" if score>=70 else "LOW" if score>=60 else "VERY LOW")
    # A setup is NOT an automatic buy. The safer trigger is confirmation above resistance
    # with stronger-than-normal volume. Until that occurs, the scanner says WAIT.
    breakout_confirmed = bool(pd.notna(r.Resistance) and r.Close > r.Resistance and r.RVOL >= 1.20 and r.BOP > 0)
    action = "BUY / BREAKOUT CONFIRMED" if breakout_confirmed and score>=80 else (
             "BUY ON BREAKOUT" if score>=80 else (
             "WATCH" if score>=70 else "AVOID"))
    sig="A+" if score>=85 else "A" if score>=80 else "B" if score>=70 else "C" if score>=60 else "D"
    trend_score = int(sum([r.Close>r.EMA20, r.EMA20>r.EMA50, r.Close>r.EMA50, r.EMA20>p.EMA20]) / 4 * 100)
    momentum_score = int(sum([52<=r.RSI<=68, r.RSI>p.RSI, r.ROC5>0, r.BOP>0]) / 4 * 100)
    volume_score = int(sum([.65<=r.RVOL<=1.35, r.OBVSlope>0]) / 2 * 100)
    breakout_score = int(sum([r.BBRank<=.35, r.ATRpct<=p.ATRpct, 0<=r.DistRes<=3, 0<=r.DistRes<=1.5]) / 4 * 100)
    relative_score = int(r.RS5>0)*100
    rr1=(t1-r.Close)/risk_abs
    rr2=(t2-r.Close)/risk_abs
    return {
        "Score":score,"Grade":sig,"Confidence":confidence,"Action":action,
        "Close":r.Close,"Entry Low":r.Close,"Entry High":entry_hi,
        "Stop Loss":stop,"Target 1":t1,"Target 2":t2,"RR T1":rr1,"RR T2":rr2,
        "Resistance":r.Resistance,"Distance to Resistance %":r.DistRes,
        "Trend %":trend_score,"Momentum %":momentum_score,"Volume %":volume_score,
        "Breakout Setup %":breakout_score,"Relative Strength %":relative_score,
        "RSI":r.RSI,"ROC5 %":r.ROC5,"ATR %":r.ATRpct,"RVOL":r.RVOL,
        "BOP":r.BOP,"OBV 5D":r.OBVSlope,"Relative Strength 5D":r.RS5,
        "Breakout Confirmed": "YES" if breakout_confirmed else "NO",
        "Reasons":"; ".join(why)
    }

@st.cache_data(ttl=900)
def download_history(symbol):
    d=yf.download(symbol+".NS",period="1y",interval="1d",auto_adjust=False,progress=False,threads=False)
    if isinstance(d.columns,pd.MultiIndex): d.columns=d.columns.get_level_values(0)
    return d[["Open","High","Low","Close","Volume"]].dropna()

@st.cache_data(ttl=900)
def download_nifty():
    d=yf.download("^NSEI",period="1y",interval="1d",auto_adjust=False,progress=False,threads=False)
    if isinstance(d.columns,pd.MultiIndex): d.columns=d.columns.get_level_values(0)
    return d[["Open","High","Low","Close","Volume"]].dropna()

if "universe" not in st.session_state:
    st.session_state.universe=None

if st.button("Refresh NIFTY 500 Universe"):
    with st.spinner("Downloading current NIFTY 500 constituents and market caps..."):
        try:
            st.session_state.universe=get_universe()
        except Exception as e:
            st.error(f"Universe download failed: {e}")

if st.session_state.universe is None:
    with st.spinner("Loading NIFTY 500 universe automatically..."):
        try:
            st.session_state.universe=get_universe()
        except Exception as e:
            st.error(f"Could not build the NIFTY 500 universe automatically. {e}")
            st.stop()

universe=st.session_state.universe
st.success(f"Eligible universe: {len(universe)} stocks | NIFTY 500 | Market Cap ≥ ₹{MIN_MARKET_CAP_CR:,} Cr")

with st.expander("Show eligible universe"):
    st.dataframe(universe,use_container_width=True,hide_index=True)

if st.button("Run BOP-PRE Scan",type="primary"):
    nifty=download_nifty()
    results=[]; errors=[]
    progress=st.progress(0)
    for i,symbol in enumerate(universe.symbol):
        try:
            h=download_history(symbol)
            if len(h)<100: raise ValueError(f"only {len(h)} daily rows")
            x=prepare(h,nifty)
            if len(x)<2: raise ValueError("insufficient indicator rows")
            r=score(x); r["Symbol"]=symbol
            r["Market Cap (Cr)"]=float(universe.loc[universe.symbol.eq(symbol),"market_cap_crore"].iloc[0])
            results.append(r)
        except Exception as e:
            errors.append({"Symbol":symbol,"Error":str(e)})
        progress.progress((i+1)/len(universe))
    if results:
        out=pd.DataFrame(results).sort_values(["Score","Distance to Resistance %"],ascending=[False,True]).head(TOP_N)
        # Put the stock name/symbol FIRST, followed by the decision fields.
        first_cols=["Symbol","Market Cap (Cr)","Score","Grade","Confidence","Action",
                    "Close","Entry Low","Entry High","Stop Loss","Target 1","Target 2",
                    "RR T1","RR T2","Breakout Confirmed"]
        other_cols=[c for c in out.columns if c not in first_cols]
        out=out[first_cols+other_cols]
        st.subheader("Top 15 Pre-Breakout Candidates")
        st.dataframe(out,use_container_width=True,hide_index=True)

        st.info("**Important:** Confidence is a strategy-strength grade, NOT a guarantee or a probability that the price will rise. The safest execution rule is to wait for breakout confirmation. No indicator can make a trade 'definite'.")

        st.subheader("Scorecard")
        card_cols=["Symbol","Score","Grade","Confidence","Trend %","Momentum %","Volume %",
                   "Breakout Setup %","Relative Strength %","RSI","RVOL","Distance to Resistance %",
                   "Breakout Confirmed","Action"]
        st.dataframe(out[card_cols],use_container_width=True,hide_index=True)

        st.download_button("Download Top 15 CSV",out.to_csv(index=False).encode(),"bop_pre_top15.csv","text/csv")
        if errors:
            with st.expander(f"Skipped stocks ({len(errors)})"):
                st.dataframe(pd.DataFrame(errors),use_container_width=True,hide_index=True)
    else:
        st.error("No stocks were scanned successfully.")
        if errors:
            st.dataframe(pd.DataFrame(errors).head(50),use_container_width=True,hide_index=True)
