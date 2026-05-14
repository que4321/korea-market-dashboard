"""
collect_investor.py
────────────────────────────────────────────────
관심 종목 10개의 투자자별(기관/외국인/개인) 일별 매매 데이터를
KRX 정보데이터시스템에서 수집하여 JSON으로 저장합니다.

저장 경로: data/investor_data.json
실행 주기: 매일 18:00 KST (GitHub Actions)
────────────────────────────────────────────────
"""

import requests
import json
import os
import time
from datetime import datetime, timedelta
import pytz

# ── 관심 종목 10개 ──────────────────────────────
WATCH_LIST = {
    "005930": "삼성전자",
    "000660": "SK하이닉스",
    "042700": "한미반도체",
    "010140": "삼성중공업",
    "015760": "한국전력",
    "028050": "삼성E&A",
    "035420": "NAVER",
    "034020": "두산에너빌리티",
    "033780": "KT&G",
    "111770": "영원무역",
}

# ── 기간 설정 (3개월 = 약 66거래일) ─────────────
KST = pytz.timezone("Asia/Seoul")
TODAY = datetime.now(KST).strftime("%Y%m%d")
START_3M = (datetime.now(KST) - timedelta(days=95)).strftime("%Y%m%d")
START_1M = (datetime.now(KST) - timedelta(days=35)).strftime("%Y%m%d")

# ── KRX API 헤더 ─────────────────────────────────
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "Referer": "http://data.krx.co.kr/",
    "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
}

def fetch_krx_investor(ticker: str, start: str, end: str) -> list:
    """
    KRX 정보데이터시스템: 투자자별 일별 매매현황
    OTP 발급 → 실제 데이터 조회 2단계
    """
    # 1단계: OTP 발급
    otp_url = "http://data.krx.co.kr/comm/fileDn/GenerateOTP/generate.cmd"
    otp_params = {
        "locale": "ko_KR",
        "ticker": ticker,
        "fromdate": start,
        "todate": end,
        "share": "1",       # 1: 주수, 2: 금액
        "money": "1",
        "csvxls_isNo": "false",
        "name": "fileDown",
        "url": "dbms/MDC/STAT/standard/MDCSTAT02302",
    }
    try:
        otp_res = requests.post(otp_url, data=otp_params, headers=HEADERS, timeout=15)
        otp = otp_res.text.strip()
        if not otp:
            print(f"  ⚠ {ticker}: OTP 발급 실패")
            return []
    except Exception as e:
        print(f"  ⚠ {ticker}: OTP 요청 오류 - {e}")
        return []

    # 2단계: 실제 데이터 다운로드 (CSV)
    data_url = "http://data.krx.co.kr/comm/fileDn/download_csv/download.cmd"
    try:
        data_res = requests.post(data_url, data={"code": otp}, headers=HEADERS, timeout=20)
        data_res.encoding = "euc-kr"
        lines = data_res.text.strip().split("\n")
    except Exception as e:
        print(f"  ⚠ {ticker}: 데이터 다운로드 오류 - {e}")
        return []

    if len(lines) < 2:
        print(f"  ⚠ {ticker}: 데이터 없음")
        return []

    rows = []
    header = [h.strip().strip('"') for h in lines[0].split(",")]

    for line in lines[1:]:
        cols = [c.strip().strip('"').replace(",", "") for c in line.split(",")]
        if len(cols) < 5:
            continue
        try:
            # KRX CSV 컬럼 구조:
            # 날짜, 종가, 대비, 기관합계매수, 기관합계매도, 외국인합계매수, 외국인합계매도, 개인매수, 개인매도, ...
            date_str = cols[0].replace(".", "-").replace("/", "-")
            close_p  = int(cols[1]) if cols[1] else 0
            # 시가가 없는 경우 종가로 대체 (일부 API는 시가 미제공)
            open_p   = int(cols[2]) if len(cols) > 2 and cols[2] else close_p

            inst_buy  = int(cols[3]) if cols[3] else 0
            inst_sell = int(cols[4]) if cols[4] else 0
            fore_buy  = int(cols[5]) if cols[5] else 0
            fore_sell = int(cols[6]) if cols[6] else 0
            pers_buy  = int(cols[7]) if len(cols) > 7 and cols[7] else 0
            pers_sell = int(cols[8]) if len(cols) > 8 and cols[8] else 0

            rows.append({
                "date":      date_str,
                "close":     close_p,
                "open":      open_p,
                "avg":       round((open_p + close_p) / 2),
                "inst_buy":  inst_buy,
                "inst_sell": inst_sell,
                "inst_net":  inst_buy - inst_sell,
                "fore_buy":  fore_buy,
                "fore_sell": fore_sell,
                "fore_net":  fore_buy - fore_sell,
                "pers_buy":  pers_buy,
                "pers_sell": pers_sell,
                "pers_net":  pers_buy - pers_sell,
            })
        except (ValueError, IndexError):
            continue

    # 날짜 오름차순 정렬
    rows.sort(key=lambda x: x["date"])
    return rows


def calc_avg_cost(rows: list, net_key: str, price_key: str = "close") -> dict:
    """
    가중평균 매입단가 계산
    avg_cost = Σ(순매수량 × 기준가격) / Σ(순매수량)  [순매수 구간만]
    """
    cum_amt = 0
    cum_qty = 0
    daily_avg = []
    total_net = 0

    for r in rows:
        net = r[net_key]
        price = r[price_key]
        total_net += net
        if net > 0:
            cum_amt += net * price
            cum_qty += net
        daily_avg.append(round(cum_amt / cum_qty) if cum_qty > 0 else None)

    return {
        "avg_cost":   round(cum_amt / cum_qty) if cum_qty > 0 else None,
        "total_net":  total_net,
        "buy_qty":    cum_qty,
        "daily_avg":  daily_avg,
    }


def build_summary(ticker: str, name: str, rows: list) -> dict:
    """종목별 요약 데이터 생성"""
    if not rows:
        return {"ticker": ticker, "name": name, "error": "데이터 없음"}

    last = rows[-1]
    cur_close = last["close"]

    # 종가 기준
    inst_c  = calc_avg_cost(rows, "inst_net", "close")
    fore_c  = calc_avg_cost(rows, "fore_net", "close")
    pers_c  = calc_avg_cost(rows, "pers_net", "close")

    # 시가+종가 평균 기준
    inst_a  = calc_avg_cost(rows, "inst_net", "avg")
    fore_a  = calc_avg_cost(rows, "fore_net", "avg")
    pers_a  = calc_avg_cost(rows, "pers_net", "avg")

    def pct(cur, avg):
        if avg and avg > 0:
            return round((cur - avg) / avg * 100, 2)
        return None

    return {
        "ticker":       ticker,
        "name":         name,
        "last_date":    last["date"],
        "cur_price":    cur_close,
        "trading_days": len(rows),

        # 종가 기준 평균매입단가
        "close": {
            "inst":  {"avg_cost": inst_c["avg_cost"], "total_net": inst_c["total_net"],
                      "pct": pct(cur_close, inst_c["avg_cost"]), "daily_avg": inst_c["daily_avg"]},
            "fore":  {"avg_cost": fore_c["avg_cost"], "total_net": fore_c["total_net"],
                      "pct": pct(cur_close, fore_c["avg_cost"]), "daily_avg": fore_c["daily_avg"]},
            "pers":  {"avg_cost": pers_c["avg_cost"], "total_net": pers_c["total_net"],
                      "pct": pct(cur_close, pers_c["avg_cost"]), "daily_avg": pers_c["daily_avg"]},
        },

        # 시가+종가 평균 기준 평균매입단가
        "avg_price": {
            "inst":  {"avg_cost": inst_a["avg_cost"], "total_net": inst_a["total_net"],
                      "pct": pct(cur_close, inst_a["avg_cost"]), "daily_avg": inst_a["daily_avg"]},
            "fore":  {"avg_cost": fore_a["avg_cost"], "total_net": fore_a["total_net"],
                      "pct": pct(cur_close, fore_a["avg_cost"]), "daily_avg": fore_a["daily_avg"]},
            "pers":  {"avg_cost": pers_a["avg_cost"], "total_net": pers_a["total_net"],
                      "pct": pct(cur_close, pers_a["avg_cost"]), "daily_avg": pers_a["daily_avg"]},
        },

        # 일별 원시 데이터 (차트/테이블용)
        "daily": [
            {
                "date":     r["date"],
                "close":    r["close"],
                "avg":      r["avg"],
                "inst_net": r["inst_net"],
                "fore_net": r["fore_net"],
                "pers_net": r["pers_net"],
            }
            for r in rows
        ],
    }


def main():
    print(f"\n{'='*55}")
    print(f"  투자자별 매매 데이터 수집 시작")
    print(f"  수집 기간: {START_3M} ~ {TODAY}")
    print(f"  대상 종목: {len(WATCH_LIST)}개")
    print(f"{'='*55}\n")

    result = {
        "updated_at": datetime.now(KST).strftime("%Y-%m-%d %H:%M KST"),
        "period": {"start": START_3M, "end": TODAY},
        "stocks": {}
    }

    for ticker, name in WATCH_LIST.items():
        print(f"▶ {name} ({ticker}) 수집 중...")
        rows = fetch_krx_investor(ticker, START_3M, TODAY)

        if rows:
            summary = build_summary(ticker, name, rows)
            result["stocks"][ticker] = summary
            last = rows[-1]
            print(f"  ✅ {len(rows)}거래일 | 최근: {last['date']} | 종가: {last['close']:,}원")
        else:
            result["stocks"][ticker] = {
                "ticker": ticker, "name": name, "error": "데이터 수집 실패"
            }
            print(f"  ❌ 수집 실패")

        time.sleep(1.5)   # KRX 서버 부하 방지

    # data 디렉토리 생성
    os.makedirs("data", exist_ok=True)

    out_path = "data/investor_data.json"
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)

    print(f"\n{'='*55}")
    print(f"  ✅ 저장 완료: {out_path}")
    print(f"  수집 종목: {len(result['stocks'])}개")
    print(f"  업데이트: {result['updated_at']}")
    print(f"{'='*55}\n")


if __name__ == "__main__":
    main()
