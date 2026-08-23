# cgotest.py — "본전에 가까워지면 매도 압력이 커진다"(처분효과)를 검증한다.
#
# 주장(박종훈 2026-08, Odean 1998 인용): 개인 순매수가 코스피 7,000~8,500에 몰려 있으니
#   본전 부근에서 매물이 쏟아진다. 원 연구는 Shefrin&Statman(1985)·Odean(1998)의 처분효과 —
#   오른 건 빨리 팔고 물린 건 붙들고 있다. cgo.py 가 재는 CGO 가 바로 그 지표다.
#
# 두 가지를 나눠 본다. 섞으면 안 된다:
#   ① 메커니즘 — CGO 수준이 그 주체의 '이후 순매수'를 예측하나? (일별 ~400관측, 검정력 있음)
#   ② 시장 영향 — CGO 수준이 '이후 지수 수익률'을 예측하나? (국면 질문 → 검정력 없음)
#
# ⚠️ 교란 하나를 반드시 통제해야 한다. 가격이 떨어지면 CGO 도 떨어지고 개인은 저가매수를
#    늘리는 경향이 있다. 통제 없이 보면 'CGO 낮을 때 개인이 산다'가 그냥 가격 반응일 뿐인데
#    처분효과처럼 보인다. 그래서 과거 20일 수익률을 같이 회귀에 넣는다.
#
# ⚠️ CGO 는 아주 느리게 움직여서 일별 400관측이 400개의 독립 관측이 아니다.
#    구간별 '사건 수'(연속 덩어리)를 같이 찍어 근거의 크기를 드러낸다.
import os
import sys
import pickle
import numpy as np
import pandas as pd
from dotenv import load_dotenv
from supabase import create_client
import FinanceDataReader as fdr

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

load_dotenv()
sb = create_client(os.environ["SUPABASE_URL"], os.environ["SUPABASE_SERVICE_KEY"])

HL = 182          # 반감기 — 이력이 더 긴 쪽(2025-01~)
FWD = 20          # 이후 관측 지평(거래일)
INV = "개인"       # 처분효과의 주인공


def fetch_cgo():
    rows, step, start = [], 1000, 0
    while True:
        r = sb.table("cgo_daily").select("dt,inv,cgo_med,under_pct,deep_pct") \
              .eq("hl_days", HL).order("dt").order("inv") \
              .range(start, start + step - 1).execute().data
        rows += r
        if len(r) < step:
            break
        start += step
    d = pd.DataFrame(rows)
    d["dt"] = pd.to_datetime(d["dt"])
    return d


def daily_flow():
    """flowtest.py 가 남긴 캐시를 재사용 — 일별·주체별 시장 전체 순매수(조원)."""
    if not os.path.exists("flow_cache.pkl"):
        raise SystemExit("flow_cache.pkl 이 없습니다 — flowtest.py 를 먼저 한 번 돌리세요")
    f = pickle.load(open("flow_cache.pkl", "rb"))
    f["dt"] = pd.to_datetime(f["dt"])
    return f.groupby(["dt", "inv"])["val"].sum().unstack("inv") / 1e12


def episodes(mask):
    """붙어있는 날들은 한 사건 — 일수가 아니라 이걸 센다."""
    if not mask.any():
        return 0
    return int((mask.astype(int).diff() == 1).sum() + (1 if bool(mask.iloc[0]) else 0))


def main():
    cgo = fetch_cgo()
    flow = daily_flow()
    kospi = fdr.DataReader("KS11", "2024-01-01")["Close"]

    c = cgo[cgo["inv"] == INV].set_index("dt")[["cgo_med", "under_pct", "deep_pct"]]
    df = c.join(flow[[INV]].rename(columns={INV: "netbuy"}), how="inner")
    df["px"] = kospi.reindex(df.index).ffill()
    df["ret20p"] = df["px"].pct_change(FWD) * 100                       # 과거 20일 (교란 통제용)
    df["fwd_buy"] = df["netbuy"][::-1].rolling(FWD).sum()[::-1].shift(-1)   # 이후 20일 순매수 합
    df["fwd_ret"] = (df["px"].shift(-FWD) / df["px"] - 1) * 100             # 이후 20일 수익률
    d = df.dropna()

    # 최신값은 df(=미래 관측이 필요 없는 원본)에서, 분석 표본 d 는 뒤 FWD일이 잘려 있다
    print(f"[{INV}] CGO(반감기 {HL}일)")
    print(f"  최신 {df.index[-1]:%Y-%m-%d}: CGO 중앙값 {df['cgo_med'].iloc[-1]:+.2f}%  ·  "
          f"물린 종목 {df['under_pct'].iloc[-1]:.1f}%")
    print(f"  분석 표본 {d.index[0]:%Y-%m-%d} ~ {d.index[-1]:%Y-%m-%d} ({len(d):,}일) "
          f"— 이후 {FWD}일이 필요해 최근 {FWD}일은 빠진다")
    print(f"  기간 중 CGO 범위 {d['cgo_med'].min():+.1f}~{d['cgo_med'].max():+.1f}%")

    # ── ① 메커니즘: CGO 구간별 '이후 20일 개인 순매수' ──
    print(f"\n① 처분효과 — CGO 구간별 이후 {FWD}일 {INV} 순매수 (조원)")
    print(f"  {'CGO 구간':<14} {'일수':>5} {'사건':>5} {'이후 순매수':>11} {'이후 수익률':>11}")
    bins = [-1e9, -10, -5, 0, 5, 1e9]
    lbl = ["-10% 미만(깊게 물림)", "-10~-5%", "-5~0%(본전 근처)", "0~+5%(본전 직상)", "+5% 초과(이익)"]
    for (lo, hi), nm in zip(zip(bins[:-1], bins[1:]), lbl):
        m = d["cgo_med"].between(lo, hi, inclusive="left")
        if not m.any():
            print(f"  {nm:<14} {'— 해당 없음':>5}")
            continue
        print(f"  {nm:<14} {m.sum():>5} {episodes(m):>5} "
              f"{d[m]['fwd_buy'].mean():>+11.2f} {d[m]['fwd_ret'].mean():>+10.2f}%")

    # ── 교란 통제: 과거 수익률을 넣고도 CGO 계수가 남나 ──
    X = np.column_stack([np.ones(len(d)), d["cgo_med"], d["ret20p"]])
    for y, nm in [(d["fwd_buy"], f"이후 {FWD}일 순매수"), (d["fwd_ret"], f"이후 {FWD}일 수익률")]:
        beta, *_ = np.linalg.lstsq(X, y.values, rcond=None)
        resid = y.values - X @ beta
        se = np.sqrt(np.sum(resid ** 2) / (len(d) - 3) *
                     np.diag(np.linalg.inv(X.T @ X)))
        print(f"\n  회귀: {nm} ~ CGO + 과거{FWD}일수익률")
        print(f"    CGO 계수      {beta[1]:+.4f}  (t={beta[1]/se[1]:+.2f})")
        print(f"    과거수익률 계수 {beta[2]:+.4f}  (t={beta[2]/se[2]:+.2f})")

    print(f"\n⚠️ CGO 는 아주 느리게 움직인다 — {len(d)}일이 {len(d)}개의 독립 관측이 아니다.")
    print("   위 '사건' 열이 실질 근거의 크기다. 회귀 t값도 그만큼 부풀려져 있다.")
    print("\n(적재 없음 — DB 용량 영향 0)")


if __name__ == "__main__":
    main()
