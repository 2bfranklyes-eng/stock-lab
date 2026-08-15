# flowtest.py — "기관·외국인이 개인에게 떠넘긴다"를 검증 가능한 형태로 바꿔서 테스트한다.
#
# 영상(경제학교)의 주장: 개인이 매수 버튼을 누르는 순간 기관·외국인이 매도 폭탄을 쏟는다.
# 리딩방·세력 서사를 걷어내면 남는 반증 가능한 명제는 하나다:
#   "주체별 순매수는 이후 수익률과 관계가 있는가? 개인은 음(-), 외국인·기관은 양(+)인가?"
#
# 설계 — 횡단면 분위 테스트(factor.py 와 같은 틀). 시계열 국면 연구와 달리 관측이
#   '사건'이 아니라 '종목-월'이라 검정력이 있다. 단, 독립 관측 수는 종목 수가 아니라
#   **월 수**임에 주의(같은 달의 종목들은 시장 전체 움직임을 공유한다) — 그래서 t값은
#   월별 스프레드 시계열로 계산한다.
#
# ⚠️ 개인과 외국인+기관은 항등식으로 거의 거울상이다(모든 매수엔 매도가 있다).
#    둘의 결과가 반대로 나오는 건 독립적인 두 증거가 아니라 같은 사실을 두 번 본 것이다.
#
# ⚠️ 겹치지 않는 월 단위 보유만 본다. 일별로 겹쳐 보면 관측이 20배 부풀려진다.
import os
import sys
import pickle
import numpy as np
import pandas as pd
from dotenv import load_dotenv
from supabase import create_client

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

load_dotenv()
sb = create_client(os.environ["SUPABASE_URL"], os.environ["SUPABASE_SERVICE_KEY"])

FLOW_CACHE, CAP_CACHE = "flow_cache.pkl", "flowcap_cache.pkl"
NQ = 5              # 분위 수
MIN_N = 50          # 그 달에 이보다 종목이 적으면 건너뜀


def fetch_monthly(table, cols, cache, start, end):
    """월 단위로 끊어 받는다 — 전체 offset 페이지네이션은 뒤로 갈수록 O(offset)이라 느려진다."""
    if os.path.exists(cache):
        with open(cache, "rb") as f:
            df = pickle.load(f)
        print(f"캐시 사용: {cache} ({len(df):,}행)")
        return df
    rows, step = [], 1000
    for m0 in pd.date_range(start, end, freq="MS"):
        m1 = m0 + pd.offsets.MonthBegin(1)
        s = 0
        while True:
            r = sb.table(table).select(cols) \
                  .gte("dt", m0.strftime("%Y-%m-%d")).lt("dt", m1.strftime("%Y-%m-%d")) \
                  .order("dt").order("code").range(s, s + step - 1).execute().data
            rows += r
            if len(r) < step:
                break
            s += step
        print(f"  {m0:%Y-%m} … 누적 {len(rows):,}행", end="\r")
    print()
    df = pd.DataFrame(rows)
    with open(cache, "wb") as f:
        pickle.dump(df, f)
    return df


def load():
    flow = fetch_monthly("investor_flow", "dt,code,inv,val", FLOW_CACHE, "2024-07-01", "2026-09-01")
    flow["dt"] = pd.to_datetime(flow["dt"])
    codes = sorted(flow["code"].unique())
    print(f"수급: {len(flow):,}행 · {len(codes)}종목 · 주체 {sorted(flow['inv'].unique())}")

    cap = fetch_monthly("stock_daily", "dt,code,close,mktcap", CAP_CACHE, "2024-07-01", "2026-09-01")
    cap["dt"] = pd.to_datetime(cap["dt"])
    cap = cap[cap["code"].isin(codes)]
    print(f"시세: {len(cap):,}행 · {cap['code'].nunique()}종목")
    return flow, cap


def build_panel(flow, cap, freq="M"):
    """기간별 패널 — 주체별 순매수(시총 대비) + 다음 기간 수익률.
    freq='M' 월간(기간 25개) / 'W' 주간(기간 ~108개, 검정력은 높지만 잡음도 크다)."""
    flow, cap = flow.copy(), cap.copy()
    flow["ym"] = flow["dt"].dt.to_period(freq)
    cap["ym"] = cap["dt"].dt.to_period(freq)

    # 월말 종가·시총 (그 달 마지막 거래일)
    eom = cap.sort_values("dt").groupby(["code", "ym"]).last()[["close", "mktcap"]].reset_index()
    eom["fwd"] = eom.groupby("code")["close"].shift(-1) / eom["close"] - 1   # 다음 달 수익률

    # 주체별 월간 순매수 대금
    agg = flow.groupby(["code", "ym", "inv"])["val"].sum().unstack("inv")
    agg = agg.reset_index()

    p = agg.merge(eom, on=["code", "ym"], how="inner")
    p = p[(p["mktcap"] > 0) & p["fwd"].notna()]
    return p


def quintile_test(p, inv):
    """주체 inv 의 순매수/시총으로 매월 5분위 → 다음 달 수익률. 월별 스프레드로 t값."""
    d = p[["ym", "code", inv, "mktcap", "fwd"]].dropna().copy()
    d["signal"] = d[inv] / d["mktcap"]

    rows, spreads = [], []
    for ym, g in d.groupby("ym"):
        if len(g) < MIN_N:
            continue
        q = pd.qcut(g["signal"].rank(method="first"), NQ, labels=False)
        means = g.groupby(q)["fwd"].mean()
        if len(means) < NQ:
            continue
        rows.append(means)
        spreads.append(means.iloc[-1] - means.iloc[0])

    if len(spreads) < 6:
        return None
    tbl = pd.DataFrame(rows).mean() * 100
    sp = np.array(spreads) * 100
    t = sp.mean() / (sp.std(ddof=1) / np.sqrt(len(sp)))
    return {"q": tbl, "spread": sp.mean(), "t": t, "months": len(sp)}


def run(flow, cap, freq, label):
    p = build_panel(flow, cap, freq)
    invs = [c for c in p.columns if c not in ("code", "ym", "close", "mktcap", "fwd")]
    print(f"\n[{label}] 패널 {len(p):,} 종목-기간 · {p['ym'].nunique()}기간 "
          f"({p['ym'].min()} ~ {p['ym'].max()})")
    print(f"  {'주체':<10} {'Q1(순매도)':>10} {'Q2':>7} {'Q3':>7} {'Q4':>7} "
          f"{'Q5(순매수)':>10} {'Q5-Q1':>8} {'t':>6}")
    last = None
    for inv in invs:
        r = quintile_test(p, inv)
        if r is None:
            print(f"  {inv:<10} — 표본 부족")
            continue
        cells = "".join(f"{v:>7.2f}" if i not in (0, NQ - 1) else f"{v:>10.2f}"
                        for i, v in enumerate(r["q"]))
        print(f"  {inv:<10}{cells} {r['spread']:>8.2f} {r['t']:>6.2f}")
        last = r
    if last:
        print(f"  독립 관측 = 종목 수가 아니라 기간 수 {last['months']}개. |t|>2 라야 유의.")


def main():
    flow, cap = load()
    print("\n주체별 순매수(시총 대비) 5분위 → 다음 기간 수익률 (%)")
    run(flow, cap, "M", "월간 · 보유 1개월")
    run(flow, cap, "W", "주간 · 보유 1주")
    print("\n⚠️ 개인과 외국인·기관은 항등식상 거의 거울상 — 반대 부호는 독립 증거가 아니다.")
    print("\n(적재 없음 — DB 용량 영향 0)")


if __name__ == "__main__":
    main()
