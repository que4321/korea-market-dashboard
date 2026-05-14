"""
collect_investor.py  —  pykrx 기반 투자자별 매매 데이터 수집
저장: data/investor_data.json
"""
from pykrx import stock
import json, os, time
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


def fetch_ohlcv(ticker):
    try:
        df = stock.get_market_ohlcv(START, TODAY, ticker)
        if df.empty:
            return {}
        result = {}
        for date, row in df.iterrows():
            cols = {str(c): c for c in row.index}
            close_col = next((v for k,v in cols.items() if '종가' in k or 'Close' in k), None)
            open_col  = next((v for k,v in cols.items() if '시가' in k or 'Open' in k), None)
            close = int(row[close_col]) if close_col is not None else 0
            open_ = int(row[open_col])  if open_col  is not None else close
            result[date.strftime("%Y-%m-%d")] = {"open": open_, "close": close}
        return result
    except Exception as e:
        print(f"  ⚠ OHLCV({ticker}): {e}")
        return {}


def fetch_investor(ticker):
    try:
        df = stock.get_market_trading_volume_by_investor(START, TODAY, ticker)
        if df.empty:
            return {}
        result = {}
        for date, row in df.iterrows():
            cols = list(row.index)
            def get_net(keyword):
                # 순매수 컬럼 탐색
                for c in cols:
                    if keyword in str(c) and '순매수' in str(c):
                        v = row[c]
                        return int(v) if v == v else 0
                # 없으면 매수-매도
                buy = sell = 0
                for c in cols:
                    cs = str(c)
                    if keyword in cs and '매수' in cs and '순' not in cs:
                        v = row[c]; buy = int(v) if v == v else 0
                    if keyword in cs and '매도' in cs and '순' not in cs:
                        v = row[c]; sell = int(v) if v == v else 0
                return buy - sell
            result[date.strftime("%Y-%m-%d")] = {
                "inst_net": get_net("기관"),
                "fore_net": get_net("외국인"),
                "pers_net": get_net("개인"),
            }
        return result
    except Exception as e:
        print(f"  ⚠ 투자자({ticker}): {e}")
        return {}


def calc_avg(rows, net_key, px_key):
    ca = cq = tot = 0
    daily = []
    for r in rows:
        net = r[net_key]; px = r[px_key]; tot += net
        if net > 0: ca += net * px; cq += net
        daily.append(round(ca/cq) if cq else None)
    return {"avg_cost": round(ca/cq) if cq else None,
            "total_net": tot, "daily_avg": daily}


def build_summary(ticker, name, rows):
    if not rows:
        return {"ticker": ticker, "name": name, "error": "데이터 없음"}
    last = rows[-1]; cp = last["close"]
    def pct(a): return round((cp-a)/a*100,2) if a else None
    def sec(pk):
        i=calc_avg(rows,"inst_net",pk); f=calc_avg(rows,"fore_net",pk); p=calc_avg(rows,"pers_net",pk)
        return {
            "inst":{"avg_cost":i["avg_cost"],"total_net":i["total_net"],"pct":pct(i["avg_cost"]),"daily_avg":i["daily_avg"]},
            "fore":{"avg_cost":f["avg_cost"],"total_net":f["total_net"],"pct":pct(f["avg_cost"]),"daily_avg":f["daily_avg"]},
            "pers":{"avg_cost":p["avg_cost"],"total_net":p["total_net"],"pct":pct(p["avg_cost"]),"daily_avg":p["daily_avg"]},
        }
    return {
        "ticker": ticker, "name": name,
        "last_date": last["date"], "cur_price": cp,
        "trading_days": len(rows),
        "close":     sec("close"),
        "avg_price": sec("avg"),
        "daily": [{"date":r["date"],"close":r["close"],"open":r["open"],"avg":r["avg"],
                   "inst_net":r["inst_net"],"fore_net":r["fore_net"],"pers_net":r["pers_net"]} for r in rows],
    }


def main():
    print(f"\n{'='*50}\n  pykrx 투자자 데이터 수집  {START}~{TODAY}\n{'='*50}\n")
    result = {"updated_at": NOW.strftime("%Y-%m-%d %H:%M KST"),
              "period": {"start":START,"end":TODAY}, "stocks":{}}

    for ticker, name in WATCH_LIST.items():
        print(f"▶ {name} ({ticker})")
        ohlcv = fetch_ohlcv(ticker);  time.sleep(0.8)
        inv   = fetch_investor(ticker); time.sleep(0.8)

        dates = sorted(set(ohlcv) & set(inv))
        rows  = []
        for d in dates:
            o=ohlcv[d]; iv=inv[d]
            cl=o["close"]; op=o["open"] if o["open"]>0 else cl
            rows.append({"date":d,"close":cl,"open":op,"avg":round((op+cl)/2),
                         "inst_net":iv["inst_net"],"fore_net":iv["fore_net"],"pers_net":iv["pers_net"]})

        summary = build_summary(ticker, name, rows)
        result["stocks"][ticker] = summary
        if rows:
            print(f"  ✅ {len(rows)}거래일 | {rows[-1]['date']} | {rows[-1]['close']:,}원")
        else:
            print(f"  ❌ 데이터 없음")

    os.makedirs("data", exist_ok=True)
    with open("data/investor_data.json","w",encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)
    print(f"\n✅ 저장: data/investor_data.json | {result['updated_at']}\n")

if __name__ == "__main__":
    main()
