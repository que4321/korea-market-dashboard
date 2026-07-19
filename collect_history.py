#!/usr/bin/env python3
"""
collect_history.py
한국/미국 시장 데이터 수집 → data/history.json 저장
EWY 옵션, SPY/QQQ 옵션, 개별종목 (yfinance)
매일 07:00 KST 자동 실행
"""
import json, os, datetime, traceback
from pathlib import Path
import yfinance as yf

HIST_FILE = Path("data/history.json")
MAX_DAYS  = 90  # 최근 90일치만 유지

US_STOCKS = ["TSLA","GOOGL","NVDA","MU","AMZN","MSFT","AAPL","META","SPCX","SKHY","NBIS","MRVL"]

def safe(fn, default=None):
    try: return fn()
    except: return default

def get_price_chg(ticker, period="5d"):
    try:
        h = yf.Ticker(ticker).history(period=period, auto_adjust=False)
        if h.empty or len(h) < 2: return None, None
        cur  = round(float(h["Close"].iloc[-1]), 2)
        prev = round(float(h["Close"].iloc[-2]), 2)
        chg  = round((cur - prev) / prev * 100, 3) if prev else 0
        return cur, chg
    except: return None, None

def get_vix():
    try:
        h = yf.Ticker("^VIX").history(period="2d", auto_adjust=False)
        if h.empty: return None
        return round(float(h["Close"].iloc[-1]), 2)
    except: return None

def get_options(ticker):
    """P/C Ratio, IV, Put/Call OI 집중 행사가 (주간/월간)"""
    try:
        t = yf.Ticker(ticker)
        exps = t.options
        if not exps: return {}

        today = datetime.date.today()

        def pick_exp(target_days):
            best = None
            for e in exps:
                d = datetime.date.fromisoformat(e)
                diff = (d - today).days
                if diff >= 0:
                    if best is None or abs(diff - target_days) < abs((datetime.date.fromisoformat(best) - today).days - target_days):
                        best = e
            return best

        weekly_exp  = pick_exp(7)
        monthly_exp = pick_exp(30)
        result = {}

        for label, exp in [("weekly", weekly_exp), ("monthly", monthly_exp)]:
            if not exp: continue
            try:
                chain = t.option_chain(exp)
                puts  = chain.puts
                calls = chain.calls
                total_put  = puts["openInterest"].sum()
                total_call = calls["openInterest"].sum()
                pc = round(total_put / total_call, 3) if total_call else None
                # IV (ATM 근사)
                cur_price, _ = get_price_chg(ticker, "2d")
                if cur_price:
                    atm_put  = puts.iloc[(puts["strike"] - cur_price).abs().argsort()[:1]]
                    atm_call = calls.iloc[(calls["strike"] - cur_price).abs().argsort()[:1]]
                    iv = round(float((atm_put["impliedVolatility"].values[0] +
                                      atm_call["impliedVolatility"].values[0]) / 2 * 100), 2)
                else:
                    iv = None
                # OI 집중 행사가
                put_strike  = float(puts.loc[puts["openInterest"].idxmax(), "strike"])  if not puts.empty  else None
                call_strike = float(calls.loc[calls["openInterest"].idxmax(), "strike"]) if not calls.empty else None

                result[label] = {
                    "pc": pc, "iv": iv,
                    "put_strike": put_strike, "call_strike": call_strike,
                    "put_oi": int(total_put), "call_oi": int(total_call),
                    "exp": exp
                }
            except Exception as e:
                print(f"  ⚠ {ticker} {label} 옵션 오류: {e}")
        return result
    except Exception as e:
        print(f"  ⚠ {ticker} 옵션 오류: {e}")
        return {}

def get_stock_data(ticker):
    try:
        t = yf.Ticker(ticker)
        h = t.history(period="300d", auto_adjust=False)
        if h.empty or len(h) < 20: return None
        c = h["Close"].dropna()
        cur   = round(float(c.iloc[-1]), 2)
        prev  = round(float(c.iloc[-2]), 2)
        chg   = round((cur - prev) / prev * 100, 3) if prev else 0
        ma200 = round(float(c.tail(200).mean()), 2) if len(c) >= 200 else round(float(c.mean()), 2)
        ma50  = round(float(c.tail(50).mean()), 2)  if len(c) >= 50  else round(float(c.mean()), 2)
        hi52  = round(float(c.tail(252).max()), 2)
        lo52  = round(float(c.tail(252).min()), 2)
        pos52 = round((cur - lo52) / (hi52 - lo52) * 100, 1) if hi52 != lo52 else 100.0

        # RSI(14)
        delta = c.diff()
        gain  = delta.clip(lower=0).tail(15)
        loss  = (-delta.clip(upper=0)).tail(15)
        avg_g = gain.mean(); avg_l = loss.mean()
        rsi   = round(100 - 100 / (1 + avg_g / avg_l), 1) if avg_l else 100.0

        ma200_pct = round((cur - ma200) / ma200 * 100, 2)
        ma50_pct  = round((cur - ma50)  / ma50  * 100, 2)

        # 옵션
        opts = get_options(ticker)
        mo = opts.get("monthly", {})

        return {
            "price": cur, "chg": chg,
            "rsi": rsi,
            "ma200_pct": ma200_pct, "ma50_pct": ma50_pct,
            "hi52": hi52, "lo52": lo52, "pos52": pos52,
            "opt_pc":   mo.get("pc"),
            "opt_iv":   mo.get("iv"),
            "opt_put":  mo.get("put_strike"),
            "opt_call": mo.get("call_strike"),
            "opt_put_oi":  mo.get("put_oi"),
            "opt_call_oi": mo.get("call_oi"),
            "opt_exp":  mo.get("exp"),
        }
    except Exception as e:
        print(f"  ⚠ {ticker} 오류: {e}")
        return None

def main():
    today = datetime.date.today().isoformat()
    print(f"🚀 collect_history.py 시작 — {today}")

    # 기존 history 로드
    HIST_FILE.parent.mkdir(exist_ok=True)
    history = []
    if HIST_FILE.exists():
        try: history = json.loads(HIST_FILE.read_text())
        except: history = []

    # 오늘 데이터 이미 있으면 업데이트
    existing = {d["date"]: i for i, d in enumerate(history)}

    entry = {"date": today}

    # EWY
    print("EWY 수집...")
    ewy_price, ewy_chg = get_price_chg("EWY")
    entry["ewy_price"] = ewy_price
    entry["ewy_chg"]   = ewy_chg

    # EWY 옵션
    ewy_opts = get_options("EWY")
    ew = ewy_opts.get("weekly",  {})
    em = ewy_opts.get("monthly", {})
    entry["pc_weekly"]           = ew.get("pc")
    entry["iv_weekly"]           = ew.get("iv")
    entry["put_strike_weekly"]   = ew.get("put_strike")
    entry["call_strike_weekly"]  = ew.get("call_strike")
    entry["put_oi_weekly"]       = ew.get("put_oi")
    entry["call_oi_weekly"]      = ew.get("call_oi")
    entry["pc_monthly"]          = em.get("pc")
    entry["iv_monthly"]          = em.get("iv")
    entry["put_strike_monthly"]  = em.get("put_strike")
    entry["call_strike_monthly"] = em.get("call_strike")
    entry["put_oi_monthly"]      = em.get("put_oi")
    entry["call_oi_monthly"]     = em.get("call_oi")

    # 환율
    print("환율 수집...")
    krw, krw_chg = get_price_chg("USDKRW=X")
    entry["krw"] = krw; entry["krw_chg"] = krw_chg

    # SPY / QQQ
    print("SPY/QQQ 수집...")
    spy, spy_chg = get_price_chg("SPY")
    qqq, qqq_chg = get_price_chg("QQQ")
    entry["spy_price"] = spy; entry["spy_chg"] = spy_chg
    entry["qqq_price"] = qqq; entry["qqq_chg"] = qqq_chg
    entry["vix"] = get_vix()

    # SPY 옵션
    spy_opts = get_options("SPY")
    sw = spy_opts.get("weekly", {}); sm = spy_opts.get("monthly", {})
    entry["spy_pc_weekly"]   = sw.get("pc");  entry["spy_iv_weekly"]  = sw.get("iv")
    entry["spy_pc_monthly"]  = sm.get("pc");  entry["spy_iv_monthly"] = sm.get("iv")
    entry["spy_put_monthly"] = sm.get("put_strike"); entry["spy_call_monthly"] = sm.get("call_strike")

    # QQQ 옵션
    qqq_opts = get_options("QQQ")
    qw = qqq_opts.get("weekly", {}); qm = qqq_opts.get("monthly", {})
    entry["qqq_pc_weekly"]   = qw.get("pc");  entry["qqq_iv_weekly"]  = qw.get("iv")
    entry["qqq_pc_monthly"]  = qm.get("pc");  entry["qqq_iv_monthly"] = qm.get("iv")
    entry["qqq_put_monthly"] = qm.get("put_strike"); entry["qqq_call_monthly"] = qm.get("call_strike")

    # 개별종목
    print("개별종목 수집...")
    stocks = {}
    for ticker in US_STOCKS:
        print(f"  {ticker}...", end=" ", flush=True)
        d = get_stock_data(ticker)
        if d:
            stocks[ticker] = d
            print(f"${d['price']} RSI{d['rsi']}")
        else:
            print("스킵")
    entry["stocks"] = stocks

    # 저장
    if today in existing:
        history[existing[today]] = entry
    else:
        history.append(entry)

    # 최근 MAX_DAYS일만 유지
    history = sorted(history, key=lambda x: x["date"])[-MAX_DAYS:]

    HIST_FILE.write_text(json.dumps(history, ensure_ascii=False, indent=2))
    print(f"\n✅ 저장 완료: {HIST_FILE} ({len(history)}일치)")

if __name__ == "__main__":
    main()
