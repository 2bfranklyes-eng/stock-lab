# allocation_backtest.py — 국면별 자산 이후수익률 통계 → asset_regime_stats
# regime_daily(사분면)에 자산 가격을 붙여, 각 국면에 서 있던 날로부터 이후 N일 수익의
# 평균·승률을 만든다 — 기존 밴드 백테스트(backtest.py 등)와 같은 문법.
#
# 정직성 장치:
#   · n_days 와 n_episodes(연속 블록 수)를 병기 — 겹치는 창은 독립 표본이 아니라서,
#     n_days 500이어도 에피소드 2번이면 그건 통계가 아니라 '사례 모음 2건'이다.
#   · 'all'(전체 기간) 행을 함께 저장 — 국면 조건부 수치는 무조건부 대비로만 의미가 있다.
#   · BTC는 이력 전체가 상승기(2014~)라 어떤 국면이든 평균이 높게 나온다 — 웹에서 뱃지 처리.
#
# 사용: python allocation_backtest.py          → 계산 + 적재 (크론용, allocation.py 다음에)
#       python allocation_backtest.py --dry    → 콘솔 요약만
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

from allocation import fetch_codes, deglitch, ASSETS, GLITCH_FILTER  # noqa: E402  같은 재료·같은 필터

HORIZONS = [5, 10, 20, 30, 60]


def fetch_regime():
    rows, step, start = [], 1000, 0
    while True:
        r = sb.table("regime_daily").select("dt,quadrant").eq("market", "GL") \
              .order("dt").range(start, start + step - 1).execute().data
        rows += r
        if len(r) < step:
            break
        start += step
    df = pd.DataFrame(rows)
    if df.empty:
        return df
    df["dt"] = pd.to_datetime(df["dt"])
    return df.set_index("dt")


def episodes(mask):
    """True 연속 블록 수 — 국면의 '사례 수'."""
    return int((mask & ~mask.shift(fill_value=False)).sum())


def main():
    dry = "--dry" in sys.argv
    rg = fetch_regime()
    if rg.empty:
        print("regime_daily 없음 — allocation.py 를 먼저 실행하세요.")
        return
    w = pd.DataFrame(fetch_codes(ASSETS))
    w["dt"] = pd.to_datetime(w["dt"])
    w = w.drop_duplicates(subset=["dt", "code"]).pivot(index="dt", columns="code", values="value")

    stats = []
    for a in ASSETS:
        px = w[a].dropna()
        if a in GLITCH_FILTER:
            px = deglitch(px)
        # 국면 달력에 정렬 — BTC(365일 거래)도 국면이 정의된 거래일 기준으로 본다.
        # 국면 시작 전 이력(2015~2017, 백분위 창 축적기)은 국면이 없으므로 자연히 빠진다.
        px = px.reindex(rg.index, method="ffill")
        fwd = {n: (px.shift(-n) / px - 1) * 100 for n in HORIZONS}
        for regime in list(rg["quadrant"].unique()) + ["all"]:
            mask = (rg["quadrant"] == regime) if regime != "all" else pd.Series(True, index=rg.index)
            row = {"regime": regime, "asset": a, "ccy": "loc",
                   "n_days": int(mask.sum()), "n_episodes": episodes(mask)}
            for n in HORIZONS:
                f = fwd[n][mask].dropna()
                row[f"fwd{n}"] = round(float(f.mean()), 2) if len(f) else None
                row[f"hit{n}"] = round(float((f > 0).mean() * 100), 1) if len(f) else None
            stats.append(row)

    cur = rg["quadrant"].iloc[-1]
    print(f"현재 국면: {cur} · 국면 이력 {rg.index[0].date()} ~ {rg.index[-1].date()}")
    view = pd.DataFrame([s for s in stats if s["regime"] in (cur, "all")])
    print(view[["regime", "asset", "n_days", "n_episodes", "fwd20", "hit20"]].to_string(index=False))

    if dry:
        print("\n--dry: 적재 생략")
        return
    # 국면 정의가 바뀌면 행 구성도 바뀌므로 upsert가 아니라 전량 교체(밴드 백테스트 관례).
    sb.table("asset_regime_stats").delete().neq("asset", "").execute()
    for i in range(0, len(stats), 500):
        sb.table("asset_regime_stats").insert(stats[i:i + 500]).execute()
    print(f"asset_regime_stats 적재: {len(stats)}행")


if __name__ == "__main__":
    main()
