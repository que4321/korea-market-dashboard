"""
한국 시장 방향성 지표 수집 스크립트
GitHub Actions에서 매일 실행 → data/history.json 누적 저장
"""
import json
import os
import time
from datetime import datetime, timezone, timedelta

KST = timezone(timedelta(hours=9))
TODAY = datetime.now(KST).strftime('%Y-%m-%d')
HISTORY_PATH = 'data/history.json'
MAX_DAYS = 90


def get_price(ticker):
    try:
        import yfinance as yf
        t = yf.Ticker(ticker)
        hist = t.history(period='5d')
        if len(hist) < 2:
            return None
        prev = float(hist['Close'].iloc[-2])
        curr = float(hist['Close'].iloc[-1])
        chg = (curr - prev) / prev * 100
        return {'price': round(curr, 4), 'chg': round(chg, 3)}
    except Exception as e:
        print(f'[{ticker} 오류] {e}')
        return None


def get_ewy_options():
    try:
        import yfinance as yf
        ewy = yf.Ticker('EWY')
        exp_dates = ewy.options
        if not exp_dates:
            return None
        opt = ewy.option_chain(exp_dates[0])
        calls = opt.calls
        puts = opt.puts
        call_vol = float(calls['volume'].fillna(0).sum())
        put_vol  = float(puts['volume'].fillna(0).sum())
        call_oi  = float(calls['openInterest'].fillna(0).sum())
        put_oi   = float(puts['openInterest'].fillna(0).sum())
        pc = None
        if call_vol > 0 and put_vol > 0:
            pc = put_vol / call_vol
        elif call_oi > 0:
            pc = put_oi / call_oi
        all_iv = list(calls['impliedVolatility'].dropna()) + list(puts['impliedVolatility'].dropna())
        avg_iv = (sum(all_iv) / len(all_iv) * 100) if all_iv else None
        top_put = top_call = None
        if not puts.empty:
            top_put = float(puts.loc[puts['openInterest'].fillna(0).idxmax(), 'strike'])
        if not calls.empty:
            top_call = float(calls.loc[calls['openInterest'].fillna(0).idxmax(), 'strike'])
        print(f'[EWY] P/C={round(pc,3) if pc else None}, IV={round(avg_iv,2) if avg_iv else None}%')
        return {
            'pc': round(pc, 3) if pc else None,
            'avg_iv': round(avg_iv, 2) if avg_iv else None,
            'top_put_strike': top_put,
            'top_call_strike': top_call,
            'call_oi': int(call_oi),
            'put_oi': int(put_oi),
        }
    except Exception as e:
        print(f'[EWY 옵션 오류] {e}')
        return None


def load_history():
    if os.path.exists(HISTORY_PATH):
        with open(HISTORY_PATH, 'r', encoding='utf-8') as f:
            try:
                return json.load(f)
            except Exception:
                return []
    return []


def save_history(data):
    os.makedirs('data', exist_ok=True)
    with open(HISTORY_PATH, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    print(f'[저장] {HISTORY_PATH} ({len(data)}일)')


def main():
    print(f'\n=== [{TODAY}] 수집 시작 ===')
    opt  = get_ewy_options(); time.sleep(1)
    ewy  = get_price('EWY')
    nvda = get_price('NVDA')
    sox  = get_price('SOXX')
    krw  = get_price('USDKRW=X')
    print(f'EWY={ewy}, NVDA={nvda}, SOXX={sox}, KRW={krw}')

    record = {
        'date': TODAY,
        'pc':              opt['pc']              if opt else None,
        'avg_iv':          opt['avg_iv']          if opt else None,
        'top_put_strike':  opt['top_put_strike']  if opt else None,
        'top_call_strike': opt['top_call_strike'] if opt else None,
        'call_oi':         opt['call_oi']         if opt else None,
        'put_oi':          opt['put_oi']          if opt else None,
        'ewy_price':       ewy['price']   if ewy  else None,
        'ewy_chg':         ewy['chg']     if ewy  else None,
        'nvda_price':      nvda['price']  if nvda else None,
        'nvda_chg':        nvda['chg']    if nvda else None,
        'sox_price':       sox['price']   if sox  else None,
        'sox_chg':         sox['chg']     if sox  else None,
        'krw':             krw['price']   if krw  else None,
        'krw_chg':         krw['chg']     if krw  else None,
    }

    history = load_history()
    history = [h for h in history if h.get('date') != TODAY]
    history.append(record)
    history = history[-MAX_DAYS:]
    save_history(history)
    print('=== 완료 ===')


if __name__ == '__main__':
    main()
