"""
한국 시장 방향성 지표 수집 스크립트
GitHub Actions에서 매일 실행 → data/history.json 누적 저장
주간/월간 옵션 분리 수집
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


def parse_option_chain(opt):
    """옵션 체인 하나에서 P/C, IV, OI 집중 행사가 추출"""
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

    all_iv = (
        list(calls['impliedVolatility'].dropna()) +
        list(puts['impliedVolatility'].dropna())
    )
    # 이상치 제거: 상위 10% 제외 후 평균
    if all_iv:
        all_iv_sorted = sorted(all_iv)
        cutoff = int(len(all_iv_sorted) * 0.9)
        all_iv_clean = all_iv_sorted[:cutoff]
        avg_iv = (sum(all_iv_clean) / len(all_iv_clean) * 100) if all_iv_clean else None
    else:
        avg_iv = None

    top_put = top_call = None
    if not puts.empty and 'openInterest' in puts.columns:
        top_put = float(puts.loc[puts['openInterest'].fillna(0).idxmax(), 'strike'])
    if not calls.empty and 'openInterest' in calls.columns:
        top_call = float(calls.loc[calls['openInterest'].fillna(0).idxmax(), 'strike'])

    return {
        'pc':   round(pc, 3) if pc else None,
        'iv':   round(avg_iv, 2) if avg_iv else None,
        'top_put':  top_put,
        'top_call': top_call,
        'call_oi':  int(call_oi),
        'put_oi':   int(put_oi),
    }


def get_ewy_options():
    """주간/월간 옵션 분리 수집"""
    try:
        import yfinance as yf
        from datetime import date
        ewy = yf.Ticker('EWY')
        exp_dates = ewy.options
        if not exp_dates:
            print('[EWY] 만기일 없음')
            return None, None

        today_dt = date.today()
        weekly_exp = None
        monthly_exp = None

        for exp in exp_dates:
            exp_dt = datetime.strptime(exp, '%Y-%m-%d').date()
            days_left = (exp_dt - today_dt).days
            if days_left < 0:
                continue
            # 주간: 7일 이내
            if weekly_exp is None and days_left <= 14:
                weekly_exp = exp
            # 월간: 25~50일 사이
            if monthly_exp is None and 25 <= days_left <= 60:
                monthly_exp = exp

        result_w = result_m = None

        if weekly_exp:
            print(f'[EWY 주간] 만기: {weekly_exp}')
            opt_w = ewy.option_chain(weekly_exp)
            result_w = parse_option_chain(opt_w)
            print(f'  P/C={result_w["pc"]}, IV={result_w["iv"]}%')
            time.sleep(1)

        if monthly_exp:
            print(f'[EWY 월간] 만기: {monthly_exp}')
            opt_m = ewy.option_chain(monthly_exp)
            result_m = parse_option_chain(opt_m)
            print(f'  P/C={result_m["pc"]}, IV={result_m["iv"]}%')

        return result_w, result_m

    except Exception as e:
        print(f'[EWY 옵션 오류] {e}')
        return None, None


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

    opt_w, opt_m = get_ewy_options()
    time.sleep(1)

    ewy  = get_price('EWY')
    nvda = get_price('NVDA')
    sox  = get_price('SOXX')
    krw  = get_price('USDKRW=X')
    print(f'EWY={ewy}, NVDA={nvda}, SOXX={sox}, KRW={krw}')

    def v(obj, key):
        return obj[key] if obj else None

    record = {
        'date': TODAY,
        # 주간 옵션
        'pc_weekly':        v(opt_w, 'pc'),
        'iv_weekly':        v(opt_w, 'iv'),
        'put_strike_weekly':v(opt_w, 'top_put'),
        'call_strike_weekly':v(opt_w,'top_call'),
        'put_oi_weekly':    v(opt_w, 'put_oi'),
        'call_oi_weekly':   v(opt_w, 'call_oi'),
        # 월간 옵션
        'pc_monthly':        v(opt_m, 'pc'),
        'iv_monthly':        v(opt_m, 'iv'),
        'put_strike_monthly':v(opt_m, 'top_put'),
        'call_strike_monthly':v(opt_m,'top_call'),
        'put_oi_monthly':    v(opt_m, 'put_oi'),
        'call_oi_monthly':   v(opt_m, 'call_oi'),
        # 가격
        'ewy_price':  v(ewy,  'price'),
        'ewy_chg':    v(ewy,  'chg'),
        'nvda_price': v(nvda, 'price'),
        'nvda_chg':   v(nvda, 'chg'),
        'sox_price':  v(sox,  'price'),
        'sox_chg':    v(sox,  'chg'),
        'krw':        v(krw,  'price'),
        'krw_chg':    v(krw,  'chg'),
    }

    history = load_history()
    history = [h for h in history if h.get('date') != TODAY]
    history.append(record)
    history = history[-MAX_DAYS:]
    save_history(history)
    print('=== 완료 ===\n')


if __name__ == '__main__':
    main()
