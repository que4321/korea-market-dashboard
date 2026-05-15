"""
collect_investor.py  v5
- KRX JSON API (1순위): 기관/외국인/개인 순매수 + OHLCV
- 네이버 금융 (fallback): 외국인 + 기관 동향 각각 수집
"""
import requests, json, os, time, re
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
START_DT = datetime.strptime(START, "%Y%m%d")

NAV_HDR = {
    "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/120.0.0.0 Safari/537.36",
    "Referer": "https://finance.naver.com",
    "Accept-Language": "ko-KR,ko;q=0.9",
}
KRX_HDR = {
    **NAV_HDR,
    "Origin":  "http://data.krx.co.kr",
    "Referer": "http://data.krx.co.kr/",
    "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
}

def to_int(v):
    try: return int(str(v).replace(",","").replace("+","").strip())
    except: return 0

def fmt_date(raw):
    d = str(raw).replace("/","-").replace(".","-").strip()
    if len(d) == 8 and "-" not in d:
        d = f"{d[:4]}-{d[4:6]}-{d[6:]}"
    return d if len(d) == 10 else ""

# ══════════════════════════════════════════
# 1순위: KRX JSON API
# ══════════════════════════════════════════
def krx_post(bld, params):
    try:
        r = requests.post(
            "http://data.krx.co.kr/comm/bldAttendant/getJsonData.cmd",
            data={"bld": bld, "locale": "ko_KR", **params},
            headers=KRX_HDR, timeout=20
        )
        data = r.json()
        return data.get("output", data.get("OutBlock_1", []))
    except Exception as e:
        print(f"    KRX 오류: {e}")
        return []

def get_krx_investor(ticker):
    items = krx_post("dbms/MDC/STAT/standard/MDCSTAT02302", {
        "ticker": ticker, "fromdate": START, "todate": TODAY,
        "share": "1", "money": "1", "csvxls_isNo": "false",
    })
    result = {}
    for item in items:
        d = fmt_date(item.get("TRD_DD",""))
        if not d: continue
        result[d] = {
            "inst_net": to_int(item.get("INST_NETBID_TRDVOL", item.get("INST_NET", 0))),
            "fore_net": to_int(item.get("FRGNR_NETBID_TRDVOL", item.get("FRGNR_NET", 0))),
            "pers_net": to_int(item.get("INDV_NETBID_TRDVOL", item.get("INDV_NET", 0))),
        }
    return result

def get_krx_ohlcv(ticker):
    items = krx_post("dbms/MDC/STAT/standard/MDCSTAT01701", {
        "ticker": ticker, "fromdate": START, "todate": TODAY,
        "adjStkPrc_check": "Y", "adjStkPrc": "2", "csvxls_isNo": "false",
    })
    result = {}
    for item in items:
        d = fmt_date(item.get("TRD_DD",""))
        if not d: continue
        cl = to_int(item.get("TDD_CLSPRC", item.get("CLSPRC", 0)))
        op = to_int(item.get("TDD_OPNPRC", item.get("OPNPRC", cl))) or cl
        result[d] = {"close": cl, "open": op, "avg": round((op+cl)/2)}
    return result

# ══════════════════════════════════════════
# 2순위: 네이버 금융 (OHLCV + 외국인 + 기관)
# ══════════════════════════════════════════
def nav_get(url):
    r = requests.get(url, headers=NAV_HDR, timeout=12)
    r.encoding = "euc-kr"
    return r.text

def get_naver_ohlcv(ticker):
    result = {}
    for page in range(1, 22):
        try:
            html = nav_get(f"https://finance.naver.com/item/sise_day.naver?code={ticker}&page={page}")
            rows = re.findall(
                r'(\d{4}\.\d{2}\.\d{2})</span>\s*</td>'
                r'.*?<span[^>]*>([\d,]+)</span>'   # 종가
                r'.*?<span[^>]*>[^<]*</span>'       # 전일비
                r'.*?<span[^>]*>([\d,]+)</span>',  # 시가
                html, re.DOTALL)
            if not rows: break
            stop = False
            for row in rows:
                dt = datetime.strptime(row[0], "%Y.%m.%d")
                if dt < START_DT: stop = True; break
                ds = dt.strftime("%Y-%m-%d")
                cl = int(row[1].replace(",",""))
                op = int(row[2].replace(",","")) if row[2] else cl
                result[ds] = {"close":cl, "open":op, "avg":round((op+cl)/2)}
            if stop: break
            time.sleep(0.25)
        except Exception as e:
            print(f"    OHLCV page{page}: {e}"); break
    return result

def get_naver_foreign(ticker):
    """네이버 외국인 순매수"""
    result = {}
    for page in range(1, 18):
        try:
            html = nav_get(f"https://finance.naver.com/item/frgn.naver?code={ticker}&page={page}")
            rows = re.findall(
                r'<td class="date">(\d{4}\.\d{2}\.\d{2})</td>'
                r'.*?<td[^>]*>\s*[\d,]+\s*</td>'      # 종가
                r'.*?<td[^>]*>[^<]*</td>'              # 전일비
                r'.*?<td[^>]*>\s*([+-]?[\d,]*)\s*</td>',  # 외국인순매수
                html, re.DOTALL)
            if not rows: break
            stop = False
            for row in rows:
                dt = datetime.strptime(row[0], "%Y.%m.%d")
                if dt < START_DT: stop = True; break
                ds = dt.strftime("%Y-%m-%d")
                result[ds] = to_int(row[1]) if row[1].strip() else 0
            if stop: break
            time.sleep(0.25)
        except Exception as e:
            print(f"    외국인 page{page}: {e}"); break
    return result

def get_naver_institution(ticker):
    """네이버 기관 순매수 (기관종합 탭)"""
    result = {}
    for page in range(1, 18):
        try:
            html = nav_get(
                f"https://finance.naver.com/item/sise_investor.naver?code={ticker}&page={page}")
            # 날짜 | 기관합계순매수 | 외국인순매수 | 개인순매수
            rows = re.findall(
                r'<td class="date">(\d{4}\.\d{2}\.\d{2})</td>'
                r'.*?<td[^>]*>\s*([+-]?[\d,]+)\s*</td>'  # 기관합계순매수
                r'.*?<td[^>]*>\s*([+-]?[\d,]+)\s*</td>'  # 외국인순매수
                r'.*?<td[^>]*>\s*([+-]?[\d,]+)\s*</td>', # 개인순매수
                html, re.DOTALL)
            if not rows: break
            stop = False
            for row in rows:
                dt = datetime.strptime(row[0], "%Y.%m.%d")
                if dt < START_DT: stop = True; break
                ds = dt.strftime("%Y-%m-%d")
                result[ds] = {
                    "inst_net": to_int(row[1]),
                    "fore_net": to_int(row[2]),
                    "pers_net": to_int(row[3]),
                }
            if stop: break
            time.sleep(0.25)
        except Exception as e:
            print(f"    기관 page{page}: {e}"); break
    return result

# ══════════════════════════════════════════
# 계산 및 요약
# ══════════════════════════════════════════
def calc_avg(rows, net_key, px_key):
    ca=cq=tot=0; daily=[]
    for r in rows:
        net=r.get(net_key,0); px=r.get(px_key, r.get("close",0))
        tot+=net
        if net>0: ca+=net*px; cq+=net
        daily.append(round(ca/cq) if cq else None)
    return {"avg_cost":round(ca/cq) if cq else None,
            "total_net":tot, "daily_avg":daily}

def build_summary(ticker, name, rows):
    if not rows:
        return {"ticker":ticker,"name":name,"error":"데이터 없음"}
    last=rows[-1]; cp=last["close"]
    def pct(a): return round((cp-a)/a*100,2) if a else None
    def sec(pk):
        i=calc_avg(rows,"inst_net",pk); f=calc_avg(rows,"fore_net",pk); p=calc_avg(rows,"pers_net",pk)
        return {
            "inst":{"avg_cost":i["avg_cost"],"total_net":i["total_net"],"pct":pct(i["avg_cost"]),"daily_avg":i["daily_avg"]},
            "fore":{"avg_cost":f["avg_cost"],"total_net":f["total_net"],"pct":pct(f["avg_cost"]),"daily_avg":f["daily_avg"]},
            "pers":{"avg_cost":p["avg_cost"],"total_net":p["total_net"],"pct":pct(p["avg_cost"]),"daily_avg":p["daily_avg"]},
        }
    return {
        "ticker":ticker,"name":name,
        "last_date":last["date"],"cur_price":cp,
        "trading_days":len(rows),
        "close":sec("close"),"avg_price":sec("avg"),
        "daily":rows,
    }

# ══════════════════════════════════════════
# 메인
# ══════════════════════════════════════════
def main():
    print(f"\n{'='*52}\n  📈 투자자 매입단가 수집  {START}~{TODAY}\n{'='*52}\n")
    result = {
        "updated_at": NOW.strftime("%Y-%m-%d %H:%M KST"),
        "period": {"start":START,"end":TODAY},
        "stocks": {}
    }

    for ticker, name in WATCH_LIST.items():
        print(f"▶ {name} ({ticker})")

        # ── 1순위: KRX JSON API ──
        krx_inv  = get_krx_investor(ticker); time.sleep(1.0)
        krx_ohlcv = get_krx_ohlcv(ticker);  time.sleep(1.0)

        if krx_inv and krx_ohlcv:
            dates = sorted(set(krx_inv) & set(krx_ohlcv))
            rows = [{
                "date":d,
                "close":krx_ohlcv[d]["close"], "open":krx_ohlcv[d]["open"],
                "avg":krx_ohlcv[d]["avg"],
                "inst_net":krx_inv[d]["inst_net"],
                "fore_net":krx_inv[d]["fore_net"],
                "pers_net":krx_inv[d]["pers_net"],
            } for d in dates]
            src = "KRX"
        else:
            # ── 2순위: 네이버 금융 ──
            print(f"  → KRX 실패, 네이버 수집 중...")
            ohlcv = get_naver_ohlcv(ticker);         time.sleep(0.4)
            inv   = get_naver_institution(ticker);   time.sleep(0.4)

            dates = sorted(set(ohlcv))
            rows = []
            for d in dates:
                o  = ohlcv[d]
                iv = inv.get(d, {"inst_net":0,"fore_net":0,"pers_net":0})
                rows.append({
                    "date":d,
                    "close":o["close"], "open":o["open"], "avg":o["avg"],
                    "inst_net":iv["inst_net"],
                    "fore_net":iv["fore_net"],
                    "pers_net":iv["pers_net"],
                })
            src = "네이버"

        result["stocks"][ticker] = build_summary(ticker, name, rows)
        if rows:
            r = rows[-1]
            print(f"  ✅ [{src}] {len(rows)}거래일 | {r['date']} | {r['close']:,}원 "
                  f"| 기관:{r['inst_net']:+,} 외국인:{r['fore_net']:+,} 개인:{r['pers_net']:+,}")
        else:
            print(f"  ❌ 데이터 없음")

    os.makedirs("data", exist_ok=True)
    with open("data/investor_data.json","w",encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)
    print(f"\n✅ 저장 완료: data/investor_data.json | {result['updated_at']}\n")

if __name__ == "__main__":
    main()
