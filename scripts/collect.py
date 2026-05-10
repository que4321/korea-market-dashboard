"""
주식 시장 방향성 지표 수집 스크립트
- 한국: EWY 옵션 (주간/월간), USD/KRW
- 미국: SPY/QQQ 옵션 P/C, VIX, 개별종목 기술지표
GitHub Actions 매일 KST 07:00 실행
"""
import json, os, time
from datetime import datetime, timezone, timedelta, date as date_cls

KST = timezone(timedelta(hours=9))
TODAY = datetime.now(KST).strftime('%Y-%m-%d')
HISTORY_PATH = 'data/history.json'
MAX_DAYS = 90

US_TICKERS = ['TSLA','GOOGL','NVDA','MU','AMZN','MSFT','AAPL','META']


def get_price(ticker):
    try:
        import yfinance as yf
        h = yf.Ticker(ticker).history(period='5d')
        if len(h) < 2: return None
        prev, curr = float(h['Close'].iloc[-2]), float(h['Close'].iloc[-1])
        return {'price': round(curr,4), 'chg': round((curr-prev)/prev*100,3)}
    except Exception as e:
        print(f'[{ticker}] {e}'); return None


def get_rsi(ticker, period=14):
    try:
        import yfinance as yf
        h = yf.Ticker(ticker).history(period='60d')['Close']
        delta = h.diff()
        gain = delta.clip(lower=0).rolling(period).mean()
        loss = (-delta.clip(upper=0)).rolling(period).mean()
        rs = gain / loss
        rsi = 100 - 100/(1+rs)
        return round(float(rsi.iloc[-1]), 1)
    except: return None


def get_ma_position(ticker):
    """현재가 대비 200일/50일 이평선 위치 (%)"""
    try:
        import yfinance as yf
        h = yf.Ticker(ticker).history(period='300d')['Close']
        curr = float(h.iloc[-1])
        ma200 = float(h.rolling(200).mean().iloc[-1])
        ma50  = float(h.rolling(50).mean().iloc[-1])
        hi52  = float(h.rolling(252).max().iloc[-1])
        lo52  = float(h.rolling(252).min().iloc[-1])
        pos52 = round((curr - lo52) / (hi52 - lo52) * 100, 1) if hi52 != lo52 else None
        return {
            'ma200_pct': round((curr - ma200) / ma200 * 100, 2),
            'ma50_pct':  round((curr - ma50)  / ma50  * 100, 2),
            'hi52': round(hi52, 2),
            'lo52': round(lo52, 2),
            'pos52': pos52,  # 52주 고저 대비 위치 (0~100%)
        }
    except Exception as e:
        print(f'[MA {ticker}] {e}'); return None


def parse_option_chain(opt):
    calls, puts = opt.calls, opt.puts
    call_vol = float(calls['volume'].fillna(0).sum())
    put_vol  = float(puts['volume'].fillna(0).sum())
    call_oi  = float(calls['openInterest'].fillna(0).sum())
    put_oi   = float(puts['openInterest'].fillna(0).sum())
    pc = (put_vol/call_vol) if call_vol>0 and put_vol>0 else (put_oi/call_oi if call_oi>0 else None)
    all_iv = list(calls['impliedVolatility'].dropna()) + list(puts['impliedVolatility'].dropna())
    if all_iv:
        cut = int(len(sorted(all_iv))*0.9)
        avg_iv = sum(sorted(all_iv)[:cut])/len(sorted(all_iv)[:cut])*100
    else:
        avg_iv = None
    top_put = top_call = None
    if not puts.empty:
        top_put = float(puts.loc[puts['openInterest'].fillna(0).idxmax(),'strike'])
    if not calls.empty:
        top_call = float(calls.loc[calls['openInterest'].fillna(0).idxmax(),'strike'])
    return {
        'pc': round(pc,3) if pc else None,
        'iv': round(avg_iv,2) if avg_iv else None,
        'top_put': top_put, 'top_call': top_call,
        'call_oi': int(call_oi), 'put_oi': int(put_oi),
    }


def get_options(ticker):
    """주간/월간 옵션 분리 수집"""
    try:
        import yfinance as yf
        t = yf.Ticker(ticker)
        exps = t.options
        if not exps: return None, None
        today_dt = date_cls.today()
        weekly_exp = monthly_exp = None
        for exp in exps:
            d = datetime.strptime(exp,'%Y-%m-%d').date()
            days = (d - today_dt).days
            if days < 0: continue
            if weekly_exp is None and days <= 14: weekly_exp = exp
            if monthly_exp is None and 25 <= days <= 60: monthly_exp = exp
        rw = rm = None
        if weekly_exp:
            rw = parse_option_chain(t.option_chain(weekly_exp))
            print(f'  [{ticker} 주간] P/C={rw["pc"]}, IV={rw["iv"]}%')
            time.sleep(0.5)
        if monthly_exp:
            rm = parse_option_chain(t.option_chain(monthly_exp))
            print(f'  [{ticker} 월간] P/C={rm["pc"]}, IV={rm["iv"]}%')
        return rw, rm
    except Exception as e:
        print(f'[{ticker} 옵션] {e}'); return None, None


def get_stock_options_summary(ticker):
    """개별종목 옵션 — 월간 중심 P/C, IV, OI 집중 행사가"""
    try:
        import yfinance as yf
        t = yf.Ticker(ticker)
        exps = t.options
        if not exps: return None
        today_dt = date_cls.today()
        target_exp = None
        for exp in exps:
            d = datetime.strptime(exp,'%Y-%m-%d').date()
            days = (d - today_dt).days
            if 20 <= days <= 50: target_exp = exp; break
        if not target_exp: target_exp = exps[0]
        r = parse_option_chain(t.option_chain(target_exp))
        r['exp'] = target_exp
        return r
    except Exception as e:
        print(f'[{ticker} 개별옵션] {e}'); return None


def load_history():
    if os.path.exists(HISTORY_PATH):
        with open(HISTORY_PATH,'r',encoding='utf-8') as f:
            try: return json.load(f)
            except: return []
    return []


def save_history(data):
    os.makedirs('data', exist_ok=True)
    with open(HISTORY_PATH,'w',encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    print(f'[저장] {HISTORY_PATH} ({len(data)}일)')


def v(obj, key):
    return obj[key] if obj else None


def main():
    print(f'\n=== [{TODAY}] 수집 시작 ===')

    # ── 한국 지표 ──────────────────────────
    print('[EWY 옵션]')
    ewy_w, ewy_m = get_options('EWY'); time.sleep(1)
    ewy  = get_price('EWY')
    krw  = get_price('USDKRW=X')

    # ── 미국 지수 ──────────────────────────
    print('[미국 지수]')
    spy  = get_price('SPY')
    qqq  = get_price('QQQ')
    vix  = get_price('^VIX')

    # ── SPY/QQQ 옵션 ───────────────────────
    print('[SPY 옵션]')
    spy_w, spy_m = get_options('SPY'); time.sleep(1)
    print('[QQQ 옵션]')
    qqq_w, qqq_m = get_options('QQQ'); time.sleep(1)

    # ── 개별종목 ───────────────────────────
    stocks = {}
    for tk in US_TICKERS:
        print(f'[{tk}]')
        price = get_price(tk)
        ma    = get_ma_position(tk)
        rsi   = get_rsi(tk)
        opt   = get_stock_options_summary(tk)
        time.sleep(0.5)
        stocks[tk] = {
            'price':     v(price,'price'),
            'chg':       v(price,'chg'),
            'rsi':       rsi,
            'ma200_pct': v(ma,'ma200_pct'),
            'ma50_pct':  v(ma,'ma50_pct'),
            'hi52':      v(ma,'hi52'),
            'lo52':      v(ma,'lo52'),
            'pos52':     v(ma,'pos52'),
            'opt_pc':    v(opt,'pc'),
            'opt_iv':    v(opt,'iv'),
            'opt_put':   v(opt,'top_put'),
            'opt_call':  v(opt,'top_call'),
            'opt_put_oi':v(opt,'put_oi'),
            'opt_call_oi':v(opt,'call_oi'),
            'opt_exp':   v(opt,'exp'),
        }
        print(f'  price={v(price,"price")}, RSI={rsi}, pos52={v(ma,"pos52")}%, pc={v(opt,"pc")}')

    record = {
        'date': TODAY,
        # 한국
        'pc_weekly':         v(ewy_w,'pc'),
        'iv_weekly':         v(ewy_w,'iv'),
        'put_strike_weekly': v(ewy_w,'top_put'),
        'call_strike_weekly':v(ewy_w,'top_call'),
        'put_oi_weekly':     v(ewy_w,'put_oi'),
        'call_oi_weekly':    v(ewy_w,'call_oi'),
        'pc_monthly':        v(ewy_m,'pc'),
        'iv_monthly':        v(ewy_m,'iv'),
        'put_strike_monthly':v(ewy_m,'top_put'),
        'call_strike_monthly':v(ewy_m,'top_call'),
        'put_oi_monthly':    v(ewy_m,'put_oi'),
        'call_oi_monthly':   v(ewy_m,'call_oi'),
        'ewy_price': v(ewy,'price'), 'ewy_chg': v(ewy,'chg'),
        'krw':       v(krw,'price'), 'krw_chg': v(krw,'chg'),
        # 미국 지수
        'spy_price': v(spy,'price'), 'spy_chg': v(spy,'chg'),
        'qqq_price': v(qqq,'price'), 'qqq_chg': v(qqq,'chg'),
        'vix':       v(vix,'price'),
        # SPY 옵션
        'spy_pc_weekly':  v(spy_w,'pc'), 'spy_iv_weekly':  v(spy_w,'iv'),
        'spy_pc_monthly': v(spy_m,'pc'), 'spy_iv_monthly': v(spy_m,'iv'),
        'spy_put_monthly':v(spy_m,'top_put'), 'spy_call_monthly':v(spy_m,'top_call'),
        # QQQ 옵션
        'qqq_pc_weekly':  v(qqq_w,'pc'), 'qqq_iv_weekly':  v(qqq_w,'iv'),
        'qqq_pc_monthly': v(qqq_m,'pc'), 'qqq_iv_monthly': v(qqq_m,'iv'),
        'qqq_put_monthly':v(qqq_m,'top_put'), 'qqq_call_monthly':v(qqq_m,'top_call'),
        # 개별종목
        'stocks': stocks,
    }

    history = load_history()
    history = [h for h in history if h.get('date') != TODAY]
    history.append(record)
    history = history[-MAX_DAYS:]
    save_history(history)
    print('=== 완료 ===\n')


if __name__ == '__main__':
    main()
