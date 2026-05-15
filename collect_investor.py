"""
collect_investor.py
로그인 없이 네이버 금융 API로 투자자별 매매 데이터 수집
- OHLCV: FinanceDataReader
- 투자자별 순매수: 네이버 금융 (로그인 불필요)
저장: data/investor_data.json
"""

import requests
import json
import os
import time
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

HEADERS = {
    "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Referer": "https://finance.naver.com",
}


def fetch_naver_investor(ticker: str) -> list:
    """
    네이버 금융 - 외국인/기관 일별 매매 동향
    https://finance.naver.com/item/frgn.naver?code=005930
    실제 데이터: sise_investor.naver (일별 투자자별 매매현황)
    """
    rows = []
    # 네이버 금융 투자자별 매매동향 API (페이지당 10건)
    for page in range(1, 15):   # 최대 14페이지 = 약 140거래일
        url = (
            f"https://finance.naver.com/item/frgn.naver"
            f"?code={ticker}&page={page}"
        )
        try:
            r = requests.get(url, headers=HEADERS, timeout=10)
            r.encoding = "euc-kr"
            html = r.text

            # 테이블 파싱 (정규식 없이 문자열 파싱)
            # 날짜 패턴: YYYY.MM.DD
            import re
            # 투자자별 매매동향 테이블 파싱
            pattern = re.compile(
                r'(\d{4}\.\d{2}\.\d{2})'           # 날짜
                r'.*?(\-?[\d,]+)'                   # 종가
                r'.*?(\-?[\d,]+)'                   # 전일비
                r'.*?(\-?[\d,]+)'                   # 외국인순매수
                r'.*?(\-?[\d,]+)'                   # 기관순매수
                , re.DOTALL
            )

            # 더 안정적인 방법: naver 전용 데이터 API 사용
            # /item/sise_investor.naver
            break
        except Exception as e:
            print(f"    페이지 {page} 오류: {e}")
            break
        time.sleep(0.3)

    return rows


def fetch_naver_investor_v2(ticker: str) -> dict:
    """
    네이버 금융 투자자별 매매동향 - JSON API 방식
    실질적으로 동작하는 엔드포인트 사용
    """
    result = {}
    
    for page in range(1, 16):
        url = f"https://finance.naver.com/item/frgn.naver?code={ticker}&page={page}"
        try:
            r = requests.get(url, headers=HEADERS, timeout=15)
            r.encoding = "euc-kr"
            html = r.text
            
            import re
            # 날짜 행 파싱
            # 네이버 금융 테이블 구조:
            # 날짜 | 종가 | 전일비 | 외국인순매수 | 외국인보유 | 외국인비중
            rows = re.findall(
                r'<td class="date">(\d{4}\.\d{2}\.\d{2})</td>'
                r'\s*<td[^>]*>\s*([\d,]+)\s*</td>'       # 종가
                r'(?:.*?<td[^>]*>.*?</td>){1}'            # 전일비
                r'\s*<td[^>]*>\s*([+-]?[\d,]*)\s*</td>'  # 외국인순매수
                , html, re.DOTALL
            )
            
            if not rows:
                break
                
            for row in rows:
                date_str = row[0].replace(".", "-")
                d = datetime.strptime(date_str, "%Y-%m-%d")
                if d < datetime.strptime(START, "%Y%m%d"):
                    return result
                    
                close = int(row[1].replace(",", "")) if row[1] else 0
                fore_net = int(row[2].replace(",", "").replace("+", "")) if row[2].strip() else 0
                
                result[date_str] = {
                    "close": close,
                    "fore_net": fore_net,
                }
            time.sleep(0.5)
        except Exception as e:
            print(f"    ⚠ {ticker} page {page}: {e}")
            break
    
    return result


def fetch_krx_investor_bulk(ticker: str) -> dict:
    """
    KRX 통계 API (공개 엔드포인트) - 투자자별 거래실적
    로그인 불필요한 공개 API
    """
    url = "http://data.krx.co.kr/comm/bldAttendant/getJsonData.cmd"
    
    params = {
        "bld": "dbms/MDC/STAT/standard/MDCSTAT02302",
        "locale": "ko_KR",
        "trdDd": TODAY,
        "share": "1",
        "money": "1",
        "csvxls_isNo": "false",
    }
    
    # 일별 투자자 데이터 페이로드
    payload = {
        "bld": "dbms/MDC/STAT/standard/MDCSTAT02302",
        "locale": "ko_KR",
        "ticker": ticker,
        "fromdate": START,
        "todate": TODAY,
        "share": "1",
        "money": "1",
        "csvxls_isNo": "false",
    }
    
    headers = {
        **HEADERS,
        "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
        "Origin": "http://data.krx.co.kr",
        "Referer": "http://data.krx.co.kr/contents/MDC/MDI/mdiLoader/index.cmd?menuId=MDC0201020402",
        "X-Requested-With": "XMLHttpRequest",
    }
    
    try:
        r = requests.post(url, data=payload, headers=headers, timeout=20)
        data = r.json()
        
        result = {}
        for item in data.get("output", []):
            date_str = item.get("TRD_DD", "").replace("/", "-")
            if not date_str:
                continue
            
            def to_int(v):
                try: return int(str(v).replace(",", "").replace("+", ""))
                except: return 0
            
            result[date_str] = {
                "close":    to_int(item.get("TDD_CLSPRC", 0)),
                "open":     to_int(item.get("TDD_OPNPRC", 0)),
                "inst_net": to_int(item.get("INST_NETBID_TRDVOL", 0)),
                "fore_net": to_int(item.get("FRGNR_NETBID_TRDVOL", 0)),
                "pers_net": to_int(item.get("INDV_NETBID_TRDVOL", 0)),
            }
        return result
    except Exception as e:
        print(f"    ⚠ KRX API ({ticker}): {e}")
        return {}


def fetch_fdr_ohlcv(ticker: str) -> dict:
    """FinanceDataReader로 OHLCV 수집"""
    try:
        import FinanceDataReader as fdr
        df = fdr.DataReader(ticker, START, TODAY)
        if df.empty:
            return {}
        result = {}
        for date, row in df.iterrows():
            d = date.strftime("%Y-%m-%d")
            close = int(row.get("Close", 0))
            open_ = int(row.get("Open", close))
            result[d] = {"close": close, "open": open_,
                         "avg": round((open_ + close) / 2)}
        return result
    except Exception as e:
        print(f"    ⚠ FDR OHLCV ({ticker}): {e}")
        return {}


def fetch_naver_ohlcv(ticker: str) -> dict:
    """네이버 금융으로 OHLCV 수집 (FDR 실패시 대체)"""
    result = {}
    for page in range(1, 20):
        url = f"https://finance.naver.com/item/sise_day.naver?code={ticker}&page={page}"
        try:
            import re
            r = requests.get(url, headers=HEADERS, timeout=10)
            r.encoding = "euc-kr"
            rows = re.findall(
                r'<td align="center"><span class="tah p10 gray03">(\d{4}\.\d{2}\.\d{2})</span></td>'
                r'\s*<td[^>]*><span[^>]*>([\d,]+)</span></td>'   # 종가
                r'\s*<td[^>]*><span[^>]*>[^<]*</span></td>'       # 전일비
                r'\s*<td[^>]*><span[^>]*>[^<]*</span></td>'       # 시가
                r'\s*<td[^>]*><span[^>]*>([\d,]+)</span></td>'   # 고가
                r'\s*<td[^>]*><span[^>]*>([\d,]+)</span></td>'   # 저가
                , r.text, re.DOTALL
            )
            if not rows:
                break
            for row in rows:
                date_str = row[0].replace(".", "-")
                d = datetime.strptime(date_str, "%Y-%m-%d")
                if d < datetime.strptime(START, "%Y%m%d"):
                    return result
                close = int(row[1].replace(",", ""))
                result[date_str] = {"close": close, "open": close,
                                    "avg": close}
            time.sleep(0.3)
        except Exception as e:
            break
    return result


def calc_avg(rows, net_key, px_key):
    ca = cq = tot = 0
    daily = []
    for r in rows:
        net = r.get(net_key, 0)
        px  = r.get(px_key, r.get("close", 0))
        tot += net
        if net > 0:
            ca += net * px
            cq += net
        daily.append(round(ca / cq) if cq else None)
    return {"avg_cost": round(ca/cq) if cq else None,
            "total_net": tot, "daily_avg": daily}


def build_summary(ticker, name, rows):
    if not rows:
        return {"ticker": ticker, "name": name, "error": "데이터 없음"}
    last = rows[-1]
    cp   = last["close"]
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

        # 1) KRX 공개 API 시도 (투자자+OHLCV 한번에)
        krx = fetch_krx_investor_bulk(ticker)
        time.sleep(1.0)

        if krx:
            rows = []
            for d in sorted(krx.keys()):
                item = krx[d]
                cl = item.get("close", 0)
                op = item.get("open", cl) or cl
                rows.append({
                    "date":     d,
                    "close":    cl,
                    "open":     op,
                    "avg":      round((op + cl) / 2),
                    "inst_net": item.get("inst_net", 0),
                    "fore_net": item.get("fore_net", 0),
                    "pers_net": item.get("pers_net", 0),
                })
            print(f"  ✅ KRX API: {len(rows)}거래일")
        else:
            # 2) FDR + 네이버 금융 조합 (fallback)
            print(f"  → KRX 실패, FinanceDataReader 시도...")
            ohlcv = fetch_fdr_ohlcv(ticker)
            if not ohlcv:
                ohlcv = fetch_naver_ohlcv(ticker)
            time.sleep(0.8)
            
            # 네이버 외국인 동향 (기관/개인은 추정)
            naver = fetch_naver_investor_v2(ticker)
            time.sleep(0.8)

            dates = sorted(set(ohlcv.keys()))
            rows = []
            for d in dates:
                o  = ohlcv.get(d, {})
                nv = naver.get(d, {})
                cl = o.get("close", 0)
                op = o.get("open", cl)
                fn = nv.get("fore_net", 0)
                rows.append({
                    "date":     d,
                    "close":    cl,
                    "open":     op,
                    "avg":      round((op + cl) / 2),
                    "inst_net": 0,    # 네이버에서 기관 개별 미제공
                    "fore_net": fn,
                    "pers_net": -fn,  # 개인 ≈ -외국인 (단순 추정)
                })
            print(f"  ⚠ FDR+네이버 fallback: {len(rows)}거래일 (기관 데이터 제한)")

        summary = build_summary(ticker, name, rows)
        result["stocks"][ticker] = summary
        if rows:
            print(f"     최근: {rows[-1]['date']} | 종가: {rows[-1]['close']:,}원")
        else:
            print(f"  ❌ 데이터 없음")

    os.makedirs("data", exist_ok=True)
    with open("data/investor_data.json", "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)
    print(f"\n✅ 저장 완료: data/investor_data.json")
    print(f"   업데이트: {result['updated_at']}\n")


if __name__ == "__main__":
    main()
