import streamlit as st
import pandas as pd
import numpy as np
import plotly.graph_objects as go
from pathlib import Path

st.set_page_config(page_title="BOP Top 15 Scanner", page_icon="📈", layout="wide")

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
    df.columns=[str(c).strip().title() for c in df.columns]
    if "Date" not in df.columns and isinstance(df.index,pd.DatetimeIndex):
        df=df.reset_index().rename(columns={"index":"Date"})
    need=["Date","Open","High","Low","Close","Volume"]
    miss=[c for c in need if c not in df.columns]
    if miss: raise ValueError("Missing columns: "+", ".join(miss))
    df["Date"]=pd.to_datetime(df.Date,errors="coerce")
    for c in need[1:]: df[c]=pd.to_numeric(df[c],errors="coerce")
    df=df.dropna(subset=need).sort_values("Date")
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
        ("Breakout above BOP",pd.notna(x.BOP) and x.Close>x.BOP,2),
        ("RVOL >= 1.5x",pd.notna(x.RVOL) and x.RVOL>=1.5,2),
        ("RSI 55-70",pd.notna(x.RSI) and 55<=x.RSI<=70,1),
        ("MACD bullish",pd.notna(x.MACD) and x.MACD>x.MACD_Signal,1),
        ("ADX > 25",pd.notna(x.ADX) and x.ADX>25,1),
        ("10%+ context",pd.notna(x.BOP) and (x.Close>x.BOP or x.BOP>=x.Close*1.10),1)
    ]
    total=sum(p for _,ok,p in checks if ok)
    signal="STRONG BOP" if total>=9 else "GOOD BOP" if total>=7 else "WATCH" if total>=5 else "AVOID"
    return total,signal,checks

def analyze(sym,raw):
    d=prepare(raw)
    if len(d)<210: return None
    total,signal,checks=score(d)
    x=d.iloc[-1]
    return dict(Stock=sym,Date=x.Date.date(),Price=x.Close,BOP=x.BOP,Score=total,
                RSI=x.RSI,ADX=x.ADX,RVOL=x.RVOL,EMA20=x.EMA20,EMA50=x.EMA50,
                SMA200=x.SMA200,ATR=x.ATR,Signal=signal,_df=d,_checks=checks)


st.markdown("""
<style>
.block-container {padding-top: 1rem; padding-left: .8rem; padding-right: .8rem;}
h1 {font-size: 1.65rem !important;}
[data-testid="stMetricValue"] {font-size: 1.15rem;}
div[data-testid="stDataFrame"] {font-size: .78rem;}
@media (max-width: 640px) {
  h1 {font-size: 1.35rem !important;}
  h2 {font-size: 1.15rem !important;}
  h3 {font-size: 1.0rem !important;}
  .stButton button {width:100%;}
}
</style>
""", unsafe_allow_html=True)

st.title("📈 BOP TOP 15")
st.caption("📱 Mobile Web Version • Free daily-data research mode")
if st.button("🔄 Refresh / Reload Data"):
    st.rerun()

with st.sidebar:
    st.header("BOP Settings")
    minimum=st.slider("Minimum score",0,11,7)
    st.write("EMA: 20 / 50")
    st.write("SMA: 200")
    st.write("RSI: 14 (55–70)")
    st.write("MACD: 12 / 26 / 9")
    st.write("ADX: 14 (>25)")
    st.write("Volume MA: 20")
    st.write("RVOL: ≥1.5×")
    st.write("ATR: 14")
    st.write("BOP: previous 20-day high")

tabs=st.tabs(["🔎 Top 15 Scanner","📊 Chart"])

with tabs[0]:
    mode=st.radio("Data source",["Upload CSV","Free Yahoo Finance daily data"],horizontal=True)
    datasets={}
    if mode=="Upload CSV":
        files=st.file_uploader("Upload OHLCV CSV files",type="csv",accept_multiple_files=True)
        if files:
            for f in files:
                raw=pd.read_csv(f)
                cols={c.upper():c for c in raw.columns}
                if "SYMBOL" in cols:
                    for sym,g in raw.groupby(cols["SYMBOL"]):
                        datasets[str(sym).upper()]=g.drop(columns=[cols["SYMBOL"]])
                else:
                    datasets[Path(f.name).stem.upper()]=raw
    else:
        symbols=st.text_area("NSE symbols (comma separated)",
                             "PARAS,VOLTAMP,CPPLUS,WELCORP,EXICOM,GVT&D,GNG")
        if st.button("Download free daily data"):
            try:
                import yfinance as yf
                for sym in symbols.split(","):
                    sym=sym.strip().upper()
                    if not sym: continue
                    d=yf.download(sym+".NS",period="2y",interval="1d",
                                  auto_adjust=False,progress=False,threads=False)
                    if not d.empty:
                        if isinstance(d.columns,pd.MultiIndex): d.columns=d.columns.get_level_values(0)
                        datasets[sym]=d.reset_index()
                st.session_state["datasets"]=datasets
            except Exception as e: st.error(str(e))
        datasets=st.session_state.get("datasets",datasets)

    if datasets:
        results=[]; details={}
        for sym,raw in datasets.items():
            try:
                a=analyze(sym,raw)
                if a: details[sym]=a; results.append({k:v for k,v in a.items() if not k.startswith("_")})
            except Exception: pass
        if results:
            r=pd.DataFrame(results)
            r=r[r.Score>=minimum].sort_values(["Score","RVOL"],ascending=False).head(15).reset_index(drop=True)
            r.insert(0,"Rank",range(1,len(r)+1))
            st.subheader("🏆 Top 15 BOP Stocks")
            st.dataframe(r.style.format({"Price":"₹{:,.2f}","BOP":"₹{:,.2f}",
                                         "RSI":"{:.1f}","ADX":"{:.1f}","RVOL":"{:.2f}x"}),
                         use_container_width=True,hide_index=True)
            if len(r):
                selected=st.selectbox("Select stock",r.Stock.tolist())
                a=details[selected]
                c=st.columns(5)
                c[0].metric("Price",f"₹{a['Price']:,.2f}")
                c[1].metric("BOP",f"₹{a['BOP']:,.2f}" if pd.notna(a["BOP"]) else "—")
                c[2].metric("Score",f"{a['Score']}/11")
                c[3].metric("RSI",f"{a['RSI']:.1f}")
                c[4].metric("RVOL",f"{a['RVOL']:.2f}x")
                st.write("### Why this BOP score?")
                st.dataframe(pd.DataFrame(
                    [{"Condition":n,"Result":"✓" if ok else "✗","Points":p if ok else 0}
                     for n,ok,p in a["_checks"]]),use_container_width=True,hide_index=True)
        else: st.warning("No stocks meet the current minimum score.")
    else:
        st.info("Upload historical OHLCV data or use the free Yahoo Finance option.")

with tabs[1]:
    ds=st.session_state.get("datasets",{})
    if ds:
        sym=st.selectbox("Stock",sorted(ds))
        d=prepare(ds[sym])
        fig=go.Figure()
        fig.add_trace(go.Candlestick(x=d.Date,open=d.Open,high=d.High,low=d.Low,close=d.Close,name="Price"))
        for col in ["EMA20","EMA50","SMA200","BOP"]:
            fig.add_trace(go.Scatter(x=d.Date,y=d[col],name=col))
        fig.update_layout(height=650,xaxis_rangeslider_visible=False)
        st.plotly_chart(fig,use_container_width=True)
    else: st.info("Load data in the Scanner tab first.")

st.divider()
st.warning("Research tool only. BOP is a custom heuristic, not an official indicator or a guarantee of returns.")
