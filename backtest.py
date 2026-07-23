# backtest.py — S(t) 심리 밴드가 '이후 수익률'을 예고하는지 검증 (미국 + 한국)
# 가설: 극단공포 뒤엔 반등(+), 극단탐욕 뒤엔 조정(-) 이라는 역발상 엣지가 있나?
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
ORDER = ["극단공포", "공포", "중립", "탐욕", "극단탐욕"]
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
    sent = fetch("sentiment_daily", "dt,s_score,band", market=market)
    px = fetch("indicator_raw", "dt,value", market=market, code=PRICE_CODE[market])
    if sent.empty or px.empty:
        print(f"[{market}] 데이터 부족 — 건너뜀\n")
        return
    sent["dt"] = pd.to_datetime(sent["dt"])
    px["dt"] = pd.to_datetime(px["dt"])
    m = sent.merge(px.rename(columns={"value": "px"}), on="dt").sort_values("dt").reset_index(drop=True)

    # 이후 수익률 (여러 기간)
    for h in HORIZONS:
        m[f"fwd{h}"] = m["px"].shift(-h) / m["px"] - 1

    print(f"[{market}] 기간: {m['dt'].min().date()} ~ {m['dt'].max().date()}  ({len(m)}일)")
    print(f"[{market}] S(t) 밴드별 '이후 수익률' (진입 시점 심리 → 이후 시장):")

    def summary(label, d):
        row = {"밴드": label, "일수": len(d)}
        for h in HORIZONS:
            row[f"이후{h}일"] = round(d[f"fwd{h}"].mean() * 100, 1)
        row["20일승률"] = round((d["fwd20"] > 0).mean() * 100, 0)
        return row

    rows = [summary(b, m[m["band"] == b]) for b in ORDER if len(m[m["band"] == b])]
    rows.append(summary("── 전체평균", m))
    print(pd.DataFrame(rows).to_string(index=False))

    # 핵심: 극단공포 vs 극단탐욕 스프레드 (역발상 엣지가 있으면 +)
    fear = m[m["band"] == "극단공포"]["fwd20"].mean() * 100
    greed = m[m["band"] == "극단탐욕"]["fwd20"].mean() * 100
    verdict = "✅ 역발상 엣지 있음" if fear > greed else "❌ 엣지 없음/역방향"
    print(f"▶ [{market} 핵심] 극단공포 − 극단탐욕 (이후 20일): {fear - greed:+.1f}%p  →  {verdict}")

    # ── 대시보드용: backtest_stats 테이블에 적재 (기간별 fwd/hit 컬럼) ──
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
    sb.table("backtest_stats").upsert(recs, on_conflict="market,band").execute()
    print(f"[{market}] backtest_stats 적재 완료: {len(recs)}행\n")


if __name__ == "__main__":
    markets = [a.upper() for a in sys.argv[1:]] or ["US", "KR"]
    for m in markets:
        run(m)
