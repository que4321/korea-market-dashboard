"""
collect_investor.py
requests 만으로 KRX 공개 API에서 투자자별 매매 데이터 수집
(외부 라이브러리 의존성 최소화)
저장: data/investor_data.json
"""

import requests
import json
import os
import time
import re
from datetime import datetime, timedelta
import pytz

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

KST   = pytz.timezone("Asia/Seoul")
NOW   = datetime.now(KST)
TODAY = NOW.strftime("%Y%m%d")
START = (NOW - timedelta(days=100)).strftime("%Y%m%d")

SESSION = requests.Session()
SESSION.headers.update({
    "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "ko-KR,ko;q=0.9",
    "Referer": "http://data.krx.co.kr/",
    "Origin":  "http://data.krx.co.kr",
})


def to_int(v):
    try:
        return int(str(v).replace(",", "").replace("+", "").strip())
    except:
        return 0


def fetch_krx_otp(bld: str, params: dict) -> str:
    """KRX OTP 발급"""
    r = SESSION.post(
        "http://data.krx.co.kr/comm/fileDn/GenerateOTP/generate.cmd",
        data={"locale": "ko_KR", "name": "fileDown",
              "url": bld, **params},
        timeout=15
    )
    return r.text.strip()


def fetch_krx_json(bld: str, params: dict) -> list:
    """KRX JSON API 직접 호출"""
    try:
        r = SESSION.post(
            "http://data.krx.co.kr/comm/bldAttendant/getJsonData.cmd",
            data={"bld": bld, "locale": "ko_KR", **params},
            timeout=20
        )
        return r.json().get("output", [])
    except Exception as e:
        print(f"    KRX JSON 오류: {e}")
        return []


def fetch_investor_krx(ticker: str) -> dict:
    """
    KRX: 투자자별 일별 매매현황 (MDCSTAT02302)
    기관합계/외국인/개인 순매수 수량 수집
    """
    params = {
        "ticker":    ticker,
        "fromdate":  START,
        "todate":    TODAY,
        "share":     "1",   # 주수 기준
        "money":     "1",
        "csvxls_isNo": "false",
    }
    items = fetch_krx_json("dbms/MDC/STAT/standard/MDCSTAT02302", params)

    result = {}
    for item in items:
        # 날짜 필드: TRD_DD (YYYY/MM/DD or YYYYMMDD)
        raw_date = str(item.get("TRD_DD", "")).replace("/", "-").replace(".", "-")
        if not raw_date or len(raw_date) < 8:
            continue
        if len(raw_date) == 8:  # YYYYMMDD
            raw_date = f"{raw_date[:4]}-{raw_date[4:6]}-{raw_date[6:]}"

        result[raw_date] = {
            "inst_net": to_int(item.get("INST_NETBID_TRDVOL",
                         item.get("INST_NET", 0))),
            "fore_net": to_int(item.get("FRGNR_NETBID_TRDVOL",
                         item.get("FRGNR_NET", 0))),
            "pers_net": to_int(item.get("INDV_NETBID_TRDVOL",
                         item.get("INDV_NET", 0))),
        }
    return result


def fetch_ohlcv_krx(ticker: str) -> dict:
    """
    KRX: 일별 OHLCV (MDCSTAT01701)
    """
    params = {
        "ticker":   ticker,
        "fromdate": START,
        "todate":   TODAY,
        "adjStkPrc_check": "Y",
        "adjStkPrc": "2",
        "csvxls_isNo": "false",
    }
    items = fetch_krx_json("dbms/MDC/STAT/standard/MDCSTAT01701", params)

    result = {}
    for item in items:
        raw_date = str(item.get("TRD_DD", "")).replace("/", "-").replace(".", "-")
        if not raw_date or len(raw_date) < 8:
            continue
        if len(raw_date) == 8:
            raw_date = f"{raw_date[:4]}-{raw_date[4:6]}-{raw_date[6:]}"

        close = to_int(item.get("TDD_CLSPRC", item.get("CLSPRC", 0)))
        open_ = to_int(item.get("TDD_OPNPRC", item.get("OPNPRC", close))) or close
        result[raw_date] = {
            "close": close,
            "open":  open_,
            "avg":   round((open_ + close) / 2),
        }
    return result


def fetch_naver_ohlcv(ticker: str) -> dict:
    """네이버 금융 OHLCV (KRX 실패 시 fallback)"""
    result = {}
    start_dt = datetime.strptime(START, "%Y%m%d")
    for page in range(1, 20):
        url = (f"https://finance.naver.com/item/sise_day.naver"
               f"?code={ticker}&page={page}")
        try:
            r = requests.get(url, headers={"User-Agent": "Mozilla/5.0",
                             "Referer": "https://finance.naver.com"},
                             timeout=10)
            r.encoding = "euc-kr"
            rows = re.findall(
                r'(\d{4}\.\d{2}\.\d{2})</span>.*?'
                r'<span[^>]*>([\d,]+)</span>.*?'  # 종가
                r'<span[^>]*>[^<]*</span>.*?'     # 전일비
                r'<span[^>]*>([\d,]+)</span>',    # 시가
                r.text, re.DOTALL
            )
            if not rows:
                break
            stop = False
            for row in rows:
                d = datetime.strptime(row[0], "%Y.%m.%d")
                if d < start_dt:
                    stop = True; break
                ds = d.strftime("%Y-%m-%d")
                cl = int(row[1].replace(",", ""))
                op = int(row[2].replace(",", "")) if row[2] else cl
                result[ds] = {"close": cl, "open": op,
                              "avg": round((op + cl) / 2)}
            if stop:
                break
            time.sleep(0.3)
        except Exception as e:
            print(f"    네이버 OHLCV page {page}: {e}"); break
    return result


def fetch_naver_foreign(ticker: str) -> dict:
    """네이버 금융 외국인 순매수 (fallback)"""
    result = {}
    start_dt = datetime.strptime(START, "%Y%m%d")
    for page in range(1, 16):
        url = (f"https://finance.naver.com/item/frgn.naver"
               f"?code={ticker}&page={page}")
        try:
            r = requests.get(url, headers={"User-Agent": "Mozilla/5.0",
                             "Referer": "https://finance.naver.com"},
                             timeout=10)
            r.encoding = "euc-kr"
            rows = re.findall(
                r'<td class="date">(\d{4}\.\d{2}\.\d{2})</td>'
                r'.*?<td[^>]*>\s*([\d,]+)\s*</td>'    # 종가
                r'.*?<td[^>]*>[^<]*</td>'              # 전일비
                r'.*?<td[^>]*>\s*([+-]?[\d,]*)\s*</td>',  # 외국인순매수
                r.text, re.DOTALL
            )
            if not rows:
                break
            stop = False
            for row in rows:
                d = datetime.strptime(row[0], "%Y.%m.%d")
                if d < start_dt:
                    stop = True; break
                ds = d.strftime("%Y-%m-%d")
                fn = to_int(row[2]) if row[2].strip() else 0
                result[ds] = {"fore_net": fn}
            if stop:
                break
            time.sleep(0.3)
        except Exception as e:
            print(f"    네이버 외국인 page {page}: {e}"); break
    return result


def calc_avg(rows, net_key, px_key):
    ca = cq = tot = 0
    daily = []
    for r in rows:
        net = r.get(net_key, 0)
        px  = r.get(px_key, r.get("close", 0))
        tot += net
        if net > 0:
            ca += net * px; cq += net
        daily.append(round(ca / cq) if cq else None)
    return {"avg_cost": round(ca/cq) if cq else None,
            "total_net": tot, "daily_avg": daily}


def build_summary(ticker, name, rows):
    if not rows:
        return {"ticker": ticker, "name": name, "error": "데이터 없음"}
    last = rows[-1]; cp = last["close"]
    def pct(a): return round((cp - a) / a * 100, 2) if a else None
    def sec(pk):
        i = calc_avg(rows, "inst_net", pk)
        f = calc_avg(rows, "fore_net", pk)
        p = calc_avg(rows, "pers_net", pk)
        return {
            "inst": {"avg_cost": i["avg_cost"], "total_net": i["total_net"],
                     "pct": pct(i["avg_cost"]), "daily_avg": i["daily_avg"]},
            "fore": {"avg_cost": f["avg_cost"], "total_net": f["total_net"],
                     "pct": pct(f["avg_cost"]), "daily_avg": f["daily_avg"]},
            "pers": {"avg_cost": p["avg_cost"], "total_net": p["total_net"],
                     "pct": pct(p["avg_cost"]), "daily_avg": p["daily_avg"]},
        }
    return {
        "ticker": ticker, "name": name,
        "last_date": last["date"], "cur_price": cp,
        "trading_days": len(rows),
        "close":     sec("close"),
        "avg_price": sec("avg"),
        "daily": rows,
    }


def main():
    print(f"\n{'='*50}")
    print(f"  투자자 데이터 수집  {START} ~ {TODAY}")
    print(f"  대상: {len(WATCH_LIST)}종목")
    print(f"{'='*50}\n")

    result = {
        "updated_at": NOW.strftime("%Y-%m-%d %H:%M KST"),
        "period": {"start": START, "end": TODAY},
        "stocks": {}
    }

    for ticker, name in WATCH_LIST.items():
        print(f"▶ {name} ({ticker})")

        # ── 1순위: KRX JSON API ──
        investor = fetch_krx_investor(ticker)
        time.sleep(1.0)
        ohlcv = fetch_ohlcv_krx(ticker)
        time.sleep(1.0)

        if investor and ohlcv:
            dates = sorted(set(investor) & set(ohlcv))
            rows = []
            for d in dates:
                o = ohlcv[d]; iv = investor[d]
                rows.append({
                    "date":     d,
                    "close":    o["close"],
                    "open":     o["open"],
                    "avg":      o["avg"],
                    "inst_net": iv["inst_net"],
                    "fore_net": iv["fore_net"],
                    "pers_net": iv["pers_net"],
                })
            print(f"  ✅ KRX: {len(rows)}거래일")
        else:
            # ── 2순위: 네이버 fallback ──
            print(f"  → KRX 실패, 네이버 금융 시도...")
            ohlcv   = fetch_naver_ohlcv(ticker)
            time.sleep(0.5)
            foreign = fetch_naver_foreign(ticker)
            time.sleep(0.5)

            dates = sorted(set(ohlcv))
            rows = []
            for d in dates:
                o  = ohlcv.get(d, {})
                fn = foreign.get(d, {}).get("fore_net", 0)
                rows.append({
                    "date":     d,
                    "close":    o.get("close", 0),
                    "open":     o.get("open", 0),
                    "avg":      o.get("avg", 0),
                    "inst_net": 0,
                    "fore_net": fn,
                    "pers_net": -fn,
                })
            print(f"  ⚠ 네이버 fallback: {len(rows)}거래일")

        summary = build_summary(ticker, name, rows)
        result["stocks"][ticker] = summary
        if rows:
            print(f"     {rows[-1]['date']} | {rows[-1]['close']:,}원")
        else:
            print(f"  ❌ 데이터 없음")

    os.makedirs("data", exist_ok=True)
    with open("data/investor_data.json", "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)
    print(f"\n✅ 저장 완료: data/investor_data.json | {result['updated_at']}\n")


if __name__ == "__main__":
    main()
