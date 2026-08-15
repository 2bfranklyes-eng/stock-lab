# retrace.py — "폭락 후 낙폭의 40~60%를 되돌린 뒤 승부가 갈린다"를 검증한다.
#
# 주장(박종훈 2026-08): 코스피 9,100(6/22) → 5,593(7/30) 낙폭 3,507.
#   40% 되돌림 = 7,000, 60% = 7,700. 이 구간이 매수·매도가 부딪히는 승부처이고,
#   60%를 뚫고 올라가면 대세 상승 전환, 못 뚫으면 데드캣 바운스.
#
# 검증 가능한 형태로 바꾸면 두 명제다:
#   ① 폭락 후 첫 반등이 실제로 40~60% 구간에서 멈추는가? (분포가 거기 몰려 있나)
#   ② 60%를 넘긴 경우 정말 전고점 회복으로 이어지는가? (조건부 확률)
#
# ⚠️ 코스피는 FDR 이력이 2010년부터라 폭락 사건이 몇 개 안 된다. 시장을 합쳐야 한다.
#    단, 2008·2020 처럼 전 세계가 동시에 겪은 위기는 시장 수만큼 독립 사건이 아니다.
#    그래서 '사건 수'와 '서로 다른 위기 시기 수'를 나눠서 보고한다.
#
# ⚠️ 진행 중인 국면(아직 전고점 미회복)은 결과를 모르므로 제외된다 — 미래 정보 안 씀.
import sys
import numpy as np
import pandas as pd
import FinanceDataReader as fdr

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

MARKETS = {"KS11": "코스피", "KQ11": "코스닥", "US500": "S&P500", "IXIC": "나스닥",
           "N225": "니케이", "HSI": "항셍", "FTSE": "FTSE"}
MIN_DD = 0.20        # 이만큼 이상 떨어진 국면만 '폭락'으로 본다
PULLBACK = 0.10      # 반등이 '멈췄다'고 판정하는 되밀림 폭


def episodes(px, min_dd=MIN_DD):
    """전고점→저점→회복 사이클을 겹치지 않게 뽑는다.
    수중(underwater) 구간 = 직전 전고점을 회복하지 못한 연속 구간."""
    run_max = px.cummax()
    under = px < run_max
    out, i, n = [], 0, len(px)
    while i < n:
        if not under.iloc[i]:
            i += 1
            continue
        j = i
        while j < n and under.iloc[j]:
            j += 1
        seg = px.iloc[i:j]                       # 수중 구간
        peak = run_max.iloc[i]
        t_pos = seg.values.argmin()
        trough = seg.iloc[t_pos]
        if peak > 0 and (trough / peak - 1) <= -min_dd:
            out.append({
                "peak": peak, "trough": trough,
                "peak_dt": px.index[i - 1] if i else px.index[0],
                "trough_dt": seg.index[t_pos],
                "recovered": j < n,              # 구간이 끝났다 = 전고점 회복
                "after": px.iloc[i + t_pos:j],   # 저점 이후 회복 전까지
                "dd": trough / peak - 1,
            })
        i = j
    return out


def stall_level(ep):
    """저점 이후 첫 '멈춤' 지점의 되돌림 비율(%).
    멈춤 = 그 지점 고가에서 PULLBACK 이상 되밀린 경우. 없으면 곧장 전고점 회복."""
    s = ep["after"]
    if len(s) < 3:
        return None
    run = s.cummax()
    hit = s < run * (1 - PULLBACK)               # 국면 고점 대비 10% 되밀린 첫 시점
    span = ep["peak"] - ep["trough"]
    if span <= 0:
        return None
    if not hit.any():
        # 되밀림 없이 회복했으면 100%, 아직 진행 중이면 판정 불가
        return 100.0 if ep["recovered"] else None
    local_max = run.loc[:hit.idxmax()].iloc[-1]
    return (local_max - ep["trough"]) / span * 100


def realtime(px, min_dd=MIN_DD, thresholds=(40, 50, 60, 70)):
    """저점을 모르는 상태에서의 판정. 수중 구간을 앞에서부터 걸어가며
    '그때까지의 최저점(m) 대비 θ% 되돌린 첫 시점'을 찾고, 그 이후 m 이 깨지는지 본다.
    → (θ, 저점 지킴 수, 저점 깨짐 수) 를 돌려준다."""
    run_max = px.cummax()
    under = px < run_max
    out, i, n = [], 0, len(px)
    while i < n:
        if not under.iloc[i]:
            i += 1
            continue
        j = i
        while j < n and under.iloc[j]:
            j += 1
        seg, peak = px.iloc[i:j].values, run_max.iloc[i]
        if peak > 0 and seg.min() / peak - 1 <= -min_dd:
            for th in thresholds:
                m, hit = seg[0], None
                for k in range(1, len(seg)):
                    if seg[k] < m:
                        m = seg[k]          # 새 저점 → 기준 갱신
                        continue
                    if m / peak - 1 > -min_dd:
                        continue            # 아직 20% 하락 전이면 판정 대상 아님
                    if peak > m and (seg[k] - m) / (peak - m) * 100 >= th:
                        hit = (k, m)
                        break
                if hit:
                    k, m = hit
                    broke = bool((seg[k + 1:] < m).any())
                    out.append((th, 0 if broke else 1, 1 if broke else 0))
        i = j
    return out


def main():
    rows = []
    for sym, name in MARKETS.items():
        px = fdr.DataReader(sym)["Close"].dropna()
        for ep in episodes(px):
            lv = stall_level(ep)
            if lv is None:
                continue
            rows.append({"시장": name, "저점": ep["trough_dt"], "낙폭": ep["dd"] * 100,
                         "되돌림": lv, "회복": ep["recovered"]})
    d = pd.DataFrame(rows).sort_values("저점")
    d["위기시기"] = d["저점"].dt.year                     # 같은 해 = 같은 위기로 근사

    print(f"폭락 국면(낙폭 ≥{MIN_DD:.0%}) {len(d)}건 · "
          f"서로 다른 시기 {d['위기시기'].nunique()}개 "
          f"({d['저점'].min():%Y-%m} ~ {d['저점'].max():%Y-%m})\n")

    print("① 첫 반등이 어디서 멈췄나 — 되돌림 비율 분포")
    bins = [0, 20, 40, 60, 80, 100, 1e9]
    lbl = ["0~20%", "20~40%", "40~60%", "60~80%", "80~100%", "되밀림 없이 회복"]
    g = pd.cut(d["되돌림"], bins, labels=lbl, right=False).value_counts().reindex(lbl)
    for k, v in g.items():
        bar = "█" * int(v * 40 / max(g.max(), 1))
        print(f"  {k:<14} {v:>3}건 ({v/len(d):>5.1%}) {bar}")
    print(f"\n  중앙값 {d['되돌림'].median():.0f}%  ·  "
          f"40~60% 구간 적중 {(d['되돌림'].between(40, 60)).mean():.1%}  "
          f"(구간 폭이 전체의 20%이므로 우연히도 20% 나온다)")

    # ── ② 실시간 관점 ──
    # ①은 '최종 저점을 이미 안다'는 전제가 깔려 있다(수중 구간의 최저점을 저점으로 씀).
    # 정작 실전에서 알고 싶은 건 "지금 반등이 진짜냐"이고, 그건 저점을 모르는 상태의 질문이다.
    # 그래서 되돌림 θ%를 달성한 시점마다 "이후 그 저점을 깨고 더 내려가는가"를 센다.
    print("\n② 실시간 관점 — '저점 대비 θ% 되돌렸을 때, 이후 그 저점이 깨지는가'")
    print(f"  {'되돌림 도달':<12} {'사례':>5} {'저점 깨짐':>9} {'저점 지킴':>9}")
    res = {}
    for sym, name in MARKETS.items():
        px = fdr.DataReader(sym)["Close"].dropna()
        for th, ok, bad in realtime(px):
            res.setdefault(th, [0, 0])
            res[th][0] += ok
            res[th][1] += bad
    for th in sorted(res):
        ok, bad = res[th]
        n = ok + bad
        if n:
            print(f"  {th:>3}% 도달      {n:>5} {bad/n:>8.1%} {ok/n:>9.1%}")

    print("\n최근 10건")
    print(d.tail(10).assign(저점=lambda x: x["저점"].dt.strftime("%Y-%m-%d"),
                            낙폭=lambda x: x["낙폭"].round(1),
                            되돌림=lambda x: x["되돌림"].round(0))
          [["시장", "저점", "낙폭", "되돌림", "회복"]].to_string(index=False))

    print("\n⚠️ 2008·2020 처럼 전 세계 동시 위기는 시장 수만큼 독립 사건이 아니다.")
    print("   실질 독립 관측은 위 '서로 다른 시기' 수에 가깝다.")


if __name__ == "__main__":
    main()
