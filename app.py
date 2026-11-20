import sqlite3
from pathlib import Path
import requests
import pandas as pd
import numpy as np
import streamlit as st
from datetime import datetime, timezone

st.set_page_config(page_title="SINKA QUANT PRO", page_icon="📈", layout="wide")
API="https://www.okx.com/api/v5"
FIVE=["BTC","ETH","SOL","BNB","XRP"]
DB=Path(__file__).with_name("trades.db")

def connect():
    c=sqlite3.connect(DB)
    c.row_factory=sqlite3.Row
    c.execute("""CREATE TABLE IF NOT EXISTS trades(
      id INTEGER PRIMARY KEY AUTOINCREMENT, symbol TEXT, side TEXT,
      entry REAL, qty REAL, leverage REAL, sl REAL, tp1 REAL, tp2 REAL,
      opened TEXT, closed TEXT, exit REAL, fee REAL DEFAULT 0)""")
    c.commit()
    return c

def api(path, params):
    r=requests.get(API+path,params=params,timeout=15)
    r.raise_for_status()
    data=r.json()
    if data.get("code")!="0":
        raise RuntimeError(data.get("msg","OKX API error"))
    return data["data"]

@st.cache_data(ttl=20)
def tickers():
    return {x["instId"]:x for x in api("/api/v5/market/tickers",{"instType":"SWAP"}) if x["instId"].endswith("-USDT-SWAP")}

@st.cache_data(ttl=90)
def candles(symbol,bar="15m"):
    rows=api("/api/v5/market/candles",{"instId":symbol,"bar":bar,"limit":"300"})
    rows=[x for x in rows if len(x)>8 and x[8]=="1"]
    if len(rows)<60: raise ValueError("Not enough completed candles")
    d=pd.DataFrame(rows,columns=["ts","open","high","low","close","vol","volCcy","volQuote","confirm"])
    for col in ["open","high","low","close","volQuote"]: d[col]=pd.to_numeric(d[col])
    return d.sort_values("ts").reset_index(drop=True)

def indicators(df):
    d=df.copy()
    for n in (20,50,200): d[f"ema{n}"]=d.close.ewm(span=n,adjust=False).mean()
    delta=d.close.diff()
    up=delta.clip(lower=0).ewm(alpha=1/14,adjust=False).mean()
    down=(-delta.clip(upper=0)).ewm(alpha=1/14,adjust=False).mean()
    d["rsi"]=100-100/(1+up/down.replace(0,np.nan))
    tr=pd.concat([d.high-d.low,(d.high-d.close.shift()).abs(),(d.low-d.close.shift()).abs()],axis=1).max(axis=1)
    d["atr"]=tr.ewm(alpha=1/14,adjust=False).mean()
    return d

def signal(d):
    x=d.iloc[-1]
    long=x.ema20>x.ema50 and x.close>x.ema20 and 50<=x.rsi<=72
    short=x.ema20<x.ema50 and x.close<x.ema20 and 28<=x.rsi<=50
    side="LONG" if long else "SHORT" if short else "WAIT"
    score=min(100,round(35+min(abs(x.ema20/x.ema50-1)*1400,25)+min(abs(x.rsi-50)*1.2,20)+(20 if side!="WAIT" else 0)))
    return side,score

def scan(m):
    liquid=sorted(m.values(),key=lambda t:float(t.get("volCcy24h") or 0)*float(t.get("last") or 0),reverse=True)[:20]
    result=[]
    for t in liquid:
        try:
            d=indicators(candles(t["instId"]))
            side,score=signal(d)
            result.append((t["instId"],side,score,float(t["last"])))
        except Exception: continue
    return sorted(result,key=lambda x:(x[1]!="WAIT",x[2]),reverse=True)[:5]

def plan(symbol, market):
    st.subheader("交易規劃 · "+symbol)
    try:
        d=indicators(candles(symbol))
    except Exception as exc:
        st.error(str(exc)); return
    st.line_chart(d.set_index("ts")[["close","ema20","ema50"]])
    side,score=signal(d)
    price=float(market.get(symbol,{}).get("last") or d.iloc[-1].close)
    atr=float(d.iloc[-1].atr)
    st.write(f"訊號：**{side}** · 技術評分：**{score}/100**（不是勝率） · RSI：{d.iloc[-1].rsi:.1f}")
    direction=st.radio("交易方向",["LONG","SHORT"],index=0 if side!="SHORT" else 1,horizontal=True)
    margin=st.number_input("保證金 USDT",min_value=1.0,value=100.0)
    risk=st.number_input("最大預估虧損 USDT",min_value=0.1,value=5.0)
    leverage=st.slider("槓桿上限",1,20,5)
    atrmult=st.slider("ATR 止損倍數",0.5,4.0,1.5,0.25)
    sign=1 if direction=="LONG" else -1
    dist=max(atr*atrmult,price*0.001)
    sl=price-sign*dist
    tp1=price+sign*dist*1.5
    tp2=price+sign*dist*2.5
    fee_rate=0.001
    qty=min(margin*leverage/price,risk/(dist+price*fee_rate))
    c1,c2,c3,c4=st.columns(4)
    c1.metric("參考進場",f"{price:.6g}")
    c2.metric("SL",f"{sl:.6g}")
    c3.metric("TP1",f"{tp1:.6g}")
    c4.metric("TP2",f"{tp2:.6g}")
    st.write(f"參考數量：**{qty:.6g} {symbol.split('-')[0]}** · 預估名目倉位：**{qty*price:.2f} USDT** · 預估止損風險（含假設費用）：**{qty*(dist+price*fee_rate):.2f} USDT**")
    st.caption("請先在 OKX 自行下單，再以實際成交價與數量記錄；止損無法保證最大損失。")
    with st.form("open_trade"):
        actual=st.number_input("實際成交價",min_value=0.00000001,value=price,format="%.8f")
        amount=st.number_input("實際成交數量（幣）",min_value=0.00000001,value=max(qty,0.00000001),format="%.8f")
        if st.form_submit_button("確認已在 OKX 下單 → 加入持倉"):
            with connect() as c:
                c.execute("INSERT INTO trades(symbol,side,entry,qty,leverage,sl,tp1,tp2,opened) VALUES (?,?,?,?,?,?,?,?,?)",
                          (symbol,direction,actual,amount,leverage,sl,tp1,tp2,datetime.now(timezone.utc).isoformat()))
            st.success("持倉已記錄。此操作不會向 OKX 下單。")

def positions(m):
    st.subheader("手動持倉監控")
    with connect() as c:
        rows=[dict(x) for x in c.execute("SELECT * FROM trades WHERE closed IS NULL ORDER BY id DESC")]
    if not rows: st.info("目前沒有未平倉交易")
    for p in rows:
        last=float(m.get(p["symbol"],{}).get("last") or 0)
        direction=1 if p["side"]=="LONG" else -1
        pnl=(last-p["entry"])*p["qty"]*direction if last else None
        with st.expander(f"#{p['id']} {p['symbol']} {p['side']} | PnL: {pnl:.2f} USDT" if pnl is not None else f"#{p['id']} {p['symbol']} | 報價暫不可用"):
            st.write(f"進場 {p['entry']} · 數量 {p['qty']} · SL {p['sl']} · TP1 {p['tp1']} · TP2 {p['tp2']} · 開倉 {p['opened']}")
            with st.form("close_"+str(p["id"])):
                exitprice=st.number_input("實際平倉價格",min_value=0.00000001,value=last or p["entry"],format="%.8f")
                fee=st.number_input("總手續費及資金費 USDT",min_value=0.0,value=0.0)
                if st.form_submit_button("確認已在 OKX 全部平倉"):
                    with connect() as c:
                        c.execute("UPDATE trades SET closed=?,exit=?,fee=? WHERE id=?",(datetime.now(timezone.utc).isoformat(),exitprice,fee,p["id"]))
                    st.rerun()

def history():
    st.subheader("已平倉交易紀錄")
    with connect() as c:
        rows=[dict(x) for x in c.execute("SELECT * FROM trades WHERE closed IS NOT NULL ORDER BY id DESC")]
    if not rows: st.info("尚無已平倉交易"); return
    d=pd.DataFrame(rows)
    d["net_pnl"]=(d["exit"]-d["entry"])*d["qty"]*np.where(d["side"]=="LONG",1,-1)-d["fee"]
    a,b,c=st.columns(3)
    a.metric("總淨盈虧",f"{d.net_pnl.sum():.2f} USDT")
    b.metric("勝率",f"{(d.net_pnl>0).mean()*100:.1f}%")
    c.metric("每筆 EV",f"{d.net_pnl.mean():.2f} USDT")
    st.dataframe(d,use_container_width=True)
    st.download_button("下載 CSV",d.to_csv(index=False).encode("utf-8-sig"),"sinka_trades.csv","text/csv")

st.title("📈 SINKA QUANT PRO")
st.caption("OKX · 手動實盤紀錄 · 行情為公開 API · 不自動下單")
if st.sidebar.button("🔄 更新行情"):
    st.cache_data.clear()
    st.rerun()
page=st.sidebar.radio("功能",["行情與掃描","交易規劃","持倉監控","交易紀錄"])
try:
    market=tickers()
except Exception as exc:
    st.error(f"無法連接 OKX：{exc}")
    st.stop()
if "symbol" not in st.session_state: st.session_state.symbol="BTC-USDT-SWAP"
if page=="行情與掃描":
    st.subheader("五大主流貨幣")
    cols=st.columns(5)
    for base,col in zip(FIVE,cols):
        sym=base+"-USDT-SWAP"
        t=market.get(sym)
        with col:
            st.metric(base,f"{float(t['last']):,.6g}" if t else "N/A")
            if st.button("交易規劃",key=sym):
                st.session_state.symbol=sym
                st.session_state.go_plan=True
    if st.session_state.get("go_plan"):
        st.session_state.go_plan=False
        plan(st.session_state.symbol,market)
    st.subheader("市場候選 TOP 5")
    st.caption("按流動性篩選後依技術訊號排序；分數不是歷史勝率。")
    if st.button("開始掃描"):
        st.session_state.candidates=scan(market)
    for sym,side,score,price in st.session_state.get("candidates",[]):
        c1,c2,c3,c4=st.columns([3,2,2,2])
        c1.write(sym);c2.write(side);c3.write(f"{score}/100")
        if c4.button("規劃",key="scan_"+sym):
            st.session_state.symbol=sym
            plan(sym,market)
elif page=="交易規劃":
    symbols=sorted(market.keys())
    index=symbols.index(st.session_state.symbol) if st.session_state.symbol in symbols else 0
    st.session_state.symbol=st.selectbox("選擇 OKX 合約",symbols,index=index)
    plan(st.session_state.symbol,market)
elif page=="持倉監控": positions(market)
else: history()
