# inflation_backtest.py — I(t) 물가 밴드가 '이후 수익률'을 예고하는지 검증 (미국 + 한국)
# 가설: 저물가(디스인플레) 뒤엔 순풍(+), 고물가(인플레) 뒤엔 역풍(-)? — 밸류에이션·금리 부담 때문.
#   구조는 liquidity_backtest.py 와 동일 — liquidity_daily 대신 inflation_daily 밴드를 씀.
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
ORDER = ["극단저물가", "저물가", "중립", "고물가", "극단고물가"]
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
    inf = fetch("inflation_daily", "dt,i_score,band", market=market)
    px = fetch("indicator_raw", "dt,value", market=market, code=PRICE_CODE[market])
    if inf.empty or px.empty:
        print(f"[{market}] 데이터 부족 — 건너뜀\n")
        return
    inf["dt"] = pd.to_datetime(inf["dt"])
    px["dt"] = pd.to_datetime(px["dt"])
    m = inf.merge(px.rename(columns={"value": "px"}), on="dt").sort_values("dt").reset_index(drop=True)

    # 이후 수익률 (여러 기간)
    for h in HORIZONS:
        m[f"fwd{h}"] = m["px"].shift(-h) / m["px"] - 1

    print(f"[{market}] 기간: {m['dt'].min().date()} ~ {m['dt'].max().date()}  ({len(m)}일)")
    print(f"[{market}] I(t) 밴드별 '이후 수익률' (진입 시점 물가압력 → 이후 시장):")

    def summary(label, d):
        row = {"밴드": label, "일수": len(d)}
        for h in HORIZONS:
            row[f"이후{h}일"] = round(d[f"fwd{h}"].mean() * 100, 1)
        # ⚠️ dropna 필수 — 최근 h일은 아직 미래가 없어 NaN 이고, NaN > 0 은 False 라 '패배'로 잡힌다(backtest.py 와 같은 수정)
        f20 = d["fwd20"].dropna()
        row["20일승률"] = round((f20 > 0).mean() * 100, 0) if len(f20) else None
        return row

    rows = [summary(b, m[m["band"] == b]) for b in ORDER if len(m[m["band"] == b])]
    rows.append(summary("── 전체평균", m))
    print(pd.DataFrame(rows).to_string(index=False))

    # 핵심: 극단저물가 vs 극단고물가 스프레드 (디스인플레 순풍이 있으면 +)
    low = m[m["band"] == "극단저물가"]["fwd20"].mean() * 100
    high = m[m["band"] == "극단고물가"]["fwd20"].mean() * 100
    verdict = "✅ 저물가 순풍 있음" if low > high else "❌ 순풍 없음/역방향"
    print(f"▶ [{market} 핵심] 극단저물가 − 극단고물가 (이후 20일): {low - high:+.1f}%p  →  {verdict}")

    # ── 대시보드용: inflation_backtest_stats 테이블에 적재 (기간별 fwd/hit 컬럼) ──
    recs = []
    for b in ORDER + ["전체"]:
        d = m if b == "전체" else m[m["band"] == b]
        if len(d) == 0:
            continue
        # 사건 수 = 그 밴드에 머문 연속 블록 수(backtest.py 와 같은 정의). 일수는 독립 표본이 아니다 —
        # 10일 평활 때문에 한 밴드가 수십~수백 일 이어져, 극단 밴드의 근거가 몇 건뿐일 수 있다
        f = m["band"] == b
        rec = {"market": market, "band": b, "n": int(len(d)),
               "n_episodes": None if b == "전체" else int((f & ~f.shift(fill_value=False)).sum())}
        for h in HORIZONS:
            f = d[f"fwd{h}"].dropna()
            rec[f"fwd{h}"] = round(float(f.mean() * 100), 2) if len(f) else None
            rec[f"hit{h}"] = round(float((f > 0).mean() * 100), 1) if len(f) else None
        recs.append(rec)
    # delete→insert: 밴드가 사라져도 옛 행이 남지 않게(liquidity_backtest 와 같은 방식)
    sb.table("inflation_backtest_stats").delete().eq("market", market).execute()
    try:
        sb.table("inflation_backtest_stats").insert(recs).execute()
    except Exception as e:                    # n_episodes 칸이 아직 없으면(sql/backtest_add_episodes2.sql 전) 빼고 넣는다
        if "n_episodes" not in str(e):
            raise
        sb.table("inflation_backtest_stats").insert([{k: v for k, v in r.items() if k != "n_episodes"} for r in recs]).execute()
    print(f"[{market}] inflation_backtest_stats 적재 완료: {len(recs)}행\n")


if __name__ == "__main__":
    markets = [a.upper() for a in sys.argv[1:]] or ["US", "KR"]
    for m in markets:
        run(m)
