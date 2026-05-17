"""
collect_investor.py  v8
- OHLCV: yfinance (auto_adjust=False → 실제 주가 사용)
- 투자자별 순매수: KRX OTP+CSV
"""
import requests, json, os, time, re, csv, io
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
    "002960": "한국쉘석유",
}

KST   = pytz.timezone("Asia/Seoul")
NOW   = datetime.now(KST)
TODAY = NOW.strftime("%Y%m%d")
START = (NOW - timedelta(days=100)).strftime("%Y%m%d")

def to_int(v):
    try: return int(str(v).replace(",","").replace("+","").strip())
    except: return 0

def fmt_date(raw):
    d = str(raw).replace("/","-").replace(".","-").strip()
    if len(d) == 8 and "-" not in d:
        d = f"{d[:4]}-{d[4:6]}-{d[6:]}"
    return d if len(d) == 10 else ""

# ══════════════════════════════════════════
# OHLCV: yfinance (auto_adjust=False)
# ══════════════════════════════════════════
def get_ohlcv_yf(ticker):
    try:
        import yfinance as yf
        symbol = ticker + ".KS"
        start_str = f"{START[:4]}-{START[4:6]}-{START[6:]}"
        end_str   = f"{TODAY[:4]}-{TODAY[4:6]}-{TODAY[6:]}"

        # auto_adjust=False → 실제 거래 주가 사용
        df = yf.download(symbol, start=start_str, end=end_str,
                         progress=False, auto_adjust=False)
        if df is None or df.empty:
            print(f"    yfinance: 데이터 없음")
            return {}

        # MultiIndex 컬럼 처리
        if hasattr(df.columns, 'levels'):
            df.columns = [col[0] if isinstance(col, tuple) else col
                         for col in df.columns]

        result = {}
        for idx in df.index:
            d = idx.strftime("%Y-%m-%d")
            try:
                cl_val = df.loc[idx, "Close"]
                op_val = df.loc[idx, "Open"]
                if hasattr(cl_val, 'item'): cl_val = cl_val.item()
                if hasattr(op_val, 'item'): op_val = op_val.item()
                cl = int(float(cl_val)) if cl_val == cl_val else 0
                op = int(float(op_val)) if op_val == op_val else cl
                if cl > 0:
                    result[d] = {"close": cl, "open": op,
                                 "avg": round((op+cl)/2)}
            except:
                continue

        print(f"    yfinance: {len(result)}거래일 | 최근종가: {list(result.values())[-1]['close']:,}원")
        return result
    except Exception as e:
        print(f"    yfinance 오류: {e}")
        return {}

# ══════════════════════════════════════════
# 투자자 순매수: KRX OTP + CSV
# ══════════════════════════════════════════
def get_krx_session():
    s = requests.Session()
    s.headers.update({
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                      "AppleWebKit/537.36 Chrome/124.0.0.0 Safari/537.36",
        "Accept-Language": "ko-KR,ko;q=0.9",
        "Accept": "text/html,application/xhtml+xml,*/*;q=0.8",
    })
    try:
        s.get("http://data.krx.co.kr/contents/MDC/MDI/mdiLoader/"
              "index.cmd?menuId=MDC0201020402", timeout=12)
        time.sleep(0.5)
    except:
        pass
    return s

KRX_SESSION = None

def get_investor_krx_csv(ticker):
    global KRX_SESSION
    if KRX_SESSION is None:
        KRX_SESSION = get_krx_session()

    try:
        otp_r = KRX_SESSION.post(
            "http://data.krx.co.kr/comm/fileDn/GenerateOTP/generate.cmd",
            data={
                "locale": "ko_KR", "ticker": ticker,
                "fromdate": START, "todate": TODAY,
                "share": "1", "money": "1",
                "csvxls_isNo": "false", "name": "fileDown",
                "url": "dbms/MDC/STAT/standard/MDCSTAT02302",
            },
            headers={
                "Referer": "http://data.krx.co.kr/contents/MDC/MDI/mdiLoader/"
                           "index.cmd?menuId=MDC0201020402",
                "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
                "X-Requested-With": "XMLHttpRequest",
            },
            timeout=15
        )
        otp = otp_r.text.strip()
        if not otp or len(otp) > 200:
            print(f"    KRX OTP 실패: {otp[:60]}")
            return {}
    except Exception as e:
        print(f"    KRX OTP 오류: {e}")
        return {}

    try:
        csv_r = KRX_SESSION.post(
            "http://data.krx.co.kr/comm/fileDn/download_csv/download.cmd",
            data={"code": otp},
            headers={"Referer": "http://data.krx.co.kr/"},
            timeout=20
        )
        csv_r.encoding = "euc-kr"
        raw = csv_r.text.strip()
        if not raw or len(raw) < 10:
            return {}
    except Exception as e:
        print(f"    KRX CSV 오류: {e}")
        return {}

    result = {}
    try:
        reader = csv.DictReader(io.StringIO(raw))
        for row in reader:
            keys = {k.strip(): v for k, v in row.items()}
            raw_date = (keys.get("일자") or keys.get("날짜") or
                        keys.get("TRD_DD") or "")
            d = fmt_date(raw_date)
            if not d:
                continue

            def find(patterns):
                for p in patterns:
                    for k, v in keys.items():
                        if p in k:
                            return to_int(v)
                return 0

            result[d] = {
                "inst_net": find(["기관 합계","기관합계","기관_합계","INST_NET"]),
                "fore_net": find(["외국인 합계","외국인합계","외국인_합계","FRGNR_NET"]),
                "pers_net": find(["개인","INDV_NET"]),
            }
        print(f"    KRX CSV: {len(result)}거래일")
    except Exception as e:
        print(f"    CSV 파싱 오류: {e}")
        return {}

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
        i=calc_avg(rows,"inst_net",pk)
        f=calc_avg(rows,"fore_net",pk)
        p=calc_avg(rows,"pers_net",pk)
        return {
            "inst":{"avg_cost":i["avg_cost"],"total_net":i["total_net"],
                    "pct":pct(i["avg_cost"]),"daily_avg":i["daily_avg"]},
            "fore":{"avg_cost":f["avg_cost"],"total_net":f["total_net"],
                    "pct":pct(f["avg_cost"]),"daily_avg":f["daily_avg"]},
            "pers":{"avg_cost":p["avg_cost"],"total_net":p["total_net"],
                    "pct":pct(p["avg_cost"]),"daily_avg":p["daily_avg"]},
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
    print(f"\n{'='*52}")
    print(f"  📈 투자자 매입단가 수집  {START}~{TODAY}")
    print(f"{'='*52}\n")
    result = {
        "updated_at": NOW.strftime("%Y-%m-%d %H:%M KST"),
        "period": {"start":START,"end":TODAY},
        "stocks": {}
    }

    for ticker, name in WATCH_LIST.items():
        print(f"▶ {name} ({ticker})")
        ohlcv = get_ohlcv_yf(ticker);          time.sleep(0.5)
        inv   = get_investor_krx_csv(ticker);  time.sleep(1.0)

        if ohlcv and inv:
            dates = sorted(set(ohlcv) & set(inv))
            rows = [{
                "date":d,
                "close":ohlcv[d]["close"], "open":ohlcv[d]["open"],
                "avg":ohlcv[d]["avg"],
                "inst_net":inv[d]["inst_net"],
                "fore_net":inv[d]["fore_net"],
                "pers_net":inv[d]["pers_net"],
            } for d in dates]
            src = "yfinance+KRX"
        elif ohlcv:
            rows = [{"date":d,"close":o["close"],"open":o["open"],"avg":o["avg"],
                     "inst_net":0,"fore_net":0,"pers_net":0}
                    for d,o in sorted(ohlcv.items())]
            src = "yfinance전용"
        else:
            rows=[]; src="실패"

        result["stocks"][ticker] = build_summary(ticker, name, rows)
        if rows:
            r = rows[-1]
            print(f"  ✅ [{src}] {len(rows)}거래일 | {r['date']} | "
                  f"{r['close']:,}원 | 기관:{r['inst_net']:+,} "
                  f"외:{r['fore_net']:+,} 개:{r['pers_net']:+,}")
        else:
            print(f"  ❌ 데이터 없음")

    os.makedirs("data", exist_ok=True)
    with open("data/investor_data.json","w",encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)
    print(f"\n✅ 저장: data/investor_data.json | {result['updated_at']}\n")

if __name__ == "__main__":
    main()
