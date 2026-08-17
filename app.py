import streamlit as st
import pandas as pd
import numpy as np
import plotly.graph_objects as go
from io import StringIO
import requests
import time

st.set_page_config(page_title="Pre-BOP Top 15 NSE Scanner", page_icon="🚀", layout="wide")

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

st.title("🚀 PRE-BOP TOP 15 — NSE")
st.caption("Early-entry research scanner • seeks stocks near resistance before breakout • free daily data")

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
    for c in need[1:]:
        df[c]=pd.to_numeric(df[c],errors="coerce")
    df=df.dropna(subset=need).sort_values("Date").drop_duplicates("Date")
    if len(df)<210: return None

    # Technical indicators. All are calculated from the same Close/High/Low/Volume series.
    df["EMA9"]=ema(df.Close,9)
    df["EMA20"]=ema(df.Close,20)
    df["EMA21"]=ema(df.Close,21)
    df["EMA50"]=ema(df.Close,50)
    df["SMA200"]=df.Close.rolling(200,min_periods=200).mean()
    df["RSI"]=rsi(df.Close,14)
    df["MACD"],df["MACD_Signal"],df["MACD_Hist"]=macd(df.Close)
    df["ADX"]=adx(df,14)
    df["ATR"]=atr(df,14)
    df["VolMA20"]=df.Volume.rolling(20,min_periods=20).mean()
    df["RVOL"]=df.Volume/df.VolMA20

    # Breakout reference is the highest high of the previous 20 sessions.
    df["BOP"]=df.High.rolling(20,min_periods=20).max().shift(1)
    df["DistanceToBO"]=(df["BOP"]-df["Close"])/df["BOP"]*100

    # Bollinger compression.
    df["BB_MID"]=df.Close.rolling(20,min_periods=20).mean()
    df["BB_STD"]=df.Close.rolling(20,min_periods=20).std()
    df["BB_WIDTH"]=(4*df["BB_STD"])/df["BB_MID"]

    # Momentum direction.
    df["RSI_Slope"]=df.RSI-df.RSI.shift(3)
    df["MACD_Hist_Slope"]=df.MACD_Hist-df.MACD_Hist.shift(3)
    df["ADX_Slope"]=df.ADX-df.ADX.shift(3)

    # Volume direction: recent volume versus the prior 5-session average.
    df["VolMA5"]=df.Volume.rolling(5,min_periods=5).mean()
    df["VolTrend"]=df["VolMA5"]/df["VolMA20"]

    return df

def find_resistances(d):
    """Find nearby resistance levels above the latest price."""
    x=d.iloc[-1]
    close=float(x.Close)
    levels=[]

    # Structural levels: previous 20D and 50D highs, excluding today.
    if len(d)>=21:
        levels.append(("20D high", float(d.High.iloc[-21:-1].max()), 3))
    if len(d)>=51:
        levels.append(("50D high", float(d.High.iloc[-51:-1].max()), 2))

    # Local swing highs from the recent history.
    h=d.High.iloc[:-2].tail(80)
    if len(h)>=7:
        roll=h.rolling(7,center=True).max()
        peaks=h[(h>=roll) & roll.notna()]
        for level in peaks.dropna().tolist():
            levels.append(("Swing resistance",float(level),2))

    # Cluster nearby levels; stronger levels get more touches.
    raw=[(name,level,weight) for name,level,weight in levels
         if np.isfinite(level) and level>close*1.005]
    if not raw:
        return []

    raw.sort(key=lambda z:z[1])
    clusters=[]
    for item in raw:
        if not clusters or abs(item[1]-clusters[-1]["level"])/clusters[-1]["level"]>0.008:
            clusters.append({"level":item[1],"strength":item[2],"sources":[item[0]]})
        else:
            c=clusters[-1]
            c["level"]=(c["level"]+item[1])/2
            c["strength"]+=item[2]
            c["sources"].append(item[0])
    return sorted(clusters,key=lambda c:c["level"])

def calculate_target(d):
    """Resistance-first target with ATR sanity check and volume/momentum context."""
    x=d.iloc[-1]
    close=float(x.Close)
    atrv=float(x.ATR) if pd.notna(x.ATR) else close*0.02
    resistances=find_resistances(d)

    # Candidate target must offer at least ~1 ATR of room; otherwise use the next level.
    min_move=max(atrv*0.75, close*0.01)
    candidates=[r for r in resistances if r["level"]>=close+min_move]

    if candidates:
        r=candidates[0]
        target=float(r["level"])
        reason=f'{r["sources"][0]} resistance'
        strength=r["strength"]
    else:
        # No clean resistance found: use a conservative ATR fallback.
        target=close+1.25*atrv
        reason="ATR fallback — no clean resistance above price"
        strength=0

    # If volume is already weakening and RSI is high, prefer the nearest resistance
    # instead of extending the target.
    volume_weak=(pd.notna(x.RVOL) and x.RVOL<1.0) or (pd.notna(x.VolTrend) and x.VolTrend<0.85)
    momentum_hot=pd.notna(x.RSI) and x.RSI>=68
    if resistances and (volume_weak or momentum_hot):
        nearer=resistances[0]
        if nearer["level"]>close:
            target=min(target,float(nearer["level"]))
            reason="Nearest resistance — volume/momentum weakening"
            strength=nearer["strength"]

    expected=(target-close)/close*100
    return target,expected,reason,strength,resistances

def score(d):
    x=d.iloc[-1]
    bb_cut=d["BB_WIDTH"].rolling(20,min_periods=20).quantile(0.40).iloc[-1]

    checks=[
      ("Price 0–3% below 20D breakout",pd.notna(x.DistanceToBO) and 0<=x.DistanceToBO<=3,2),
      ("EMA9 > EMA21",pd.notna(x.EMA9) and pd.notna(x.EMA21) and x.EMA9>x.EMA21,1),
      ("EMA20 > EMA50",pd.notna(x.EMA20) and pd.notna(x.EMA50) and x.EMA20>x.EMA50,1),
      ("RSI 52–65 and rising",pd.notna(x.RSI) and 52<=x.RSI<=65 and pd.notna(x.RSI_Slope) and x.RSI_Slope>0,2),
      ("MACD histogram improving",pd.notna(x.MACD_Hist_Slope) and x.MACD_Hist_Slope>0,1),
      ("RVOL >= 1.2x",pd.notna(x.RVOL) and x.RVOL>=1.2,1),
      ("ADX >= 18 and rising",pd.notna(x.ADX) and x.ADX>=18 and pd.notna(x.ADX_Slope) and x.ADX_Slope>0,1),
      ("Bollinger volatility compressed",pd.notna(x.BB_WIDTH) and pd.notna(bb_cut) and x.BB_WIDTH<=bb_cut,1)
    ]
    total=sum(p for _,ok,p in checks if ok)

    # A BUY requires both a high technical score and enough room to the target.
    target,expected,reason,strength,_=calculate_target(d)
    if total>=8 and expected>=2.0:
        signal="🟢 BUY"
    elif total>=6 and expected>=1.5:
        signal="🟡 WATCH"
    else:
        signal="⚪ AVOID"
    return total,signal,checks,target,expected,reason,strength

@st.cache_data(ttl=86400, show_spinner=False)
def get_nse_universe():
    urls=[
        "https://archives.nseindia.com/content/equities/EQUITY_L.csv",
        "https://www.nseindia.com/api/equity-master"
    ]
    headers={"User-Agent":"Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/151 Safari/537.36",
             "Accept":"text/csv,text/plain,application/json,*/*"}
    for url in urls:
        try:
            r=requests.get(url,headers=headers,timeout=15)
            if r.ok and len(r.content)>1000 and url.endswith(".csv"):
                d=pd.read_csv(StringIO(r.text))
                symcol=next((c for c in d.columns if str(c).upper()=="SYMBOL"),None)
                sercol=next((c for c in d.columns if str(c).upper()=="SERIES"),None)
                if symcol:
                    if sercol:
                        d=d[d[sercol].astype(str).str.upper().eq("EQ")]
                    return sorted(set(d[symcol].astype(str).str.strip().str.upper()))
        except Exception:
            pass
    return []

@st.cache_data(ttl=3600, show_spinner=False)
def download_batch(symbols, period="1y"):
    import yfinance as yf
    tickers=[s+".NS" for s in symbols]
    try:
        return yf.download(tickers,period=period,interval="1d",auto_adjust=False,
                            progress=False,threads=True,group_by="ticker")
    except Exception:
        return None

def extract_symbol(raw,sym):
    if raw is None or raw.empty: return None
    t=sym+".NS"
    try:
        if isinstance(raw.columns,pd.MultiIndex):
            if t in raw.columns.get_level_values(0):
                d=raw[t].copy()
            elif t in raw.columns.get_level_values(-1):
                d=raw.xs(t,axis=1,level=-1).copy()
            else:
                return None
        else:
            d=raw.copy()
        return d.reset_index()
    except Exception:
        return None

with st.sidebar:
    st.header("PRE-BOP Settings")
    minimum=st.slider("Minimum score",0,10,7)
    universe=st.selectbox("Stock universe",[
        "All NSE Equity (automatic)",
        "NSE liquid scan (faster)",
        "My 7 reference stocks"
    ])
    batch_size=st.slider("Batch size",10,100,40,step=10)
    max_symbols=st.slider("Maximum stocks to scan",50,2000,500,step=50)
    st.divider()
    st.write("Entry: price 0–3% below previous 20D high")
    st.write("RSI: 52–65 and rising")
    st.write("RVOL: ≥1.2×")
    st.write("ADX: ≥18 and rising")
    st.write("Target: next resistance + ATR sanity check")
    st.write("Exit warning: resistance + weakening volume/momentum")
    st.warning("Free Yahoo data can be delayed/rate-limited. This is not live NSE data.")

if "scan_results" not in st.session_state: st.session_state.scan_results=None
if "scan_details" not in st.session_state: st.session_state.scan_details={}
if "scan_universe" not in st.session_state: st.session_state.scan_universe=[]

if st.button("🔄 Scan / Refresh Pre-BOP Top 15"):
    if universe=="My 7 reference stocks":
        symbols=["VOLTAMP","EBGNG","EXICOM","CPPLUS","WELCORP","GVT&D","PARAS"]
    else:
        symbols=get_nse_universe()
        if not symbols:
            st.error("Could not download the NSE equity master right now. Try again later.")
            symbols=[]
        if universe=="NSE liquid scan (faster)" and symbols:
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
                try:
                    d=prepare(extract_symbol(raw,sym))
                    if d is None: continue
                    a=score(d); x=d.iloc[-1]
                    if pd.isna(x.RVOL) or pd.isna(x.BOP): continue

                    # Only pre-breakout candidates are allowed into the ranked list.
                    if not (0<=x.DistanceToBO<=3): continue

                    target,expected,reason,strength,resistances=calculate_target(d)
                    buy_price=float(x.Close)

                    rec={
                        "Stock":sym,"Date":x.Date.date(),"Price":float(x.Close),
                        "Buy Price":buy_price,"Target":target,"Expected %":expected,
                        "BOP":float(x.BOP),"Distance %":float(x.DistanceToBO),
                        "Score":a[0],"Signal":a[1],"RSI":float(x.RSI),
                        "ADX":float(x.ADX),"RVOL":float(x.RVOL),
                        "EMA20":float(x.EMA20),"EMA50":float(x.EMA50),
                        "SMA200":float(x.SMA200) if pd.notna(x.SMA200) else np.nan,
                        "ATR":float(x.ATR),"Target Reason":reason,
                        "Resistance Strength":strength,
                        "Vol Trend":float(x.VolTrend) if pd.notna(x.VolTrend) else np.nan
                    }
                    results.append(rec)
                    details[sym]=(a,d,rec,resistances)
                except Exception:
                    continue

            progress.progress((bi+1)/total_batches,
                              text=f"Scanned {min((bi+1)*batch_size,len(symbols))}/{len(symbols)}")
        st.session_state.scan_results=(
            pd.DataFrame(results)
            .sort_values(["Score","Expected %","RVOL"],ascending=False)
            .head(15)
            if results else pd.DataFrame()
        )
        st.session_state.scan_details=details
        progress.empty()

r=st.session_state.scan_results
if r is not None and not r.empty:
    st.subheader("🚀 PRE-BOP TOP 15 — BUY / TARGET")

    view=r.copy()
    view.insert(0,"Rank",range(1,len(view)+1))
    view=view[view.Score>=minimum].copy()

    # Main mobile-friendly display requested by the user.
    main=view[["Stock","Price","Buy Price","Target","Signal"]].copy()
    main.insert(0,"Rank",range(1,len(main)+1))
    main=main.rename(columns={"Stock":"Share","Price":"Current Rate"})
    st.dataframe(
        main.style.format({
            "Current Rate":"₹{:,.2f}",
            "Buy Price":"₹{:,.2f}",
            "Target":"₹{:,.2f}"
        }),
        use_container_width=True,hide_index=True
    )

    st.caption(
        f"Universe scanned: {len(st.session_state.scan_universe)} symbols • "
        f"Pre-BOP results meeting score ≥ {minimum}: {len(view)}"
    )

    with st.expander("📊 Technical Details / Target Logic",expanded=False):
        technical_cols=["Rank","Stock","Date","Price","BOP","Distance %",
                        "Score","Signal","RSI","ADX","RVOL","Vol Trend",
                        "EMA20","EMA50","SMA200","ATR","Expected %",
                        "Target Reason","Resistance Strength"]
        tech=view[technical_cols].copy()
        st.dataframe(
            tech.style.format({
                "Price":"₹{:,.2f}","BOP":"₹{:,.2f}","Distance %":"{:.2f}%",
                "RSI":"{:.1f}","ADX":"{:.1f}","RVOL":"{:.2f}x",
                "Vol Trend":"{:.2f}x","EMA20":"₹{:,.2f}",
                "EMA50":"₹{:,.2f}","SMA200":"₹{:,.2f}",
                "ATR":"₹{:,.2f}","Expected %":"{:.2f}%"
            }),
            use_container_width=True,hide_index=True
        )

    sym=st.selectbox("Select a stock for chart",view.Stock.tolist())
    a,d,rec,resistances=st.session_state.scan_details[sym]
    x=d.iloc[-1]

    c=st.columns(6)
    c[0].metric("Current",f"₹{x.Close:,.2f}")
    c[1].metric("Buy Price",f"₹{rec['Buy Price']:,.2f}")
    c[2].metric("Target",f"₹{rec['Target']:,.2f}")
    c[3].metric("Expected",f"{rec['Expected %']:.2f}%")
    c[4].metric("Score",f"{a[0]}/10")
    c[5].metric("RVOL",f"{x.RVOL:.2f}x")

    if rec["Target Reason"].startswith("Nearest resistance"):
        st.warning(f"Target ₹{rec['Target']:,.2f}: {rec['Target Reason']}.")
    else:
        st.info(f"Target ₹{rec['Target']:,.2f}: {rec['Target Reason']}.")

    if pd.notna(x.RVOL) and x.RVOL < 1:
        st.warning("⚠️ Volume is below its 20-day average. If price approaches resistance while volume falls, consider booking profit rather than extending the target.")
    elif pd.notna(x.RVOL) and x.RVOL >= 1.5:
        st.success("🔥 Volume participation is strong. Target can remain valid while price and momentum continue to strengthen.")

    fig=go.Figure()
    fig.add_trace(go.Candlestick(x=d.Date,open=d.Open,high=d.High,low=d.Low,close=d.Close,name="Price"))
    for col in ["EMA20","EMA50","SMA200","BOP"]:
        fig.add_trace(go.Scatter(x=d.Date,y=d[col],name=col))
    fig.add_hline(y=rec["Target"],line_dash="dash",annotation_text="Target")
    fig.update_layout(height=600,xaxis_rangeslider_visible=False)
    st.plotly_chart(fig,use_container_width=True)

    st.write("### Pre-BOP score breakdown")
    st.dataframe(
        pd.DataFrame([{"Condition":n,"Result":"✓" if ok else "✗","Points":p if ok else 0}
                      for n,ok,p in a[2]]),
        use_container_width=True,hide_index=True
    )
else:
    st.info("Choose a universe in the sidebar and press **Scan / Refresh Pre-BOP Top 15**.")

st.divider()
st.warning(
    "Research tool only. Pre-BOP is a custom heuristic; targets are resistance/ATR estimates, "
    "not guaranteed prices. Free Yahoo Finance data is not a true live NSE feed."
)
