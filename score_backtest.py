# score_backtest.py — 기업 점검 '네 축 점수'의 전수 검증 (로컬 전용, DB 적재 없음)
#
# 질문: fin_score.py 의 점수(성장·수익성·현금·건전성 백분위 평균)가 높은 종목이 실제로 그 다음 달에 나았나?
#
# 생존편향·미래참조를 막는 장치 — 이게 빠지면 검증이 아니라 자기기만이다(factor.py 머리말 참고):
#   · 유니버스: 매달 '그 시점'에 상장돼 있던 전 종목(pit_monthly, 상장폐지 포함) 중 크기 기준 통과
#   · 재무: 그 달 말까지 '공시된'(rcept_dt ≤ 월말) 보고서만. 분기말이 지났어도 공시 전이면 모른다
#   · 점수 계산은 fin_score.metrics 를 그대로 호출 — 라이브 점수와 정의가 한 글자도 다르면 안 된다
#   · 수익률은 factor.build_monthly(분할 보정, 끊긴 달 제외) — 팩터 연구와 같은 잣대
#   · 거래비용 왕복 0.3% (factor.COST_RT) — 비용 전/후를 나란히
#   · 상장폐지로 끊긴 종목: 기본은 factor.py 처럼 버리되(상폐 수익률을 모름), 감도 분석으로 '-50% 가정'도 찍는다.
#     상폐는 대개 큰 손실이라 버리면 점수 낮은 쪽이 실제보다 좋아 보인다 — 점수에 불리한 쪽 편향이다.
#
# 재무 출처: fin_archive.py 가 받은 과거분(.cache/fin_archive.jsonl) + 라이브 fin_q(2023~ 현 유니버스).
# 한계: 보고서 숫자는 나중에 정정된 값일 수 있다(DART 는 최신본을 준다) — 미세한 미래참조. 정정은 드물다.
#
# 실행:  python score_backtest.py
import json
import os
import sys

import numpy as np
import pandas as pd

import factor
import fin_score
from fin_score import load

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

ROOT = os.path.dirname(os.path.abspath(__file__))
ARCH = os.path.join(ROOT, ".cache", "fin_archive.jsonl")
DELIST_HIT = -0.5          # 감도 분석: 다음 달이 끊긴(상폐·장기정지) 종목의 수익률 가정
TOPN = 180                 # 실제 관심종목 규칙: 점수 상위 180
COLS = ["code", "fiscal_q", "bsns_year", "reprt", "fs_div", "rcept_dt", "revenue_ytd", "op_income_ytd",
        "net_income_ytd", "ocf_ytd", "capex_ytd", "interest_ytd", "assets", "liabilities", "equity",
        "cur_assets", "cur_liabilities", "ppe", "cash", "receivables", "inventory"]
FLOW = {"revenue": "revenue_ytd", "op_income": "op_income_ytd", "net_income": "net_income_ytd",
        "ocf": "ocf_ytd", "capex": "capex_ytd", "interest": "interest_ytd"}


def load_fin():
    """과거분(jsonl) + 라이브 fin_q → 분기 행. 겹치면 라이브(DB) 값."""
    rows = []
    if os.path.exists(ARCH):
        with open(ARCH, encoding="utf-8") as f:
            rows = [json.loads(l) for l in f]
    a = pd.DataFrame(rows, columns=COLS) if rows else pd.DataFrame(columns=COLS)
    b = pd.DataFrame(load("fin_q", ",".join(COLS)), columns=COLS)
    q = pd.concat([a, b], ignore_index=True).drop_duplicates(["code", "fiscal_q"], keep="last")
    q = q[q["rcept_dt"].notna()].copy()
    q["qn"] = q["fiscal_q"].str[5:7].astype(int) // 3
    q["qi"] = q["bsns_year"].astype(int) * 4 + q["qn"]
    return q


def to_3m(q):
    """누적 → 3개월 (fin_q3m 뷰와 같은 규칙: 1분기는 그대로, 아니면 같은 해 직전 분기 누적을 뺀다.
    직전 분기가 비었거나 연결/별도가 바뀌었으면 빈칸)."""
    q = q.sort_values(["code", "bsns_year", "qn"]).copy()
    g = q.groupby(["code", "bsns_year"])
    prev_qn, prev_div = g["qn"].shift(1), g["fs_div"].shift(1)
    chain = (prev_qn == q["qn"] - 1) & (prev_div == q["fs_div"])
    for out, ytd in FLOW.items():
        p = g[ytd].shift(1)
        q[out] = np.where(q["qn"] == 1, q[ytd], np.where(chain, q[ytd] - p, np.nan))
    return q


def metrics_by_last(q3):
    """(종목, 마지막 분기) → 지표. 그 시점까지의 분기만 넘겨 fin_score.metrics 를 그대로 부른다.
    점수는 '가장 최근 공시 분기'에만 달려 있으므로 종목×분기마다 한 번만 계산하면 된다."""
    out = {}
    for code, g in q3.groupby("code"):
        g = g.sort_values("qi")
        for L in g["qi"]:
            m = fin_score.metrics(g[g["qi"] <= L])
            if m is not None and m["qi"] == L:          # 그 분기 매출이 있어야 그 분기 기준 점수
                out[(code, L)] = m
    return out


def score_month(uni, mets):
    """한 달 유니버스의 점수 — fin_score.main 과 같은 축·같은 결측 처리(빈 축 50, 셋 이상 있어야)."""
    d = pd.DataFrame([{**mets[(c, L)], "code": c} for c, L in uni])
    axes = {
        "s_growth": [fin_score.pct(d["rev_g"]), fin_score.pct(d["op_g"])],
        "s_profit": [fin_score.pct(d["roic"]), fin_score.pct(d["op_margin"])],
        "s_cash": [fin_score.pct(d["fcf_margin"]), fin_score.pct(d["cash_conv"])],
        "s_health": [fin_score.pct(d["debt_ratio"], higher=False), fin_score.pct(d["int_cov"])],
    }
    for k, parts in axes.items():
        d[k] = pd.concat(parts, axis=1).mean(axis=1, skipna=True)
    ax = d[list(axes)]
    d["score"] = ax.fillna(50).mean(axis=1).where(ax.notna().sum(axis=1) >= 3)
    return d.dropna(subset=["score"])


def main():
    print("재무 불러오는 중…")
    q3 = to_3m(load_fin())
    print(f"  분기 행 {len(q3):,} · 종목 {q3['code'].nunique():,} · {q3['fiscal_q'].min()} ~ {q3['fiscal_q'].max()}")
    mets = metrics_by_last(q3)
    print(f"  종목×분기 지표 {len(mets):,}")
    filed = q3[["code", "qi", "rcept_dt"]].copy()           # 그 분기 보고서가 언제 공시됐나

    corp = {c["code"]: c.get("fin_kind") for c in load("dart_corp", "code,fin_kind")}
    full = factor.build_monthly(factor.load_panel())          # 분할 보정 + 다음 달 수익률(fwd)
    # 끊긴 다음 달: 전체 패널에서 그 뒤로 다시 안 나타나면 상폐(또는 장기정지)로 본다 — 감도 분석용.
    # 크기 기준으로 거르기 '전에' 재야 한다 — 거른 뒤에 재면 시총이 줄어 빠진 종목까지 상폐로 잘못 센다.
    last_full = full.groupby("code")["ym"].max()
    full["gone"] = full["fwd"].isna() & (full["ym"] == full["code"].map(last_full)) & (full["ym"] < full["ym"].max())
    m = full[full["code"].str.endswith("0") & full["market"].isin(["KOSPI", "KOSDAQ"])]
    m = m[(m["mktcap"] >= factor.MIN_CAP) & (m["tval"] >= factor.MIN_TVAL)]
    m = m[~m["code"].map(corp).isin(["financial", "fin_holding", "non_dec_fy"])]

    rec = []
    for ym, grp in m.groupby("ym"):
        end = ym.end_time.strftime("%Y-%m-%d")
        # 월말까지 공시된 보고서 중 가장 최근 분기 — 이게 그 달에 '알 수 있었던' 재무다
        known = filed[filed["rcept_dt"] <= end].groupby("code")["qi"].max()
        uni = [(c, int(known[c])) for c in grp["code"] if c in known.index and (c, int(known[c])) in mets]
        if len(uni) < 200:
            continue
        s = score_month(uni, mets).merge(grp[["code", "fwd", "gone"]], on="code")
        # 자료 초입엔 4분기 합(TTM)이 안 서서 셋 이상 축을 가진 종목이 거의 없다 — 그런 달은 5분위가 안 나뉜다
        if len(s) < 100:
            continue
        s["ym"] = ym
        rec.append(s)
    p = pd.concat(rec, ignore_index=True)
    print(f"  채점된 달 {p['ym'].nunique()}개월 ({p['ym'].min()} ~ {p['ym'].max()}) · 월평균 {p.groupby('ym').size().mean():.0f}종목")
    p.to_pickle(os.path.join(ROOT, ".cache", "score_backtest_panel.pkl"))
    evaluate(p)


def portfolio(p, pick, label, hit=None):
    """매달 pick(그 달 표) → 고른 종목 동일가중 다음 달 수익률 vs 유니버스 동일가중."""
    out, prev = [], set()
    for ym, g in p.groupby("ym"):
        g = g.copy()
        if hit is not None:
            g.loc[g["gone"], "fwd"] = hit
        g = g.dropna(subset=["fwd"])
        sel = pick(g)
        if sel.empty:
            continue
        cur = set(sel["code"])
        turn = len(cur - prev) / len(cur) if prev else 1.0
        prev = cur
        out.append({"ym": ym, "n": len(sel), "ret": sel["fwd"].mean(), "mkt": g["fwd"].mean(), "turn": turn})
    r = pd.DataFrame(out)
    r["ex"] = r["ret"] - r["mkt"]
    r["ex_net"] = r["ex"] - r["turn"] * factor.COST_RT      # 롱온리 한 다리 — 바뀐 비율만큼 왕복 비용
    return r


def tstat(x):
    x = x.dropna()
    return x.mean() / (x.std(ddof=1) / np.sqrt(len(x))) if len(x) > 2 else np.nan


def show(r, label):
    a, b = factor.summ(r, "ex"), factor.summ(r, "ex_net")
    if a is None:
        print(f"  {label:<24} 표본 부족({len(r)}개월)")
        return
    half = len(r) // 2
    # 전반·후반을 따로 — 부호가 뒤집히면 그 초과수익은 특정 시기의 우연이다(factor.py 와 같은 잣대)
    h = [factor.summ(x, "ex") for x in (r.iloc[:half], r.iloc[half:])]
    hs = " / ".join("  —  " if s is None else f"{s['ann']:+5.1f}%" for s in h)
    print(f"  {label:<24} 초과(전) {a['ann']:+6.1f}% · 초과(후) {b['ann']:+6.1f}% · t {tstat(r['ex']):+5.2f} · "
          f"월승률 {a['win']:4.0f}% · 회전 {r['turn'].mean() * 100:3.0f}% | 전반/후반 {hs}")


def evaluate(p):
    p = p.copy()
    p["q"] = p.groupby("ym")["score"].transform(lambda s: pd.qcut(s.rank(method="first"), 5, labels=False))
    print("\n── 점수 5분위 (매달 리밸런싱, 동일가중, 유니버스 대비 초과수익) ──")
    for k, nm in ((4, "상위 20%"), (3, "60~80%"), (2, "40~60%"), (1, "20~40%"), (0, "하위 20%")):
        show(portfolio(p, lambda g, k=k: g[g["q"] == k], nm), nm)
    print("\n── 실제 규칙: 점수 상위 180 ──")
    show(portfolio(p, lambda g: g.nlargest(TOPN, "score"), "상위 180"), "상위 180")
    show(portfolio(p, lambda g: g.nlargest(TOPN, "score"), "상위 180", hit=DELIST_HIT), f"상위 180 (상폐 {DELIST_HIT:.0%})")
    show(portfolio(p, lambda g: g[g["q"] == 0], "하위 20%", hit=DELIST_HIT), f"하위 20% (상폐 {DELIST_HIT:.0%})")
    print("\n── 축별 상위 20% (어느 축이 일을 하나) ──")
    for ax, nm in (("s_growth", "성장"), ("s_profit", "수익성"), ("s_cash", "현금"), ("s_health", "건전성")):
        pp = p.dropna(subset=[ax]).copy()
        pp["qa"] = pp.groupby("ym")[ax].transform(lambda s: pd.qcut(s.rank(method="first"), 5, labels=False))
        show(portfolio(pp, lambda g: g[g["qa"] == 4], nm), f"{nm} 상위 20%")
    gone = p.groupby("q")["gone"].mean() * 100
    print("\n  다음 달이 끊긴(상폐·장기정지) 비율: " + " · ".join(f"{['하위','20~40','40~60','60~80','상위'][k]} {v:.2f}%"
                                                  for k, v in gone.items()))


if __name__ == "__main__":
    main()
