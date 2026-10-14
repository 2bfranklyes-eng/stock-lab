# fin_score.py — 분기 재무 이력(fin_q3m) → 네 축 점수(fin_score) → 관심종목(watch) 채우기
#
# 고르는 방식(2026-10-14 사용자 확정 초안):
#   1) 거르기: 금융업(fin_hist.py 가 dart_corp 에 표시) · 감사의견 비적정 · 시총 500억/거래대금 5억 미만
#   2) 점수: 네 축을 유니버스 안 백분위(0~100)로 매기고 평균한다
#        성장   = 매출 TTM 증가율, 영업이익 TTM 증가율
#        수익성 = ROIC, 영업이익률
#        현금   = FCF 마진, 현금 전환율(영업현금흐름 ÷ 순이익)
#        건전성 = 부채비율(낮을수록), 이자보상배율
#   3) 위에서부터 180개를 watch 에 넣는다 — 나머지 20자리는 사용자가 직접 넣는 몫
#   4) 한번 들어온 종목은 '제외' 판정 전까지 남긴다(점수가 분기마다 출렁여도 들락날락하지 않게)
#
# ⚠️ 백분위는 업종을 가리지 않는다. 영업이익률·부채비율은 업종마다 원래 수준이 달라서(유통은 이익률이
#    낮고, 조선·건설은 선수금 때문에 부채비율이 높다) 그런 업종이 구조적으로 불리하다. 1차판의 알려진 한계.
# ⚠️ 경고 표시(flags)는 점수에 넣지 않는다 — 점수는 '좋은 정도', 경고는 '확인할 것'으로 따로 본다.
#
# 실행:  python fin_score.py         → 계산 + 적재 + watch 채우기
#        python fin_score.py --dry   → 적재 없이 상위 30 출력
import argparse
import sys
from datetime import date, datetime, timedelta, timezone

import pandas as pd

from dart import sb
import fin_hist

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

SCORE_SLOTS = 180          # 점수로 채우는 자리. 직접 추가(manual)는 이 수에 안 센다
STALE_Q = 2                # 최신 분기보다 2분기 넘게 뒤처진 보고서는 '지연' 표시
# 최근 1년 공시 사건 → 경고 표시 (dart_events.py 가 모은다). 자사주·무상증자처럼 경고가 아닌 건 뺀다.
EVENT_FLAG = {"cb": "CB·BW", "bw": "CB·BW", "eb": "CB·BW", "rights": "유상증자",
              "reduction": "감자", "distress": "부실공시", "suspension": "영업정지"}


def load(table, cols, **eq):
    rows, off = [], 0
    while True:
        q = sb.table(table).select(cols)
        for k, v in eq.items():
            q = q.eq(k, v)
        d = q.range(off, off + 999).execute().data
        rows += d
        off += 1000
        if len(d) < 1000:
            return rows


def ttm(g, col, last, back=0):
    """last 분기(분기 번호)에서 back 분기 전까지 거슬러 4분기 합. 하나라도 비면 None —
    3개월치가 빠진 합을 1년치로 믿으면 성장률이 거짓말을 한다."""
    want = range(last - back - 3, last - back + 1)
    s = g.set_index("qi")[col]
    vals = [s.get(i) for i in want]
    if any(v is None or pd.isna(v) for v in vals):
        return None
    return float(sum(vals))


def chg(now, prev):
    """증가율. 기저가 음수(적자)여도 방향이 맞게 |기저|로 나눈다 — 적자 축소도 '개선'으로 읽힌다."""
    if now is None or prev is None or prev == 0:
        return None
    return (now - prev) / abs(prev)


def cover(op, intr):
    """이자보상배율. 이자를 한 푼도 안 냈으면 '무한'이라 상한 100배로 눌러 둔다(백분위엔 순서만 중요)."""
    if op is None or intr is None:
        return None
    if intr > 0:
        return min(op / intr, 100.0)
    return 100.0 if op > 0 else None


def metrics(g):
    g = g.sort_values("qi")
    have = g[g["revenue"].notna()]
    if have.empty:
        return None
    last = int(have["qi"].max())
    cur = g[g["qi"] == last].iloc[0]
    yago = g[g["qi"] == last - 4]
    yago = yago.iloc[0] if len(yago) else None
    rev, rev_p = ttm(g, "revenue", last), ttm(g, "revenue", last, 4)
    op, op_p = ttm(g, "op_income", last), ttm(g, "op_income", last, 4)
    net, ocf, capex = ttm(g, "net_income", last), ttm(g, "ocf", last), ttm(g, "capex", last)
    intr = ttm(g, "interest", last)

    def bs(row, k):
        if row is None:
            return None
        v = row[k]
        return None if pd.isna(v) else float(v)

    ca, cl, ppe, assets = bs(cur, "cur_assets"), bs(cur, "cur_liabilities"), bs(cur, "ppe"), bs(cur, "assets")
    liab, eq = bs(cur, "liabilities"), bs(cur, "equity")
    ic = None
    if None not in (ca, cl, ppe):
        ic = max(ca - cl, 0) + ppe
        if assets and ic < assets * 0.05:          # 지주회사처럼 영업용 자산이 거의 없으면 ROIC 가 폭발한다(dart.py 와 같은 이유)
            ic = None
    m = {
        "fiscal_q": cur["fiscal_q"], "qi": last,
        "rev_g": chg(rev, rev_p), "op_g": chg(op, op_p),
        "roic": (op / ic) if op is not None and ic else None,
        "op_margin": (op / rev) if op is not None and rev else None,
        "fcf_margin": ((ocf - capex) / rev) if None not in (ocf, capex) and rev else None,
        "cash_conv": (ocf / net) if ocf is not None and net and net > 0 else None,
        "debt_ratio": (liab / eq * 100) if liab is not None and eq and eq > 0 else None,
        "int_cov": cover(op, intr),
    }
    flags = []
    if eq is not None and eq <= 0:
        flags.append("자본잠식")
    if None not in (ocf, capex) and ocf - capex < 0:
        flags.append("FCF적자")
    if m["cash_conv"] is not None and m["cash_conv"] < 0.5:
        flags.append("이익의질")
    # 결제·핀테크처럼 고객 예치금이 영업현금흐름에 섞이는 회사는 FCF 가 매출을 넘기도 한다
    # (실측: 더즌 130%, 쿠콘 87%). 계산은 맞지만 '버는 현금'이 아니라 '맡은 현금'일 수 있다.
    if m["fcf_margin"] is not None and abs(m["fcf_margin"]) > 0.6:
        flags.append("현금흐름확인")
    if g.tail(8)["fs_div"].nunique() > 1:
        flags.append("연결별도변경")
    rg = chg(rev, rev_p)
    for k, nm in (("receivables", "매출채권급증"), ("inventory", "재고급증")):
        a, b = bs(cur, k), bs(yago, k)
        if None not in (a, b, rg) and b > 0 and (a / b - 1) - rg > 0.20:
            flags.append(nm)
    m["flags"] = flags
    return m


def pct(s, higher=True):
    """백분위 0~100. 값이 없는 종목은 None 그대로(그 지표만 빠지고 축은 남은 지표로 매긴다)."""
    r = s.rank(pct=True, ascending=higher) * 100
    return r.where(s.notna())


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry", action="store_true")
    a = ap.parse_args()
    run_at = datetime.now(timezone.utc).isoformat()

    uni = {u["code"]: u for u in fin_hist.universe()}
    corp = {c["code"]: c for c in load("dart_corp", "code,fin_kind")}
    audit, evf = {}, {}
    since = (date.today() - timedelta(days=365)).isoformat()
    for e in load("dart_event", "code,kind,rcept_dt,report_nm,detail"):
        c = e["code"]
        if not c:
            continue
        # [기재정정]·[첨부정정] 같은 정정공시는 같은 결정을 다시 낸 것이다 — 세면 1건이 3회가 된다
        # (실측: SK하이닉스 유상증자 1건 + 정정 2건이 '유상증자 3회'로 찍혔다)
        if (e.get("report_nm") or "").startswith("["):
            continue
        if e["kind"] == "audit":
            if c not in audit or e["rcept_dt"] > audit[c]["rcept_dt"]:
                audit[c] = e
        elif e["rcept_dt"] >= since and e["kind"] in EVENT_FLAG:
            # 날짜로 센다 — 한 결정을 같은 날 여러 건으로 나눠 내기도 한다(실측: 알테오젠 10/6 유상증자 4건)
            evf.setdefault(c, {}).setdefault(EVENT_FLAG[e["kind"]], set()).add(e["rcept_dt"])
    q = pd.DataFrame(load("fin_q3m", "code,fiscal_q,bsns_year,qn,fs_div,revenue,op_income,net_income,ocf,capex,"
                                     "interest,assets,liabilities,equity,cur_assets,cur_liabilities,ppe,"
                                     "receivables,inventory"))
    print(f"fin_q3m {len(q):,}행 · {q['code'].nunique():,}종목")
    q["qi"] = q["bsns_year"] * 4 + q["qn"]

    recs = []
    for code, g in q.groupby("code"):
        if code not in uni:
            continue
        m = metrics(g)
        if m is None:
            continue
        u = uni[code]
        excl = None
        kind = (corp.get(code) or {}).get("fin_kind")
        if kind:
            excl = {"financial": "금융업", "fin_holding": "금융지주", "non_dec_fy": "12월 결산 아님"}.get(kind, kind)
        op = (audit.get(code) or {}).get("detail") or {}
        if not excl and op.get("opinion") and "적정" != op["opinion"].replace("의견", "").strip():
            excl = f"감사의견 {op['opinion']}"
        # 최근 1년 공시 사건과 감사 관련 경고 — 점수엔 안 넣고 표시만
        m["flags"] += [f if len(d) == 1 else f"{f} {len(d)}회" for f, d in (evf.get(code) or {}).items()]
        # 감사인 교체는 표시하지 않는다 — 주기적 지정제 때문에 한 해 29%가 바뀐다(2026-10 실측 293/1,011).
        # 그만큼 흔하면 경고가 아니라 소음이다. 데이터(dart_event.detail)는 점검 카드용으로 남긴다.
        if op.get("going_concern"):
            m["flags"].append("계속기업")
        recs.append({"code": code, "name": u.get("name"), "market": u.get("market"),
                     "mktcap": u.get("mktcap"), "excluded": excl, **m})
    df = pd.DataFrame(recs)
    newest = df["qi"].max()
    late = df["qi"] < newest - STALE_Q
    df.loc[late, "flags"] = df.loc[late, "flags"].apply(lambda f: f + ["보고서지연"])

    ok = df["excluded"].isna()
    e = df[ok]
    axes = {
        "s_growth": [pct(e["rev_g"]), pct(e["op_g"])],
        "s_profit": [pct(e["roic"]), pct(e["op_margin"])],
        "s_cash": [pct(e["fcf_margin"]), pct(e["cash_conv"])],
        "s_health": [pct(e["debt_ratio"], higher=False), pct(e["int_cov"])],
    }
    for k, parts in axes.items():
        df.loc[ok, k] = pd.concat(parts, axis=1).mean(axis=1, skipna=True)
    ax = df.loc[ok, list(axes)]
    enough = ax.notna().sum(axis=1) >= 3                    # 네 축 중 셋은 있어야 점수를 준다
    # 빈 축은 50(중간)으로 채워 평균한다. 그냥 빼고 평균하면 빈 칸이 오히려 유리해진다 — 상장 2년이 안 돼
    # 성장률이 없는 종목이 나머지 세 축만으로 상위권을 휩쓸었다(실측: 첫 채점 상위 30 중 8종목).
    df.loc[ok, "score"] = ax.fillna(50).mean(axis=1).where(enough)
    df.loc[ok & df["score"].isna(), "excluded"] = "데이터 부족"
    ranked = df[df["score"].notna()].sort_values("score", ascending=False).copy()
    ranked["rank"] = range(1, len(ranked) + 1)
    df.loc[ranked.index, "rank"] = ranked["rank"]

    print(f"채점 {len(ranked):,}종목 · 제외 {df['excluded'].notna().sum():,} "
          f"({df['excluded'].value_counts().to_dict()})")
    show = ranked.head(30)
    for _, r in show.iterrows():
        f = lambda v, p=True: "  —  " if v is None or pd.isna(v) else (f"{v * 100:5.0f}%" if p else f"{v:5.0f}")
        print(f"  {int(r['rank']):3d} {str(r['name'])[:10]:<11} {r['score']:5.1f} | 성장 {r['s_growth']:4.0f} "
              f"수익 {r['s_profit']:4.0f} 현금 {r['s_cash']:4.0f} 건전 {r['s_health']:4.0f} | "
              f"매출 {f(r['rev_g'])} ROIC {f(r['roic'])} FCF마진 {f(r['fcf_margin'])} 부채 {f(r['debt_ratio'], False)}% "
              f"{' '.join(r['flags'])}")
    if a.dry:
        print("\n[dry] 적재 건너뜀")
        return

    cols = ["code", "name", "market", "fiscal_q", "mktcap", "rev_g", "op_g", "roic", "op_margin", "fcf_margin",
            "cash_conv", "debt_ratio", "int_cov", "s_growth", "s_profit", "s_cash", "s_health", "score", "rank",
            "flags", "excluded"]
    out = df[cols].astype(object).where(df[cols].notna(), None).to_dict("records")
    for r in out:
        r["rank"] = int(r["rank"]) if r["rank"] is not None else None
        r["updated_at"] = run_at
    for i in range(0, len(out), 500):
        sb.table("fin_score").upsert(out[i:i + 500], on_conflict="code").execute()
    sb.table("fin_score").delete().lt("updated_at", run_at).execute()     # 유니버스에서 빠진 종목 정리
    print(f"fin_score {len(out):,}행 적재")

    # watch 채우기 — 점수 자리(180)가 빌 때만 위에서부터. 이미 있는 종목은 상태를 건드리지 않는다.
    w = {x["code"]: x for x in load("watch", "code,source,status")}
    taken = sum(1 for x in w.values() if x["source"] == "score" and x["status"] != "drop")
    add = []
    for _, r in ranked.iterrows():
        if taken + len(add) >= SCORE_SLOTS:
            break
        if r["code"] not in w:
            add.append({"code": r["code"], "name": r["name"], "source": "score", "status": "active"})
    if add:
        sb.table("watch").insert(add).execute()
    outside = [r["code"] for _, r in ranked.head(SCORE_SLOTS).iterrows() if r["code"] not in w and
               r["code"] not in {x["code"] for x in add}]
    print(f"watch: 점수 자리 {taken} → {taken + len(add)} (새로 {len(add)})"
          + (f" · 상위 {SCORE_SLOTS} 중 자리가 없어 못 들어간 {len(outside)}종목" if outside else ""))


if __name__ == "__main__":
    main()
