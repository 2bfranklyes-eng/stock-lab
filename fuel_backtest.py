# fuel_backtest.py — 실탄 F(t) 밴드가 '이후 수익률'을 예고하나 → fuel_backtest_stats
#   실탄은 주간(US)/월간(KR)이라, 각 실탄 날짜를 일간 지수에 매핑해 N'거래일' 뒤 수익률 계산.
#   가설: 실탄 풍부(자금 유입) 뒤 순풍? 아니면 극단(과열)은 오히려 역방향? — 상태 측정으로 확인.
import os
import sys
from dotenv import load_dotenv
import pandas as pd
from supabase import create_client

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

load_dotenv()
sb = create_client(os.environ["SUPABASE_URL"], os.environ["SUPABASE_SERVICE_KEY"])
ORDER = ["고갈", "부족", "중립", "여유", "풍부"]
PRICE_CODE = {"US": "us_index", "KR": "kr_index"}
HORIZONS = [5, 10, 20, 30, 60]


def fetch(table, sel, **eq):
    rows, step, start = [], 1000, 0
    while True:
        q = sb.table(table).select(sel)
        for k, v in eq.items():
            q = q.eq(k, v)
        r = q.order("dt").range(start, start + step - 1).execute().data
        rows += r
        if len(r) < step:
            break
        start += step
    return pd.DataFrame(rows)


def run(market):
    fuel = fetch("fuel_index", "dt,f_score,band", market=market)
    px = fetch("indicator_raw", "dt,value", market=market, code=PRICE_CODE[market])
    if fuel.empty or px.empty:
        print(f"[{market}] 데이터 부족 — 건너뜀\n")
        return
    px["dt"] = pd.to_datetime(px["dt"])
    px = px.drop_duplicates("dt").sort_values("dt").reset_index(drop=True)
    pv = px["value"].to_numpy()
    dts = px["dt"].to_numpy()
    fuel["dt"] = pd.to_datetime(fuel["dt"])

    # 표본 선택: 각 실탄 날짜 → 이후 첫 거래일 위치, 그 위치 기준 N거래일 뒤 수익률.
    #   US(주간)는 20거래일 창이 서로 겹치므로 '비겹침'(직전 선택과 20거래일↑ 간격)만 채택 → 독립 표본.
    #   KR(월간)은 표본 간격이 이미 ≈20거래일이라 전부 사용.
    STEP = 20
    recs_rows, last = [], -STEP
    for _, fr in fuel.iterrows():
        pos = int(dts.searchsorted(fr["dt"].to_datetime64()))
        if pos >= len(pv):
            continue
        if market == "US" and pos - last < STEP:
            continue                     # 직전 선택 표본과 20거래일 미만 → 창 겹침, 건너뜀
        last = pos
        row = {"band": fr["band"]}
        for h in HORIZONS:
            row[f"fwd{h}"] = (pv[pos + h] / pv[pos] - 1) if pos + h < len(pv) else None
        recs_rows.append(row)
    m = pd.DataFrame(recs_rows)

    print(f"[{market}] 실탄 밴드별 '이후 수익률' (진입 시점 실탄 → 이후 시장, {len(m)}개 시점):")

    def summ(label, d):
        r = {"밴드": label, "일수": len(d)}
        for h in HORIZONS:
            r[f"이후{h}"] = round(d[f"fwd{h}"].mean() * 100, 1)
        r["20승률"] = round((d["fwd20"] > 0).mean() * 100, 0)
        return r
    tbl = [summ(b, m[m["band"] == b]) for b in ORDER if len(m[m["band"] == b])]
    tbl.append(summ("── 전체", m))
    print(pd.DataFrame(tbl).to_string(index=False))

    # 적재 (delete→insert)
    recs = []
    for b in ORDER + ["전체"]:
        d = m if b == "전체" else m[m["band"] == b]
        if len(d) == 0:
            continue
        rec = {"market": market, "band": b, "n": int(len(d))}
        for h in HORIZONS:
            rec[f"fwd{h}"] = round(float(d[f"fwd{h}"].mean() * 100), 2)
            rec[f"hit{h}"] = round(float((d[f"fwd{h}"] > 0).mean() * 100), 1)
        recs.append(rec)
    sb.table("fuel_backtest_stats").delete().eq("market", market).execute()
    sb.table("fuel_backtest_stats").insert(recs).execute()
    print(f"[{market}] fuel_backtest_stats 적재 완료: {len(recs)}행\n")


if __name__ == "__main__":
    markets = [a.upper() for a in sys.argv[1:]] or ["US", "KR"]
    for m in markets:
        run(m)
