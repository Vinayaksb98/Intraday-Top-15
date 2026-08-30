import streamlit as st
import pandas as pd
import numpy as np
import plotly.graph_objects as go
from io import StringIO
import requests
import time

st.set_page_config(page_title="NIFTY 500 Next-Day Intraday Scanner", page_icon="⚡", layout="wide")

st.markdown("""
<style>
.block-container {padding-top:1rem;padding-left:.8rem;padding-right:.8rem}
h1 {font-size:1.55rem!important}
@media(max-width:640px){h1{font-size:1.25rem!important}.stButton button{width:100%}}
</style>
""", unsafe_allow_html=True)

st.title("⚡ NDP-EDGE — NEXT-DAY INTRADAY SCANNER")
st.caption("End-of-day scanner → ranks stocks with the strongest probability setup for a next-session intraday expansion. Research tool, not a guarantee.")

# ---------------- Indicators ----------------
def ema(s, n):
    return s.ewm(span=n, adjust=False).mean()

def rsi(s, n=14):
    d = s.diff(); up = d.clip(lower=0); dn = -d.clip(upper=0)
    au = up.ewm(alpha=1/n, adjust=False).mean()
    ad = dn.ewm(alpha=1/n, adjust=False).mean()
    rs = au / ad.replace(0, np.nan)
    return 100 - 100/(1+rs)

def macd(s):
    m = ema(s, 12) - ema(s, 26); sig = ema(m, 9)
    return m, sig, m-sig

def atr(df, n=14):
    p = df.Close.shift(1)
    tr = pd.concat([df.High-df.Low, (df.High-p).abs(), (df.Low-p).abs()], axis=1).max(axis=1)
    return tr.ewm(alpha=1/n, adjust=False).mean()

def adx(df, n=14):
    up = df.High.diff(); dn = -df.Low.diff()
    plus = np.where((up>dn)&(up>0), up, 0.0)
    minus = np.where((dn>up)&(dn>0), dn, 0.0)
    p = df.Close.shift(1)
    tr = pd.concat([df.High-df.Low, (df.High-p).abs(), (df.Low-p).abs()], axis=1).max(axis=1)
    av = tr.ewm(alpha=1/n, adjust=False).mean()
    pi = 100*pd.Series(plus,index=df.index).ewm(alpha=1/n,adjust=False).mean()/av.replace(0,np.nan)
    mi = 100*pd.Series(minus,index=df.index).ewm(alpha=1/n,adjust=False).mean()/av.replace(0,np.nan)
    dx = 100*(pi-mi).abs()/(pi+mi).replace(0,np.nan)
    return dx.ewm(alpha=1/n,adjust=False).mean()

def safe_num(v, default=np.nan):
    try:
        x = float(v)
        return x if np.isfinite(x) else default
    except Exception:
        return default

# ---------------- Data preparation ----------------
def prepare(df):
    if df is None or df.empty:
        return None
    df = df.copy()
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)
    df.columns = [str(c).strip().title() for c in df.columns]
    if "Date" not in df.columns and isinstance(df.index, pd.DatetimeIndex):
        df = df.reset_index().rename(columns={"index":"Date"})
    need = ["Date","Open","High","Low","Close","Volume"]
    if any(c not in df.columns for c in need):
        return None
    df["Date"] = pd.to_datetime(df.Date, errors="coerce")
    for c in need[1:]: df[c] = pd.to_numeric(df[c], errors="coerce")
    df = df.dropna(subset=need).sort_values("Date").drop_duplicates("Date")
    if len(df) < 220: return None

    df["EMA9"] = ema(df.Close,9); df["EMA20"] = ema(df.Close,20)
    df["EMA50"] = ema(df.Close,50); df["SMA200"] = df.Close.rolling(200).mean()
    df["RSI"] = rsi(df.Close,14)
    df["MACD"],df["MACD_Signal"],df["MACD_Hist"] = macd(df.Close)
    df["ADX"] = adx(df,14); df["ATR"] = atr(df,14)
    df["ATR_PCT"] = df.ATR/df.Close*100
    df["VolMA5"] = df.Volume.rolling(5).mean(); df["VolMA20"] = df.Volume.rolling(20).mean()
    df["RVOL"] = df.Volume/df.VolMA20
    df["AvgValue20Cr"] = (df.Close*df.Volume).rolling(20).mean()/1e7

    # Resistance and base
    df["BOP20"] = df.High.rolling(20).max().shift(1)
    df["DistToBOP"] = (df.BOP20-df.Close)/df.BOP20*100
    df["High30"] = df.High.rolling(30).max().shift(1)
    df["Low30"] = df.Low.rolling(30).min().shift(1)
    df["BaseRange30"] = (df.High30-df.Low30)/df.Low30*100

    # Compression / contraction
    df["BB_MID"] = df.Close.rolling(20).mean(); df["BB_STD"] = df.Close.rolling(20).std()
    df["BB_WIDTH"] = 4*df.BB_STD/df.BB_MID
    df["ATR10"] = df.ATR_PCT.rolling(10).mean()
    df["ATR_PREV"] = df.ATR_PCT.shift(10).rolling(10).mean()
    df["VolBase"] = df.Volume.rolling(10).mean()/df.Volume.shift(10).rolling(10).mean()

    # Slopes / momentum
    df["RSI_Slope"] = df.RSI-df.RSI.shift(3)
    df["MACD_Slope"] = df.MACD_Hist-df.MACD_Hist.shift(3)
    df["ADX_Slope"] = df.ADX-df.ADX.shift(3)
    df["EMA50_Slope"] = df.EMA50-df.EMA50.shift(10)
    df["SMA200_Slope"] = df.SMA200-df.SMA200.shift(20)
    df["ClosePos"] = (df.Close-df.Low)/(df.High-df.Low).replace(0,np.nan)
    return df

# ---------------- Universe ----------------
@st.cache_data(ttl=6*3600, show_spinner=False)
def get_nifty500_symbols():
    # Official Nifty Indices constituent CSV first; alternate URLs retained for resilience.
    urls = [
        "https://www.niftyindices.com/IndexConstituent/ind_nifty500list.csv",
        "https://archives.nseindia.com/content/indices/ind_nifty500list.csv",
    ]
    headers={"User-Agent":"Mozilla/5.0","Accept":"text/csv,*/*"}
    for url in urls:
        try:
            r=requests.get(url,headers=headers,timeout=20)
            if r.ok and len(r.content)>500:
                d=pd.read_csv(StringIO(r.text))
                cols={str(c).strip().upper():c for c in d.columns}
                symcol=cols.get("SYMBOL")
                if symcol:
                    syms=sorted(set(d[symcol].astype(str).str.strip().str.upper()))
                    if len(syms)>=450:
                        return syms
        except Exception:
            pass
    return []

@st.cache_data(ttl=24*3600, show_spinner=False)
def get_market_caps(symbols):
    import yfinance as yf
    out={}
    # Market cap changes slowly; cache prevents repeated metadata calls.
    for i,sym in enumerate(symbols):
        try:
            t=yf.Ticker(sym+".NS")
            cap=np.nan
            try:
                cap=safe_num(t.fast_info.get("market_cap"))
            except Exception:
                pass
            if not np.isfinite(cap):
                try:
                    cap=safe_num(t.get_info().get("marketCap"))
                except Exception:
                    pass
            out[sym]=cap/1e7 if np.isfinite(cap) else np.nan  # INR Crore
        except Exception:
            out[sym]=np.nan
    return out

@st.cache_data(ttl=3600, show_spinner=False)
def download_batch(symbols, period="1y"):
    import yfinance as yf
    try:
        tickers=[s+".NS" for s in symbols]
        return yf.download(tickers, period=period, interval="1d", auto_adjust=False,
                           progress=False, threads=True, group_by="ticker")
    except Exception:
        return None

def extract_symbol(raw, sym):
    if raw is None or raw.empty: return None
    t=sym+".NS"
    try:
        if isinstance(raw.columns,pd.MultiIndex):
            if t in raw.columns.get_level_values(0): d=raw[t].copy()
            elif t in raw.columns.get_level_values(-1): d=raw.xs(t,axis=1,level=-1).copy()
            else: return None
        else: d=raw.copy()
        return d.reset_index()
    except Exception:
        return None

# ---------------- Index relative strength ----------------
@st.cache_data(ttl=3600, show_spinner=False)
def get_index_history():
    import yfinance as yf
    try:
        d=yf.download("^CRSLDX", period="1y", interval="1d", auto_adjust=False, progress=False)
        if d is None or d.empty:
            d=yf.download("^NSEI", period="1y", interval="1d", auto_adjust=False, progress=False)
        if isinstance(d.columns,pd.MultiIndex): d.columns=d.columns.get_level_values(0)
        d=d.reset_index()
        return prepare(d)
    except Exception:
        return None

def relative_strength_points(d, idx):
    if idx is None or len(idx)<130 or len(d)<130: return 0, np.nan, np.nan, np.nan
    pts=0; vals=[]
    for n,p in [(20,5),(60,5),(120,5)]:
        sr=d.Close.iloc[-1]/d.Close.iloc[-n-1]-1
        ir=idx.Close.iloc[-1]/idx.Close.iloc[-n-1]-1
        vals.append((sr-ir)*100)
        if sr>ir: pts+=p
    return pts,*vals

# ---------------- Intraday setup ----------------
def resistance_strength(d):
    h=d.High.iloc[-61:-1]
    if len(h)<20: return 0
    level=h.max(); tol=0.012
    touches=((h-level).abs()/level<=tol).sum()
    return int(min(5, touches))

def intraday_levels(d):
    x=d.iloc[-1]; close=float(x.Close); atrv=float(x.ATR)
    # Next-day trigger requires actual confirmation, not just an overnight prediction.
    trigger=max(float(x.High), float(x.BOP20))
    entry=trigger*(1+0.0005)  # small confirmation buffer
    stop=max(float(x.Low), entry-0.8*atrv)
    if stop>=entry: stop=entry-0.8*atrv
    risk=entry-stop
    target1=entry+1.2*atrv
    target2=entry+2.0*atrv
    return entry,stop,target1,target2,risk

def score_next_day(d, idx):
    x=d.iloc[-1]
    checks=[]
    def add(name, ok, pts): checks.append((name,bool(ok),pts))

    # Trend quality (20)
    add("Close > SMA200", pd.notna(x.SMA200) and x.Close>x.SMA200,4)
    add("EMA20 > EMA50", x.EMA20>x.EMA50,4)
    add("EMA50 rising", pd.notna(x.EMA50_Slope) and x.EMA50_Slope>0,4)
    add("SMA200 rising", pd.notna(x.SMA200_Slope) and x.SMA200_Slope>=0,3)
    add("Close in upper half of daily range", pd.notna(x.ClosePos) and x.ClosePos>=0.55,5)

    # Base/compression (20)
    bbcut=d.BB_WIDTH.rolling(40).quantile(0.40).iloc[-1]
    add("30D base range <= 18%", pd.notna(x.BaseRange30) and x.BaseRange30<=18,5)
    add("ATR contracting", pd.notna(x.ATR10) and pd.notna(x.ATR_PREV) and x.ATR10<=x.ATR_PREV*0.95,5)
    add("Bollinger compression", pd.notna(x.BB_WIDTH) and pd.notna(bbcut) and x.BB_WIDTH<=bbcut,5)
    add("Volume contracted during base", pd.notna(x.VolBase) and x.VolBase<=0.95,5)

    # Momentum (15)
    add("RSI 52-68", 52<=x.RSI<=68,5)
    add("RSI rising", pd.notna(x.RSI_Slope) and x.RSI_Slope>0,3)
    add("MACD histogram improving", pd.notna(x.MACD_Slope) and x.MACD_Slope>0,4)
    add("ADX healthy/rising", pd.notna(x.ADX) and x.ADX>=18 and pd.notna(x.ADX_Slope) and x.ADX_Slope>=0,3)

    # Volume/participation (15), progressive
    rvol=safe_num(x.RVOL,0)
    volpts=0 if rvol<0.7 else 2 if rvol<1.0 else 3 if rvol<1.2 else 4 if rvol<1.6 else 5
    checks.append((f"Progressive RVOL ({rvol:.2f}x)",volpts>0,volpts))
    add("20D traded value >= ₹10 Cr", pd.notna(x.AvgValue20Cr) and x.AvgValue20Cr>=10,5)
    add("Today's volume >= 20D average", rvol>=1.0,5)

    # Relative strength (15)
    rspts,rs20,rs60,rs120=relative_strength_points(d,idx)
    checks.append(("Outperforms index: 20/60/120D",rspts>0,rspts))

    # Breakout proximity / structure (15)
    dist=safe_num(x.DistToBOP,999)
    add("0-2.5% below 20D resistance",0<=dist<=2.5,5)
    add("Resistance tested",resistance_strength(d)>=2,3)
    entry,stop,t1,t2,risk=intraday_levels(d)
    rr=(t2-entry)/risk if risk>0 else 0
    add("Intraday R:R >= 2",rr>=2,4)
    add("No excessive extension today",(x.Close-x.EMA20)/x.EMA20*100<=5,3)

    total=sum(p for _,ok,p in checks if ok)

    # Signal is intentionally probabilistic; next-day move must still trigger.
    if total>=80 and 0<=dist<=2.5 and rr>=2: signal="🟢 NEXT-DAY STRONG"
    elif total>=68 and 0<=dist<=3.0: signal="🟢 NEXT-DAY CANDIDATE"
    elif total>=58: signal="🟡 WATCH"
    else: signal="⚪ AVOID"

    return total,signal,checks,entry,stop,t1,t2,rr,(rs20,rs60,rs120)

# ---------------- UI ----------------
with st.sidebar:
    st.header("Scanner Settings")
    min_cap=st.number_input("Minimum market cap (₹ Cr)", value=10000, min_value=1000, step=1000)
    min_score=st.slider("Minimum score",0,100,68,step=1)
    batch_size=st.slider("Batch size",20,100,50,step=10)
    st.divider()
    st.write("Universe: **NIFTY 500 only**")
    st.write("Filter: **Market Cap ≥ ₹10,000 Cr**")
    st.write("Signal: calculated after market close for next trading day")
    st.warning("A signal identifies a higher-probability setup. It cannot guarantee which share will move tomorrow.")

if "scan_results" not in st.session_state: st.session_state.scan_results=None
if "scan_details" not in st.session_state: st.session_state.scan_details={}
if "scan_universe" not in st.session_state: st.session_state.scan_universe=[]

if st.button("🔄 Build Tomorrow's Intraday Watchlist"):
    symbols=get_nifty500_symbols()
    if not symbols:
        st.error("Could not retrieve the current NIFTY 500 constituent list. Please try again later.")
    else:
        with st.spinner("Checking NIFTY 500 market caps (cached for 24 hours)..."):
            caps=get_market_caps(symbols)
        eligible=[s for s in symbols if safe_num(caps.get(s),0)>=min_cap]
        st.session_state.scan_universe=eligible
        if not eligible:
            st.error("No stocks passed the market-cap filter.")
        else:
            idx=get_index_history()
            progress=st.progress(0,text=f"Scanning {len(eligible)} eligible NIFTY 500 stocks...")
            results=[]; details={}
            batches=(len(eligible)+batch_size-1)//batch_size
            for bi in range(batches):
                batch=eligible[bi*batch_size:(bi+1)*batch_size]
                raw=download_batch(batch)
                for sym in batch:
                    try:
                        d=prepare(extract_symbol(raw,sym))
                        if d is None: continue
                        x=d.iloc[-1]
                        if pd.isna(x.BOP20) or pd.isna(x.RVOL): continue
                        total,signal,checks,entry,stop,t1,t2,rr,rs=score_next_day(d,idx)
                        if total<min_score or signal=="⚪ AVOID": continue
                        rec={
                            "Stock":sym,"Date":x.Date.date(),"Market Cap Cr":safe_num(caps.get(sym)),
                            "Close":float(x.Close),"Tomorrow Trigger":entry,"Stop":stop,
                            "Target 1":t1,"Target 2":t2,"R:R":rr,
                            "Score":total,"Signal":signal,"Distance %":safe_num(x.DistToBOP),
                            "RSI":safe_num(x.RSI),"ADX":safe_num(x.ADX),"RVOL":safe_num(x.RVOL),
                            "Avg Value Cr":safe_num(x.AvgValue20Cr),"RS vs Index 20D %":rs[0],
                            "RS vs Index 60D %":rs[1],"RS vs Index 120D %":rs[2]
                        }
                        results.append(rec); details[sym]=(d,checks,rec)
                    except Exception:
                        continue
                progress.progress((bi+1)/batches,text=f"Scanned {min((bi+1)*batch_size,len(eligible))}/{len(eligible)}")
            progress.empty()
            if results:
                rank={"🟢 NEXT-DAY STRONG":2,"🟢 NEXT-DAY CANDIDATE":1,"🟡 WATCH":0}
                r=pd.DataFrame(results); r["_rank"]=r.Signal.map(rank).fillna(-1)
                r=r.sort_values(["_rank","Score","R:R","RVOL"],ascending=False).drop(columns="_rank").head(15)
                st.session_state.scan_results=r
                st.session_state.scan_details=details
            else:
                st.session_state.scan_results=pd.DataFrame(); st.session_state.scan_details={}

r=st.session_state.scan_results
if r is not None:
    if r.empty:
        st.warning("No candidates met the selected filters today.")
    else:
        st.subheader("⚡ Tomorrow's Top Intraday Candidates")
        st.info("How to use tomorrow: do NOT buy automatically at market open. Take a trade only after price trades above the displayed Trigger with intraday volume confirmation.")
        view=r.copy(); view.insert(0,"Rank",range(1,len(view)+1))
        main=view[["Rank","Stock","Market Cap Cr","Close","Tomorrow Trigger","Stop","Target 1","Target 2","R:R","Score","Signal"]]
        st.dataframe(main.style.format({
            "Market Cap Cr":"₹{:,.0f} Cr","Close":"₹{:,.2f}","Tomorrow Trigger":"₹{:,.2f}",
            "Stop":"₹{:,.2f}","Target 1":"₹{:,.2f}","Target 2":"₹{:,.2f}","R:R":"{:.2f}"
        }),use_container_width=True,hide_index=True)
        st.caption(f"Universe scanned: {len(st.session_state.scan_universe)} NIFTY 500 stocks after Market Cap ≥ ₹{min_cap:,.0f} Cr filter.")

        with st.expander("📊 Full scoring details",expanded=False):
            st.dataframe(view,use_container_width=True,hide_index=True)

        sym=st.selectbox("Select stock for setup chart",view.Stock.tolist())
        d,checks,rec=st.session_state.scan_details[sym]
        c=st.columns(6)
        c[0].metric("Close",f"₹{rec['Close']:,.2f}")
        c[1].metric("Tomorrow Trigger",f"₹{rec['Tomorrow Trigger']:,.2f}")
        c[2].metric("Stop",f"₹{rec['Stop']:,.2f}")
        c[3].metric("Target 1",f"₹{rec['Target 1']:,.2f}")
        c[4].metric("Target 2",f"₹{rec['Target 2']:,.2f}")
        c[5].metric("Score",f"{rec['Score']}/100")

        fig=go.Figure()
        dd=d.tail(120)
        fig.add_trace(go.Candlestick(x=dd.Date,open=dd.Open,high=dd.High,low=dd.Low,close=dd.Close,name="Price"))
        for col in ["EMA20","EMA50","SMA200","BOP20"]:
            fig.add_trace(go.Scatter(x=dd.Date,y=dd[col],name=col))
        for y,name in [(rec["Tomorrow Trigger"],"Tomorrow Trigger"),(rec["Stop"],"Stop"),(rec["Target 1"],"Target 1"),(rec["Target 2"],"Target 2")]:
            fig.add_hline(y=y,line_dash="dash",annotation_text=name)
        fig.update_layout(height=620,xaxis_rangeslider_visible=False)
        st.plotly_chart(fig,use_container_width=True)

        st.write("### Score breakdown")
        st.dataframe(pd.DataFrame([{"Condition":n,"Result":"✓" if ok else "✗","Points":p if ok else 0} for n,ok,p in checks]),use_container_width=True,hide_index=True)

        st.write("### Tomorrow's execution rule")
        st.markdown("""
1. Wait at least for the opening volatility to settle.
2. Trade **only if price breaks the Tomorrow Trigger** and volume confirms.
3. If price gaps too far above the trigger, do not chase; wait for a controlled pullback/retest.
4. Use the displayed Stop as the risk reference.
5. Book/manage partial profit near Target 1 and reassess for Target 2.
6. If the trigger is never crossed, **no trade**.
""")
else:
    st.info("After market close, click **Build Tomorrow's Intraday Watchlist**.")

st.divider()
st.warning("Research and screening tool only. The model ranks probability based on historical end-of-day technical conditions; it cannot know with certainty which stock will move tomorrow. Intraday gaps, news and market conditions can invalidate any setup.")
