"""
한국 시장 방향성 지표 수집 스크립트
GitHub Actions에서 매일 실행 → data/history.json 누적 저장
"""
import json
import os
from datetime import datetime, timezone, timedelta
import yfinance as yf

KST = timezone(timedelta(hours=9))
TODAY = datetime.now(KST).strftime('%Y-%m-%d')
HISTORY_PATH = 'data/history.json'
MAX_DAYS = 90  # 최대 90일 보관


def get_ewy_options():
    """EWY 옵션에서 P/C Ratio, IV, OI 집중 행사가 추출"""
    try:
        ewy = yf.Ticker('EWY')
        exp_dates = ewy.options
        if not exp_dates:
            return None

        # 가장 가까운 만기
        opt = ewy.option_chain(exp_dates[0])
        calls = opt.calls
        puts = opt.puts

        call_vol = calls['volume'].fillna(0).sum()
        put_vol = puts['volume'].fillna(0).sum()
        call_oi = calls['openInterest'].fillna(0).sum()
        put_oi = puts['openInterest'].fillna(0).sum()

        pc_vol = put_vol / call_vol if call_vol > 0 else None
        pc_oi = put_oi / call_oi if call_oi > 0 else None
        pc = pc_vol if pc_vol else pc_oi

        # 평균 IV
        all_iv = list(calls['impliedVolatility'].dropna()) + list(puts['impliedVolatility'].dropna())
        avg_iv = (sum(all_iv) / len(all_iv) * 100) if all_iv else None

        # OI 집중 행사가
        top_put_strike = puts.loc[puts['openInterest'].idxmax(), 'strike'] if not puts.empty else None
        top_call_strike = calls.loc[calls['openInterest'].idxmax(), 'strike'] if not calls.empty else None

        return {
            'pc': round(pc, 3) if pc else None,
            'avg_iv': round(avg_iv, 2) if avg_iv else None,
            'top_put_strike': float(top_put_strike) if top_put_strike else None,
            'top_call_strike': float(top_call_strike) if top_call_strike else None,
            'call_oi': int(call_oi),
            'put_oi': int(put_oi),
        }
    except Exception as e:
        print(f'[EWY 옵션 오류] {e}')
        return None


def get_price(ticker):
    """종가 및 등락률 조회"""
    try:
        t = yf.Ticker(ticker)
        hist = t.history(period='2d')
        if len(hist) < 2:
            return None
        prev = hist['Close'].iloc[-2]
        curr = hist['Close'].iloc[-1]
        return {
            'price': round(float(curr), 4),
            'chg': round((curr - prev) / prev * 100, 3),
        }
    except Exception as e:
        print(f'[{ticker} 오류] {e}')
        return None


def load_history():
    if os.path.exists(HISTORY_PATH):
        with open(HISTORY_PATH, 'r', encoding='utf-8') as f:
            return json.load(f)
    return []


def save_history(data):
    os.makedirs('data', exist_ok=True)
    with open(HISTORY_PATH, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def main():
    print(f'[{TODAY}] 데이터 수집 시작...')

    opt = get_ewy_options()
    ewy = get_price('EWY')
    nvda = get_price('NVDA')
    sox = get_price('SOXX')
    krw = get_price('USDKRW=X')

    record = {
        'date': TODAY,
        'pc': opt['pc'] if opt else None,
        'avg_iv': opt['avg_iv'] if opt else None,
        'top_put_strike': opt['top_put_strike'] if opt else None,
        'top_call_strike': opt['top_call_strike'] if opt else None,
        'ewy_price': ewy['price'] if ewy else None,
        'ewy_chg': ewy['chg'] if ewy else None,
        'nvda_chg': nvda['chg'] if nvda else None,
        'sox_chg': sox['chg'] if sox else None,
        'krw': krw['price'] if krw else None,
        'krw_chg': krw['chg'] if krw else None,
    }

    history = load_history()

    # 오늘 날짜 중복 방지
    history = [h for h in history if h.get('date') != TODAY]
    history.append(record)

    # 최대 90일 유지
    history = history[-MAX_DAYS:]

    save_history(history)
    print(f'[완료] 총 {len(history)}일 데이터 저장 → {HISTORY_PATH}')
    print(f'  P/C Ratio: {record["pc"]}')
    print(f'  EWY IV: {record["avg_iv"]}%')
    print(f'  NVDA 등락: {record["nvda_chg"]}%')
    print(f'  USD/KRW: {record["krw"]}')


if __name__ == '__main__':
    main()
