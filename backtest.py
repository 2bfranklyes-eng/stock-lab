# backtest.py — S(t) 심리 밴드가 '이후 수익률'을 예고하는지 검증
# 가설: 극단공포 뒤엔 반등(+), 극단탐욕 뒤엔 조정(-) 이라는 역발상 엣지가 있나?
import os
from dotenv import load_dotenv
import pandas as pd
from supabase import create_client

load_dotenv()
sb = create_client(os.environ["SUPABASE_URL"], os.environ["SUPABASE_SERVICE_KEY"])
MARKET = "US"
ORDER = ["극단공포", "공포", "중립", "탐욕", "극단탐욕"]


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


sent = fetch("sentiment_daily", "dt,s_score,band", market=MARKET)
px = fetch("indicator_raw", "dt,value", market=MARKET, code="us_index")
sent["dt"] = pd.to_datetime(sent["dt"])
px["dt"] = pd.to_datetime(px["dt"])
m = sent.merge(px.rename(columns={"value": "spx"}), on="dt").sort_values("dt").reset_index(drop=True)

# 이후 5/20/60일 수익률
for h in (5, 20, 60):
    m[f"fwd{h}"] = m["spx"].shift(-h) / m["spx"] - 1

print(f"기간: {m['dt'].min().date()} ~ {m['dt'].max().date()}  ({len(m)}일)\n")
print("S(t) 밴드별 '이후 수익률' (진입 시점 심리 → 이후 시장):")

rows = []
for b in ORDER:
    d = m[m["band"] == b]
    if len(d) == 0:
        continue
    rows.append({"밴드": b, "일수": len(d),
                 "이후5일": round(d["fwd5"].mean() * 100, 1),
                 "이후20일": round(d["fwd20"].mean() * 100, 1),
                 "이후60일": round(d["fwd60"].mean() * 100, 1),
                 "20일승률": round((d["fwd20"] > 0).mean() * 100, 0)})
rows.append({"밴드": "── 전체평균", "일수": len(m),
             "이후5일": round(m["fwd5"].mean() * 100, 1),
             "이후20일": round(m["fwd20"].mean() * 100, 1),
             "이후60일": round(m["fwd60"].mean() * 100, 1),
             "20일승률": round((m["fwd20"] > 0).mean() * 100, 0)})
print(pd.DataFrame(rows).to_string(index=False))

# 핵심: 극단공포 vs 극단탐욕 스프레드 (역발상 엣지가 있으면 +)
fear = m[m["band"] == "극단공포"]["fwd20"].mean() * 100
greed = m[m["band"] == "극단탐욕"]["fwd20"].mean() * 100
verdict = "✅ 역발상 엣지 있음" if fear > greed else "❌ 엣지 없음/역방향"
print(f"\n▶ [핵심] 극단공포 − 극단탐욕 (이후 20일): {fear - greed:+.1f}%p  →  {verdict}")
print("  (공포일 때가 탐욕일 때보다 이후 수익이 높으면 = 심리가 반전을 예고)")

# ── 대시보드용: backtest_stats 테이블에 적재 ──
recs = []
for b in ORDER + ["전체"]:
    d = m if b == "전체" else m[m["band"] == b]
    if len(d) == 0:
        continue
    recs.append({"market": MARKET, "band": b, "n": int(len(d)),
                 "fwd5": round(float(d["fwd5"].mean() * 100), 2),
                 "fwd20": round(float(d["fwd20"].mean() * 100), 2),
                 "fwd60": round(float(d["fwd60"].mean() * 100), 2),
                 "hit20": round(float((d["fwd20"] > 0).mean() * 100), 1)})
sb.table("backtest_stats").upsert(recs, on_conflict="market,band").execute()
print(f"\nbacktest_stats 적재 완료: {len(recs)}행")
