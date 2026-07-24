# liquidity_backtest.py — L(t) 유동성 밴드가 '이후 수익률'을 예고하는지 검증 (미국 + 한국)
# 가설: 완화(돈 풀림) 뒤엔 순풍(+), 긴축(돈 조임) 뒤엔 역풍(-) 이라는 순환매 성격이 있나?
#   심리(backtest.py)는 역발상(공포 뒤 반등)인데, 유동성은 순방향(완화 뒤 순풍) 가설이라 방향이 반대.
#   구조는 backtest.py 와 동일 — sentiment_daily 대신 liquidity_daily 밴드를 씀.
import os
import sys
from dotenv import load_dotenv
import pandas as pd
from supabase import create_client

try:  # 윈도우 콘솔(cp949)에서도 한글·기호 출력이 깨지지 않게
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

load_dotenv()
sb = create_client(os.environ["SUPABASE_URL"], os.environ["SUPABASE_SERVICE_KEY"])
ORDER = ["극단긴축", "긴축", "중립", "완화", "극단완화"]
PRICE_CODE = {"US": "us_index", "KR": "kr_index"}  # 시장 대표 지수 코드
HORIZONS = [5, 10, 20, 30, 60]  # 이후수익률 기간(거래일). 대시보드에서 토글 (20거래일 ≈ 1달)


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
    liq = fetch("liquidity_daily", "dt,l_score,band", market=market)
    px = fetch("indicator_raw", "dt,value", market=market, code=PRICE_CODE[market])
    if liq.empty or px.empty:
        print(f"[{market}] 데이터 부족 — 건너뜀\n")
        return
    liq["dt"] = pd.to_datetime(liq["dt"])
    px["dt"] = pd.to_datetime(px["dt"])
    m = liq.merge(px.rename(columns={"value": "px"}), on="dt").sort_values("dt").reset_index(drop=True)

    # 이후 수익률 (여러 기간)
    for h in HORIZONS:
        m[f"fwd{h}"] = m["px"].shift(-h) / m["px"] - 1

    print(f"[{market}] 기간: {m['dt'].min().date()} ~ {m['dt'].max().date()}  ({len(m)}일)")
    print(f"[{market}] L(t) 밴드별 '이후 수익률' (진입 시점 유동성 → 이후 시장):")

    def summary(label, d):
        row = {"밴드": label, "일수": len(d)}
        for h in HORIZONS:
            row[f"이후{h}일"] = round(d[f"fwd{h}"].mean() * 100, 1)
        row["20일승률"] = round((d["fwd20"] > 0).mean() * 100, 0)
        return row

    rows = [summary(b, m[m["band"] == b]) for b in ORDER if len(m[m["band"] == b])]
    rows.append(summary("── 전체평균", m))
    print(pd.DataFrame(rows).to_string(index=False))

    # 핵심: 극단완화 vs 극단긴축 스프레드 (유동성 순풍이 있으면 +)
    easy = m[m["band"] == "극단완화"]["fwd20"].mean() * 100
    tight = m[m["band"] == "극단긴축"]["fwd20"].mean() * 100
    verdict = "✅ 유동성 순풍 있음" if easy > tight else "❌ 순풍 없음/역방향"
    print(f"▶ [{market} 핵심] 극단완화 − 극단긴축 (이후 20일): {easy - tight:+.1f}%p  →  {verdict}")

    # ── 대시보드용: liquidity_backtest_stats 테이블에 적재 (기간별 fwd/hit 컬럼) ──
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
    sb.table("liquidity_backtest_stats").upsert(recs, on_conflict="market,band").execute()
    print(f"[{market}] liquidity_backtest_stats 적재 완료: {len(recs)}행\n")


if __name__ == "__main__":
    markets = [a.upper() for a in sys.argv[1:]] or ["US", "KR"]
    for m in markets:
        run(m)
