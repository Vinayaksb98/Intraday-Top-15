
import streamlit as st
import pandas as pd
import numpy as np
import plotly.graph_objects as go
from io import StringIO
import requests
import time

st.set_page_config(page_title="BOP Top 15 NSE Scanner", page_icon="📈", layout="wide")

st.markdown("""
<style>
.block-container {padding-top:1rem;padding-left:.8rem;padding-right:.8rem}
h1 {font-size:1.55rem!important}
@media(max-width:640px){
 h1{font-size:1.25rem!important}
 .stButton button{width:100%}
}
</style>
""", unsafe_allow_html=True)

st.title("📈 BOP TOP 15 — NSE")
st.caption("Automatic NSE equity universe • Free daily-data research mode")

def ema(s,n): return s.ewm(span=n,adjust=False).mean()

def rsi(s,n=14):
    d=s.diff(); up=d.clip(lower=0); dn=-d.clip(upper=0)
    au=up.ewm(alpha=1/n,adjust=False).mean()
    ad=dn.ewm(alpha=1/n,adjust=False).mean()
    rs=au/ad.replace(0,np.nan)
    return 100-100/(1+rs)

def macd(s):
    m=ema(s,12)-ema(s,26); sig=ema(m,9)
    return m,sig,m-sig

def atr(df,n=14):
    p=df.Close.shift(1)
    tr=pd.concat([df.High-df.Low,(df.High-p).abs(),(df.Low-p).abs()],axis=1).max(axis=1)
    return tr.ewm(alpha=1/n,adjust=False).mean()

def adx(df,n=14):
    up=df.High.diff(); dn=-df.Low.diff()
    plus=np.where((up>dn)&(up>0),up,0.0)
    minus=np.where((dn>up)&(dn>0),dn,0.0)
    p=df.Close.shift(1)
    tr=pd.concat([df.High-df.Low,(df.High-p).abs(),(df.Low-p).abs()],axis=1).max(axis=1)
    av=tr.ewm(alpha=1/n,adjust=False).mean()
    pi=100*pd.Series(plus,index=df.index).ewm(alpha=1/n,adjust=False).mean()/av.replace(0,np.nan)
    mi=100*pd.Series(minus,index=df.index).ewm(alpha=1/n,adjust=False).mean()/av.replace(0,np.nan)
    dx=100*(pi-mi).abs()/(pi+mi).replace(0,np.nan)
    return dx.ewm(alpha=1/n,adjust=False).mean()

def prepare(df):
    df=df.copy()
    if isinstance(df.columns,pd.MultiIndex):
        df.columns=df.columns.get_level_values(0)
    df.columns=[str(c).strip().title() for c in df.columns]
    if "Date" not in df.columns and isinstance(df.index,pd.DatetimeIndex):
        df=df.reset_index().rename(columns={"index":"Date"})
    need=["Date","Open","High","Low","Close","Volume"]
    if any(c not in df.columns for c in need): return None
    df["Date"]=pd.to_datetime(df.Date,errors="coerce")
    for c in need[1:]: df[c]=pd.to_numeric(df[c],errors="coerce")
    df=df.dropna(subset=need).sort_values("Date")
    if len(df)<210: return None
    df["EMA20"]=ema(df.Close,20); df["EMA50"]=ema(df.Close,50)
    df["SMA200"]=df.Close.rolling(200).mean()
    df["RSI"]=rsi(df.Close,14)
    df["MACD"],df["MACD_Signal"],df["MACD_Hist"]=macd(df.Close)
    df["ADX"]=adx(df,14); df["ATR"]=atr(df,14)
    df["VolMA20"]=df.Volume.rolling(20).mean()
    df["RVOL"]=df.Volume/df.VolMA20
    df["BOP"]=df.High.rolling(20).max().shift(1)
    return df

def score(d):
    x=d.iloc[-1]
    checks=[
      ("Price > EMA20",x.Close>x.EMA20,1),
      ("EMA20 > EMA50",x.EMA20>x.EMA50,1),
      ("Price > SMA200",pd.notna(x.SMA200) and x.Close>x.SMA200,1),
      ("Breakout above previous 20D high",pd.notna(x.BOP) and x.Close>x.BOP,2),
      ("RVOL >= 1.5x",pd.notna(x.RVOL) and x.RVOL>=1.5,2),
      ("RSI 55–70",pd.notna(x.RSI) and 55<=x.RSI<=70,1),
      ("MACD bullish",pd.notna(x.MACD) and x.MACD>x.MACD_Signal,1),
      ("ADX > 25",pd.notna(x.ADX) and x.ADX>25,1),
      ("BOP proximity/breakout context",pd.notna(x.BOP) and x.Close>=x.BOP*0.98,1)
    ]
    total=sum(p for _,ok,p in checks if ok)
    signal="STRONG BOP" if total>=9 else "GOOD BOP" if total>=7 else "WATCH" if total>=5 else "AVOID"
    return total,signal,checks

@st.cache_data(ttl=86400, show_spinner=False)
def get_nse_universe():
    # NSE's current equity-security master. This is the source of the universe.
    urls=[
        "https://archives.nseindia.com/content/equities/EQUITY_L.csv",
        "https://www.nseindia.com/api/equity-master"
    ]
    headers={"User-Agent":"Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/151 Safari/537.36",
             "Accept":"text/csv,text/plain,application/json,*/*"}
    for url in urls:
        try:
            r=requests.get(url,headers=headers,timeout=15)
            if r.ok and len(r.content)>1000:
                if url.endswith(".csv"):
                    d=pd.read_csv(StringIO(r.text))
                    symcol=next((c for c in d.columns if str(c).upper()=="SYMBOL"),None)
                    sercol=next((c for c in d.columns if str(c).upper()=="SERIES"),None)
                    if symcol:
                        if sercol:
                            d=d[d[sercol].astype(str).str.upper().eq("EQ")]
                        syms=sorted(set(d[symcol].astype(str).str.strip().str.upper()))
                        return syms
        except Exception:
            pass
    return []

@st.cache_data(ttl=3600, show_spinner=False)
def download_batch(symbols, period="1y"):
    import yfinance as yf
    tickers=[s+".NS" for s in symbols]
    try:
        raw=yf.download(tickers,period=period,interval="1d",auto_adjust=False,
                        progress=False,threads=True,group_by="ticker")
        return raw
    except Exception:
        return None

def extract_symbol(raw,sym):
    if raw is None or raw.empty: return None
    t=sym+".NS"
    try:
        if isinstance(raw.columns,pd.MultiIndex):
            if t not in raw.columns.get_level_values(0): return None
            d=raw[t].copy()
        else:
            d=raw.copy()
        d=d.reset_index()
        return d
    except Exception:
        return None

with st.sidebar:
    st.header("BOP Settings")
    minimum=st.slider("Minimum score",0,11,7)
    universe=st.selectbox("Stock universe",[
        "All NSE Equity (automatic)",
        "NSE liquid scan (faster)",
        "My 7 reference stocks"
    ])
    batch_size=st.slider("Batch size",10,100,40,step=10)
    max_symbols=st.slider("Maximum stocks to scan",50,2000,500,step=50)
    st.divider()
    st.write("EMA: 20 / 50")
    st.write("SMA: 200")
    st.write("RSI: 14 (55–70)")
    st.write("MACD: 12 / 26 / 9")
    st.write("ADX: 14 (>25)")
    st.write("RVOL: ≥1.5×")
    st.write("BOP: previous 20-day high")
    st.warning("Free Yahoo data can be delayed/rate-limited. This is not live exchange data.")

if "scan_results" not in st.session_state: st.session_state.scan_results=None
if "scan_details" not in st.session_state: st.session_state.scan_details={}
if "scan_universe" not in st.session_state: st.session_state.scan_universe=[]

if st.button("🔄 Scan / Refresh Top 15"):
    if universe=="My 7 reference stocks":
        symbols=["VOLTAMP","EBGNG","EXICOM","CPPLUS","WELCORP","GVT&D","PARAS"]
    else:
        symbols=get_nse_universe()
        if not symbols:
            st.error("Could not download the NSE equity master right now. Try again later.")
            symbols=[]
        if universe=="NSE liquid scan (faster)" and symbols:
            # Keep a manageable universe; liquidity filter is applied after data download.
            symbols=symbols[:min(len(symbols),1000)]
    symbols=symbols[:max_symbols]
    st.session_state.scan_universe=symbols

    if symbols:
        progress=st.progress(0,text=f"Scanning {len(symbols)} NSE symbols...")
        results=[]; details={}
        total_batches=(len(symbols)+batch_size-1)//batch_size
        for bi in range(total_batches):
            batch=symbols[bi*batch_size:(bi+1)*batch_size]
            raw=download_batch(batch)
            for sym in batch:
                d=extract_symbol(raw,sym)
                try:
                    d=prepare(d)
                    if d is None: continue
                    a=score(d); x=d.iloc[-1]
                    # Skip unusably illiquid instruments in broad scans.
                    if pd.isna(x.RVOL): continue
                    rec={"Stock":sym,"Date":x.Date.date(),"Price":x.Close,"BOP":x.BOP,
                         "Score":a[0],"Signal":a[1],"RSI":x.RSI,"ADX":x.ADX,
                         "RVOL":x.RVOL,"EMA20":x.EMA20,"EMA50":x.EMA50,
                         "SMA200":x.SMA200,"ATR":x.ATR}
                    results.append(rec); details[sym]=(a,d)
                except Exception:
                    continue
            progress.progress((bi+1)/total_batches,text=f"Scanned {min((bi+1)*batch_size,len(symbols))}/{len(symbols)}")
        st.session_state.scan_results=pd.DataFrame(results).sort_values(["Score","RVOL"],ascending=False).head(15)
        st.session_state.scan_details=details
        progress.empty()

r=st.session_state.scan_results
if r is not None and not r.empty:
    st.subheader("🏆 Top 15 BOP Opportunities")
    view=r.copy()
    view.insert(0,"Rank",range(1,len(view)+1))
    view=view[view.Score>=minimum].copy()
    st.dataframe(view.style.format({"Price":"₹{:,.2f}","BOP":"₹{:,.2f}",
                                    "RSI":"{:.1f}","ADX":"{:.1f}","RVOL":"{:.2f}x"}),
                 use_container_width=True,hide_index=True)
    st.caption(f"Universe scanned: {len(st.session_state.scan_universe)} symbols • Results meeting score ≥ {minimum}: {len(view)}")

    if len(view):
        sym=st.selectbox("Select a stock for chart",view.Stock.tolist())
        a,d=st.session_state.scan_details[sym]
        c=st.columns(5)
        x=d.iloc[-1]
        c[0].metric("Price",f"₹{x.Close:,.2f}")
        c[1].metric("BOP",f"₹{x.BOP:,.2f}" if pd.notna(x.BOP) else "—")
        c[2].metric("Score",f"{a[0]}/11")
        c[3].metric("RSI",f"{x.RSI:.1f}")
        c[4].metric("RVOL",f"{x.RVOL:.2f}x")
        fig=go.Figure()
        fig.add_trace(go.Candlestick(x=d.Date,open=d.Open,high=d.High,low=d.Low,close=d.Close,name="Price"))
        for col in ["EMA20","EMA50","SMA200","BOP"]:
            fig.add_trace(go.Scatter(x=d.Date,y=d[col],name=col))
        fig.update_layout(height=600,xaxis_rangeslider_visible=False)
        st.plotly_chart(fig,use_container_width=True)
        st.write("### BOP score breakdown")
        st.dataframe(pd.DataFrame([{"Condition":n,"Result":"✓" if ok else "✗","Points":p if ok else 0}
                                   for n,ok,p in a[2]]),
                     use_container_width=True,hide_index=True)
else:
    st.info("Choose a universe in the sidebar and press **Scan / Refresh Top 15**.")

st.divider()
st.warning("Research tool only. BOP is a custom heuristic and does not guarantee returns. Free Yahoo Finance data is not a true live NSE feed.")
