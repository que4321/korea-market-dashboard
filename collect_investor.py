"""
collect_investor.py  v4
requests + pytz 만 사용. 외부 라이브러리 없음.
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

HDR = {
    "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/120.0.0.0 Safari/537.36",
    "Referer": "https://finance.naver.com",
}

def to_int(v):
    try: return int(str(v).replace(",","").replace("+","").strip())
    except: return 0

# ── KRX JSON API ──────────────────────────────────────────
def krx_json(bld, params):
    try:
        r = requests.post(
            "http://data.krx.co.kr/comm/bldAttendant/getJsonData.cmd",
            data={"bld": bld, "locale": "ko_KR", **params},
            headers={**HDR, "Origin": "http://data.krx.co.kr",
                     "Referer": "http://data.krx.co.kr/"},
            timeout=20
        )
        return r.json().get("output", [])
    except Exception as e:
        print(f"    KRX 오류: {e}")
        return []

def get_investor_krx(ticker):
    items = krx_json("dbms/MDC/STAT/standard/MDCSTAT02302", {
        "ticker": ticker, "fromdate": START, "todate": TODAY,
        "share": "1", "money": "1", "csvxls_isNo": "false",
    })
    result = {}
    for item in items:
        d = str(item.get("TRD_DD","")).replace("/","-").replace(".","-")
        if len(d)==8: d = f"{d[:4]}-{d[4:6]}-{d[6:]}"
        if not d: continue
        result[d] = {
            "inst_net": to_int(item.get("INST_NETBID_TRDVOL", item.get("INST_NET",0))),
            "fore_net": to_int(item.get("FRGNR_NETBID_TRDVOL", item.get("FRGNR_NET",0))),
            "pers_net": to_int(item.get("INDV_NETBID_TRDVOL", item.get("INDV_NET",0))),
        }
    return result

def get_ohlcv_krx(ticker):
    items = krx_json("dbms/MDC/STAT/standard/MDCSTAT01701", {
        "ticker": ticker, "fromdate": START, "todate": TODAY,
        "adjStkPrc_check": "Y", "adjStkPrc": "2", "csvxls_isNo": "false",
    })
    result = {}
    for item in items:
        d = str(item.get("TRD_DD","")).replace("/","-").replace(".","-")
        if len(d)==8: d = f"{d[:4]}-{d[4:6]}-{d[6:]}"
        if not d: continue
        cl = to_int(item.get("TDD_CLSPRC", item.get("CLSPRC",0)))
        op = to_int(item.get("TDD_OPNPRC", item.get("OPNPRC",cl))) or cl
        result[d] = {"close": cl, "open": op, "avg": round((op+cl)/2)}
    return result

# ── 네이버 fallback ────────────────────────────────────────
def get_ohlcv_naver(ticker):
    result = {}
    start_dt = datetime.strptime(START, "%Y%m%d")
    for page in range(1, 20):
        try:
            r = requests.get(
                f"https://finance.naver.com/item/sise_day.naver?code={ticker}&page={page}",
                headers=HDR, timeout=10)
            r.encoding = "euc-kr"
            rows = re.findall(
                r'(\d{4}\.\d{2}\.\d{2})</span>.*?'
                r'<span[^>]*>([\d,]+)</span>.*?'
                r'<span[^>]*>[^<]*</span>.*?'
                r'<span[^>]*>([\d,]+)</span>',
                r.text, re.DOTALL)
            if not rows: break
            stop = False
            for row in rows:
                d = datetime.strptime(row[0], "%Y.%m.%d")
                if d < start_dt: stop=True; break
                ds = d.strftime("%Y-%m-%d")
                cl = int(row[1].replace(",",""))
                op = int(row[2].replace(",","")) if row[2] else cl
                result[ds] = {"close":cl,"open":op,"avg":round((op+cl)/2)}
            if stop: break
            time.sleep(0.3)
        except: break
    return result

def get_foreign_naver(ticker):
    result = {}
    start_dt = datetime.strptime(START, "%Y%m%d")
    for page in range(1, 16):
        try:
            r = requests.get(
                f"https://finance.naver.com/item/frgn.naver?code={ticker}&page={page}",
                headers=HDR, timeout=10)
            r.encoding = "euc-kr"
            rows = re.findall(
                r'<td class="date">(\d{4}\.\d{2}\.\d{2})</td>'
                r'.*?<td[^>]*>\s*([\d,]+)\s*</td>'
                r'.*?<td[^>]*>[^<]*</td>'
                r'.*?<td[^>]*>\s*([+-]?[\d,]*)\s*</td>',
                r.text, re.DOTALL)
            if not rows: break
            stop = False
            for row in rows:
                d = datetime.strptime(row[0], "%Y.%m.%d")
                if d < start_dt: stop=True; break
                ds = d.strftime("%Y-%m-%d")
                fn = to_int(row[2]) if row[2].strip() else 0
                result[ds] = {"fore_net": fn}
            if stop: break
            time.sleep(0.3)
        except: break
    return result

# ── 계산 ──────────────────────────────────────────────────
def calc_avg(rows, net_key, px_key):
    ca=cq=tot=0; daily=[]
    for r in rows:
        net=r.get(net_key,0); px=r.get(px_key, r.get("close",0))
        tot+=net
        if net>0: ca+=net*px; cq+=net
        daily.append(round(ca/cq) if cq else None)
    return {"avg_cost": round(ca/cq) if cq else None,
            "total_net": tot, "daily_avg": daily}

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

# ── 메인 ──────────────────────────────────────────────────
def main():
    print(f"\n{'='*50}\n  투자자 데이터 수집  {START}~{TODAY}\n{'='*50}\n")
    result = {
        "updated_at": NOW.strftime("%Y-%m-%d %H:%M KST"),
        "period": {"start":START,"end":TODAY},
        "stocks": {}
    }

    for ticker, name in WATCH_LIST.items():
        print(f"▶ {name} ({ticker})")

        # 1순위: KRX
        inv  = get_investor_krx(ticker); time.sleep(1.0)
        ohlcv = get_ohlcv_krx(ticker);   time.sleep(1.0)

        if inv and ohlcv:
            dates = sorted(set(inv) & set(ohlcv))
            rows = [{
                "date":d, "close":ohlcv[d]["close"], "open":ohlcv[d]["open"],
                "avg":ohlcv[d]["avg"], "inst_net":inv[d]["inst_net"],
                "fore_net":inv[d]["fore_net"], "pers_net":inv[d]["pers_net"],
            } for d in dates]
            print(f"  ✅ KRX {len(rows)}거래일")
        else:
            # 2순위: 네이버
            print(f"  → 네이버 fallback")
            ohlcv  = get_ohlcv_naver(ticker);   time.sleep(0.5)
            foreign = get_foreign_naver(ticker); time.sleep(0.5)
            rows = []
            for d in sorted(ohlcv):
                o=ohlcv[d]; fn=foreign.get(d,{}).get("fore_net",0)
                rows.append({"date":d,"close":o["close"],"open":o["open"],
                             "avg":o["avg"],"inst_net":0,"fore_net":fn,"pers_net":-fn})
            print(f"  ⚠ 네이버 {len(rows)}거래일")

        result["stocks"][ticker] = build_summary(ticker, name, rows)
        if rows: print(f"     {rows[-1]['date']} | {rows[-1]['close']:,}원")
        else: print(f"  ❌ 없음")

    os.makedirs("data", exist_ok=True)
    with open("data/investor_data.json","w",encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)
    print(f"\n✅ 저장: data/investor_data.json | {result['updated_at']}\n")

if __name__ == "__main__":
    main()
