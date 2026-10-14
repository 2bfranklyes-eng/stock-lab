# review.py — 관심종목 기록 + 분기 자동 체크 (사업보고서 점검 2단계)
#
# 판정은 사람이 한다. 웹에 입력칸을 두려면 로그인이 필요해서(사이트가 공개라 아무나 쓰게 된다)
# 당분간은 사용자가 Claude Code 대화로 말하면 이 명령으로 남긴다(2026-10-15 사용자 결정).
#
#   python review.py status 삼성전자 관찰 --memo "메모리 가격 정점 우려"   → watch.status (+메모)
#   python review.py note 삼성전자 --thesis "…" --kpi "HBM 매출 비중" --kill "영업이익률 30% 아래"
#   python review.py add 005380 --thesis "…"                               → 직접 추가 (20자리)
#   python review.py verdict 삼성전자 2026-09-30 유지 --memo "…"           → review.verdict + watch.status
#   python review.py checks [--fq 2026-06-30] [종목…]                       → 숫자 자동 체크 → review.checks
#   python review.py load <폴더>                                            → AI 요약 JSON → review.summary·extracted
#
# 자동 체크는 '확인할 것'을 고르는 일이지 판정이 아니다. fail 이 떠도 판정은 사람이 한다.
import argparse
import glob
import json
import sys
from datetime import date, datetime, timezone

from dart import sb
from fin_score import load

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

ST = {"유지": "active", "관찰": "watch", "제외": "drop"}      # watch.status
VD = {"유지": "keep", "관찰": "watch", "제외": "drop"}        # review.verdict
MANUAL_SLOTS = 20
DILUTE = {"cb": "CB 발행", "bw": "BW 발행", "eb": "EB 발행", "rights": "유상증자"}
BAD_EV = {"distress": "부실 공시", "reduction": "감자", "suspension": "영업정지"}
GOOD_EV = {"buyback": "자사주 취득", "cancel": "주식 소각"}


def now():
    return datetime.now(timezone.utc).isoformat()


def find(q):
    """종목코드 또는 이름(정확히 → 포함 순)으로 한 종목을 찾는다. 여럿이면 후보를 보여주고 멈춘다 —
    '삼성'으로 삼성중공업에 판정이 들어가면 되돌리기 어렵다."""
    names = {}
    for r in load("fin_score", "code,name") + load("watch", "code,name") + load("dart_corp", "code,name"):
        if r.get("code") and r.get("name"):
            names[r["code"]] = r["name"]
    if q in names:
        return q, names[q]
    exact = [c for c, n in names.items() if n == q]
    hits = exact or [c for c, n in names.items() if q.lower() in n.lower()]
    if len(hits) == 1:
        return hits[0], names[hits[0]]
    if not hits:
        sys.exit(f"'{q}' 종목을 못 찾았어요")
    sys.exit(f"'{q}' 후보가 여럿이에요: " + ", ".join(f"{names[c]}({c})" for c in hits[:10]))


def cmd_status(a):
    code, name = find(a.who)
    w = sb.table("watch").select("*").eq("code", code).execute().data
    if not w:
        sys.exit(f"{name}은 관심종목이 아니에요 — 먼저 add 로 넣으세요")
    upd = {"status": ST[a.state], "updated_at": now()}
    if a.memo:
        upd["memo"] = ((w[0].get("memo") or "") + f"\n[{date.today()}] {a.memo}").strip()
    sb.table("watch").update(upd).eq("code", code).execute()
    print(f"{name}({code}) → {a.state}" + (f" · 메모 추가" if a.memo else ""))


def cmd_note(a):
    code, name = find(a.who)
    upd = {k: v for k, v in {"thesis": a.thesis, "kpi": a.kpi, "kill": a.kill}.items() if v}
    w = sb.table("watch").select("memo").eq("code", code).execute().data
    if not w:
        sys.exit(f"{name}은 관심종목이 아니에요 — 먼저 add 로 넣으세요")
    if a.memo:
        upd["memo"] = ((w[0].get("memo") or "") + f"\n[{date.today()}] {a.memo}").strip()
    if not upd:
        sys.exit("바꿀 내용이 없어요 (--thesis / --kpi / --kill / --memo)")
    upd["updated_at"] = now()
    sb.table("watch").update(upd).eq("code", code).execute()
    print(f"{name}({code}) 기록: {', '.join(k for k in upd if k != 'updated_at')}")


def cmd_add(a):
    code, name = find(a.who)
    w = sb.table("watch").select("code,status").eq("code", code).execute().data
    if w:
        sys.exit(f"{name}은 이미 관심종목이에요 (상태 {w[0]['status']})")
    manual = sb.table("watch").select("code").eq("source", "manual").neq("status", "drop").execute().data
    if len(manual) >= MANUAL_SLOTS:
        sys.exit(f"직접 추가 자리 {MANUAL_SLOTS}개가 다 찼어요 — 하나를 '제외'하면 자리가 납니다")
    sb.table("watch").insert({"code": code, "name": name, "source": "manual", "status": "active",
                              "thesis": a.thesis, "memo": a.memo}).execute()
    print(f"{name}({code}) 직접 추가 ({len(manual) + 1}/{MANUAL_SLOTS})")


def cmd_verdict(a):
    code, name = find(a.who)
    fq = a.fq
    row = {"code": code, "fiscal_q": fq, "verdict": VD[a.state], "reviewed_at": now()}
    if a.memo:
        row["memo"] = a.memo
    sb.table("review").upsert(row, on_conflict="code,fiscal_q").execute()
    # 판정이 곧 현재 상태다 — 둘이 어긋나면 목록과 기록이 다른 말을 한다
    sb.table("watch").update({"status": ST[a.state], "updated_at": now()}).eq("code", code).execute()
    print(f"{name}({code}) {fq} 판정: {a.state}")


# ── 숫자 자동 체크 ────────────────────────────────────────────────────────
def _ttm(by, qi, col):
    vals = [by.get(i, {}).get(col) for i in range(qi - 3, qi + 1)]
    return None if any(v is None for v in vals) else sum(vals)


def _g(a, b):
    return None if a is None or b is None or b == 0 else (a - b) / abs(b)


def _p(v):
    return "—" if v is None else f"{v * 100:+.0f}%"


def _w(v):
    return f"{v / 1e12:,.2f}조" if abs(v) >= 1e12 else f"{v / 1e8:,.0f}억"


def checks_for(rows, events, fq=None):
    """한 종목의 분기 행들 → (기준 분기, rcept_no, 체크 목록). 결과는 pass / warn / fail / info."""
    by = {r["bsns_year"] * 4 + r["qn"]: r for r in rows}
    have = [i for i, r in by.items() if r.get("revenue") is not None]
    if not have:
        return None, None, []
    if fq:
        cand = [i for i, r in by.items() if r["fiscal_q"] == fq]
        if not cand:
            return None, None, []
        qi = cand[0]
    else:
        qi = max(have)
    cur, prev = by[qi], by.get(qi - 1)
    T = lambda col, back=0: _ttm(by, qi - back, col)
    out = []

    def add(rule, result, value, note=""):
        out.append({"rule": rule, "result": result, "value": value, "note": note})

    rev, rev_y, rev_p, rev_py = T("revenue"), T("revenue", 4), T("revenue", 1), T("revenue", 5)
    g, gp = _g(rev, rev_y), _g(rev_p, rev_py)
    if g is not None:
        # 위반은 '2분기 연속 감소 + 최근 감소폭 3% 넘음'. -0.3%가 두 번 이어진 걸 위반으로 치면 경보가 흔해진다
        # (실측: 클리오 -0%가 위반으로 찍혔다)
        two = g < 0 and gp is not None and gp < 0
        add("매출(최근 4분기) 전년 대비", "fail" if two and g < -0.03 else "warn" if g < 0 else "pass",
            _p(g), "2분기 연속 감소" if two else "")
    op, op_y = T("op_income"), T("op_income", 4)
    if op is not None:
        og = _g(op, op_y)
        add("영업이익(최근 4분기)", "fail" if op < 0 else "warn" if og is not None and og < -0.2 else "pass",
            f"{_w(op)} ({_p(og)})", "적자" if op < 0 else "")
        if rev and rev_y:
            dm = (op / rev - op_y / rev_y) * 100 if op_y is not None else None
            if dm is not None:
                add("영업이익률 변화(1년)", "warn" if dm < -3 else "pass", f"{dm:+.1f}%p")
    ocf, capex, net = T("ocf"), T("capex"), T("net_income")
    if ocf is not None and capex is not None:
        add("FCF(최근 4분기)", "warn" if ocf - capex < 0 else "pass", _w(ocf - capex))
    if ocf is not None and net is not None:
        if net > 0:
            add("현금 전환(영업CF÷순이익)", "warn" if ocf / net < 0.5 else "pass", f"{ocf / net:.2f}")
        else:
            add("현금 전환(영업CF÷순이익)", "info", "순이익 적자")
    eq, liab = cur.get("equity"), cur.get("liabilities")
    if eq is not None and liab is not None:
        if eq <= 0:
            add("부채비율", "fail", "자본잠식")
        else:
            dr = liab / eq * 100
            y = by.get(qi - 4)
            dy = (dr - y["liabilities"] / y["equity"] * 100) if y and y.get("equity") and y.get("liabilities") is not None \
                and y["equity"] > 0 else None
            add("부채비율", "warn" if dr > 200 or (dy is not None and dy > 50) else "pass",
                f"{dr:.0f}%" + (f" ({dy:+.0f}%p)" if dy is not None else ""))
    intr = T("interest")
    if op is not None and intr is not None:
        if intr <= 0:
            add("이자보상배율", "pass", "이자 지급 없음")
        else:
            cov = op / intr
            add("이자보상배율", "fail" if cov < 1 else "warn" if cov < 3 else "pass", f"{cov:.1f}배")
    y = by.get(qi - 4)
    for k, nm in (("receivables", "매출채권"), ("inventory", "재고")):
        if y and cur.get(k) is not None and y.get(k) and g is not None and y[k] > 0:
            gap = (cur[k] / y[k] - 1) - g
            add(f"{nm} 증가 vs 매출 증가", "warn" if gap > 0.2 else "pass", f"{gap * 100:+.0f}%p")
    if prev and prev.get("fs_div") and prev["fs_div"] != cur.get("fs_div"):
        add("연결/별도 기준", "info", f"{prev['fs_div']} → {cur.get('fs_div')}", "전 분기와 비교가 어긋날 수 있다")
    # 이번 분기 공시 사건: 직전 보고서 공시일 다음 날부터 이번 보고서 공시일까지
    lo, hi = (prev or {}).get("rcept_dt") or "0000", cur.get("rcept_dt") or "9999"
    seen = set()
    for e in events:
        d = e["rcept_dt"]
        if not (lo < d <= hi) or (e.get("report_nm") or "").startswith("["):
            continue
        k = e["kind"]
        tag = (k, d)
        if tag in seen:
            continue
        seen.add(tag)
        if k in DILUTE:
            add("공시: " + DILUTE[k], "warn", d, "주식 희석")
        elif k in BAD_EV:
            add("공시: " + BAD_EV[k], "fail" if k == "distress" else "warn", d)
        elif k in GOOD_EV:
            add("공시: " + GOOD_EV[k], "info", d, "주주환원")
    return cur["fiscal_q"], cur.get("rcept_no"), out


def cmd_checks(a):
    codes = [find(x)[0] for x in a.codes] if a.codes else \
        [w["code"] for w in load("watch", "code,status") if w["status"] != "drop"]
    n, tally = 0, {"pass": 0, "warn": 0, "fail": 0, "info": 0}
    q3m, evs = {}, {}
    for r in load("fin_q3m", "*"):                      # 종목마다 부르면 180×2번 — 한 번에 받아 나눈다
        q3m.setdefault(r["code"], []).append(r)
    for e in load("dart_event", "code,kind,rcept_dt,report_nm"):
        evs.setdefault(e["code"], []).append(e)
    for code in codes:
        fq, rno, ck = checks_for(q3m.get(code, []), evs.get(code, []), a.fq)
        if not fq:
            continue
        sb.table("review").upsert({"code": code, "fiscal_q": fq, "rcept_no": rno, "checks": ck},
                                  on_conflict="code,fiscal_q").execute()
        for c in ck:
            tally[c["result"]] += 1
        n += 1
        if a.codes:
            print(f"{code} {fq}: " + " · ".join(f"{c['rule']} {c['result']} {c['value']}" for c in ck))
    print(f"자동 체크 {n}종목 · " + " · ".join(f"{k} {v}" for k, v in tally.items()))


def cmd_load(a):
    files = sorted(glob.glob(f"{a.dir}/*.json"))
    n = 0
    for p in files:
        j = json.load(open(p, encoding="utf-8"))
        row = {"code": j["code"], "fiscal_q": j["fiscal_q"], "summary": j.get("summary"),
               "extracted": j.get("extracted")}
        sb.table("review").upsert(row, on_conflict="code,fiscal_q").execute()
        n += 1
    print(f"AI 요약 {n}건 적재")


def main():
    ap = argparse.ArgumentParser()
    sp = ap.add_subparsers(dest="cmd", required=True)
    s = sp.add_parser("status")
    s.add_argument("who"); s.add_argument("state", choices=list(ST)); s.add_argument("--memo")
    s = sp.add_parser("note")
    s.add_argument("who"); s.add_argument("--thesis"); s.add_argument("--kpi"); s.add_argument("--kill")
    s.add_argument("--memo")
    s = sp.add_parser("add")
    s.add_argument("who"); s.add_argument("--thesis"); s.add_argument("--memo")
    s = sp.add_parser("verdict")
    s.add_argument("who"); s.add_argument("fq"); s.add_argument("state", choices=list(VD)); s.add_argument("--memo")
    s = sp.add_parser("checks")
    s.add_argument("--fq"); s.add_argument("codes", nargs="*")
    s = sp.add_parser("load")
    s.add_argument("dir")
    a = ap.parse_args()
    {"status": cmd_status, "note": cmd_note, "add": cmd_add, "verdict": cmd_verdict,
     "checks": cmd_checks, "load": cmd_load}[a.cmd](a)


if __name__ == "__main__":
    main()
