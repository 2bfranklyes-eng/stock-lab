# allocation_shock.py — 충격완화 통계 → asset_shock_stats
# 사용자 포트폴리오가 주식 중심이라는 사실에서 출발한 뷰: "주식이 깨질 때 뭐가 버텨줬나".
#
# ① 급락월 조건표(crash10): 기준주식(S&P/코스피)의 캘린더 월수익 하위 10% 달에서
#    각 자산의 같은 달 수익 평균·중앙값·승률·최악값. n이 13~14달뿐 — 통계라기보다 사례 모음.
#    '하위 10%'는 전체 이력으로 정한 사후 기준(look-ahead)이다. 예측 규칙이 아니라 과거 묘사이고,
#    데이터가 쌓이면 급락월 집합 자체가 소급 재정의된다. 웹 해설에 전부 자인.
# ② 위기 리플레이(ep_*): 기준주식 고점→저점 구간 6건의 자산별 누적수익·구간 내 최대낙폭.
#    구간은 실제 데이터의 고점·저점 날짜로 앵커했다(episodes_probe로 확인). 2026은 진행 중이라
#    끝을 최신일로 연다. '결과를 알고 고른 위기 목록'이라는 선택 편향도 해설에 자인.
# ③ 원화 환산(ret_krw): 달러자산 가격×원/달러 — 급락기 환율 완충('환율 방패')을 숫자로.
#    2022년엔 원달러 +20%가 달러 자산을 크게 완충했지만, 2026 급락에선 원화가 강세라
#    방패가 없다 — 이런 '항상 통하지는 않는다'가 이 표의 핵심 정보다.
#
# 사용: python allocation_shock.py          → 계산 + 적재 (크론용)
#       python allocation_shock.py --dry    → 콘솔 요약만
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

from allocation import fetch_codes, deglitch, ASSETS, GLITCH_FILTER  # noqa: E402
from allocation_backtest import USD_ASSETS                            # noqa: E402

BENCH = {"US": "us_index", "KR": "kr_index"}
# 구간은 기준주식의 실제 고점→저점(2026은 진행 중이라 끝이 None=최신일).
EPISODES = [
    ("ep_2015yuan",  "kr_index", "2015-07-02", "2015-08-24"),
    ("ep_2018q4",    "us_index", "2018-09-20", "2018-12-24"),
    ("ep_2020covid", "us_index", "2020-02-19", "2020-03-23"),
    ("ep_2022rates", "us_index", "2022-01-03", "2022-10-12"),
    ("ep_2024yen",   "kr_index", "2024-07-11", "2024-08-05"),
    ("ep_2026kr",    "kr_index", "2026-06-22", None),
]


def monthly(px):
    """월말 종가 기준 캘린더 월수익(%). 마지막 미완성 달은 급락월 판정을 오염시키므로 버린다."""
    m = px.resample("ME").last().pct_change() * 100
    return m.iloc[:-1]


def krw_px(px, krw, a):
    """달러자산이면 원화 환산 가격, 원화자산이면 그대로."""
    return px * krw.reindex(px.index, method="ffill") if a in USD_ASSETS else px


def main():
    dry = "--dry" in sys.argv
    w = pd.DataFrame(fetch_codes(ASSETS))
    w["dt"] = pd.to_datetime(w["dt"])
    w = w.drop_duplicates(subset=["dt", "code"]).pivot(index="dt", columns="code", values="value")
    krw = w["usdkrw"].dropna()
    px_of = {}
    for a in ASSETS:
        p = w[a].dropna()
        px_of[a] = deglitch(p) if a in GLITCH_FILTER else p

    rows = []

    # ── ① 급락월 조건표 ──
    for basis, bcode in BENCH.items():
        bm = monthly(px_of[bcode])
        cut = bm.quantile(0.10)
        crash = bm[bm <= cut]
        print(f"[{basis}] 급락월 {len(crash)}달 (컷 {cut:.1f}%): "
              + " ".join(d.strftime("%y-%m") for d in crash.index))
        for a in ASSETS:
            am = monthly(px_of[a])
            ak = monthly(krw_px(px_of[a], krw, a))
            # NaN 달(자산 첫 달 pct_change, 데이터 공백)을 먼저 버린다 — 안 버리면 n은 NaN을 세고
            # hit은 NaN>0=False로 '하락'으로 집계해 같은 행의 분모가 제각각이 된다.
            r = am[crash.index.intersection(am.index)].dropna()
            if not len(r):
                continue
            rk = ak[ak.index.intersection(r.index)].dropna()   # 원화도 같은 달 집합 기준
            rows.append({"basis": basis, "scope": "crash10", "asset": a, "n": int(len(r)),
                         "ret_avg": round(float(r.mean()), 2), "ret_med": round(float(r.median()), 2),
                         "ret_krw": round(float(rk.mean()), 2) if len(rk) else None,
                         "hit": round(float((r > 0).mean() * 100), 1),
                         "worst": round(float(r.min()), 2), "mdd": None,
                         "stock_ret": round(float(crash[r.index].mean()), 2)})

    # ── ② 위기 리플레이 ──
    for scope, bcode, a0, a1 in EPISODES:
        bench = px_of[bcode]
        dates = bench.loc[a0:(a1 or bench.index[-1])].index
        if len(dates) < 5:
            print(f"{scope}: 구간 데이터 부족 — 건너뜀")
            continue
        b_ret = (bench[dates[-1]] / bench[dates[0]] - 1) * 100
        for a in ASSETS:
            p = px_of[a].reindex(dates, method="ffill")
            pk = krw_px(px_of[a], krw, a).reindex(dates, method="ffill")
            # 구간 시작 전 이력이 없는 자산은 건너뜀 — ffill은 앞을 못 채워 선두가 NaN이 되고,
            # NaN이 insert에 들어가면 배치 전체가 죽는다(JSON 비호환). 부분 구간 통계는
            # mdd를 과소평가하므로 만들지 않는 쪽이 정직하다. (2008 백필 등 과거 확장 대비)
            if p.isna().any() or pk.isna().any():
                continue
            cum = (p.iloc[-1] / p.iloc[0] - 1) * 100
            # MDD는 자산 '자기 달력'으로 — 기준주식 달력에 얹으면 BTC 주말 급락이 안 잡혀
            # 위험지표가 한 방향(과소)으로만 틀린다 (실측 최대 3.8%p 차이).
            win = px_of[a].loc[dates[0]:dates[-1]]
            mdd = ((win / win.cummax() - 1).min()) * 100
            rows.append({"basis": "EP", "scope": scope, "asset": a, "n": int(len(dates)),
                         "ret_avg": round(float(cum), 2), "ret_med": None,
                         "ret_krw": round(float((pk.iloc[-1] / pk.iloc[0] - 1) * 100), 2),
                         "hit": None, "worst": None, "mdd": round(float(mdd), 2),
                         "stock_ret": round(float(b_ret), 2)})

    ep_view = pd.DataFrame([r for r in rows if r["scope"] != "crash10"])
    for scope in ep_view["scope"].unique():
        v = ep_view[ep_view["scope"] == scope]
        best = v.loc[v["ret_avg"].idxmax()]
        print(f"{scope}: 기준주식 {v['stock_ret'].iloc[0]:+.1f}% · 최고 방어 "
              f"{best['asset']} {best['ret_avg']:+.1f}% (원화 {best['ret_krw']:+.1f}%)")

    if dry:
        print(f"\n--dry: 적재 생략 ({len(rows)}행)")
        return
    # 급락월 컷·에피소드 구간이 바뀌면 행 구성도 바뀐다 — 전량 교체(밴드 백테스트 관례).
    sb.table("asset_shock_stats").delete().neq("asset", "").execute()
    for i in range(0, len(rows), 500):
        sb.table("asset_shock_stats").insert(rows[i:i + 500]).execute()
    print(f"asset_shock_stats 적재: {len(rows)}행")


if __name__ == "__main__":
    main()
