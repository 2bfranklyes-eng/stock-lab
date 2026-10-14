# dart_events.py — 공시 사건 → dart_event (사업보고서 점검 1단계)
#
# 숫자(fin_q)가 '회사가 얼마나 버나'라면 사건은 '주주에게 무슨 일이 생겼나'다. 둘 다 정형 데이터라
# AI 없이 코드로 모은다. 점수에는 넣지 않고 경고 표시로만 쓴다(fin_score.py 가 flags 로 붙인다).
#   1) 주요사항보고서 — 전 종목. 제목으로 분류한다(CB·BW·유상증자·자사주·감자·합병·부실 …)
#      2주 291건(2026-10 실측)이라 1년치도 75콜 남짓이다.
#   2) 감사의견 — 유니버스 종목의 최신 사업보고서(회사당 1콜). 비적정은 후보에서 뺀다(사용자 확정).
#      감사인 교체·계속기업 불확실성은 경고 표시.
#
# 실행:  python dart_events.py              → 최근 14일 + 아직 없는 감사의견 (주 1회 크론)
#        python dart_events.py --days 365   → 첫 적재: 1년치
import argparse
import json
import re
import sys
from datetime import date, timedelta

import fin_hist
from dart import sb, corp_map, DartBlocked
from fin_hist import get, DailyLimit
from fin_score import load

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

# 제목 → 종류. 위에서부터 먼저 맞는 것. '자기전환사채만기전취득'은 CB 발행이 아니라 회수라 따로 둔다.
KINDS = [
    ("자기전환사채", "cb_buyback"),
    ("전환사채권발행결정", "cb"),
    ("신주인수권부사채권발행결정", "bw"),
    ("교환사채권발행결정", "eb"),
    ("유무상증자결정", "rights"),
    ("유상증자결정", "rights"),
    ("무상증자결정", "bonus"),
    ("감자결정", "reduction"),
    ("자기주식취득", "buyback"),            # 취득결정 · 취득신탁계약체결결정
    ("자기주식처분결정", "buyback_sell"),
    ("주식소각결정", "cancel"),
    ("회사합병결정", "merger"),
    ("회사분할", "split"),                  # 분할결정 · 분할합병결정
    ("주식교환", "merger"),
    ("부도발생", "distress"),
    # 영업정지는 '부실'과 떼어 둔다 — 제약사의 일부 품목 판매정지처럼 회사 전체로는 작은 처분이 대부분이다
    # (실측: JW중외제약 2026-04 영업정지가 부실로 묶여 빨간 경고가 됐다). 비중은 원문에서 확인.
    ("영업정지", "suspension"),
    ("회생절차개시", "distress"),
    ("해산사유발생", "distress"),
    ("채권은행등의관리절차", "distress"),
    ("소송등의제기", "lawsuit"),
    ("양수결정", "asset_buy"),
    ("양도결정", "asset_sell"),
]


def classify(nm):
    t = re.sub(r"\s+", "", nm or "")
    for key, kind in KINDS:
        if key in t:
            return kind
    return None


def scan(days, today):
    """주요사항보고서(B) 전 종목. corp_code 없이 물으면 기간이 3개월로 제한돼 창을 나눈다."""
    out, end = [], today
    start = today - timedelta(days=days)
    while end >= start:
        bgn = max(start, end - timedelta(days=89))
        page = 1
        while True:
            j = get("list.json", bgn_de=bgn.strftime("%Y%m%d"), end_de=end.strftime("%Y%m%d"),
                    pblntf_ty="B", page_no=str(page), page_count="100")
            for x in j.get("list", []):
                sc, kind = (x.get("stock_code") or "").strip(), classify(x.get("report_nm"))
                if sc and kind:                    # 상장사 + 아는 종류만
                    d = x["rcept_dt"]
                    out.append({"rcept_no": x["rcept_no"], "rcept_dt": f"{d[:4]}-{d[4:6]}-{d[6:]}",
                                "code": sc, "corp_code": x["corp_code"], "corp_name": x["corp_name"],
                                "kind": kind, "report_nm": x["report_nm"]})
            if page >= int(j.get("total_page") or 1):
                break
            page += 1
        end = bgn - timedelta(days=1)
    return out


def audit_year(today):
    """가장 최근에 나왔어야 할 사업보고서 연도. 사업보고서 기한은 3월 말이다."""
    return today.year - 1 if today > date(today.year, 4, 5) else today.year - 2


def audits(today):
    """감사의견을 받아 100건마다 바로 적재한다(중간에 한도에 걸려도 거기까지 남게). 적재 건 목록을 돌려준다."""
    year = audit_year(today)
    uni = fin_hist.universe()
    cmap = corp_map()
    fin = {c["code"] for c in load("dart_corp", "code,fin_kind") if c.get("fin_kind")}
    have = {(e["code"], (e.get("detail") or {}).get("year")) for e in load("dart_event", "code,detail", kind="audit")}
    todo = [u for u in uni if cmap.get(u["code"]) and u["code"] not in fin and (u["code"], year) not in have]
    print(f"감사의견 {year}년: {len(todo)}종목 조회")
    out, buf = [], []
    for i, u in enumerate(todo, 1):
        if len(buf) >= 100:
            put(buf)
            buf = []
        j = get("accnutAdtorNmNdAdtOpinion.json", corp_code=cmap[u["code"]], bsns_year=str(year), reprt_code="11011")
        rows = j.get("list") or []
        cur = [r for r in rows if "당기" in (r.get("bsns_year") or "")]
        prv = [r for r in rows if "전기" in (r.get("bsns_year") or "")]
        if not cur:
            continue
        ops = [(r.get("adt_opinion") or "").strip() for r in cur if (r.get("adt_opinion") or "").strip() not in ("", "-")]
        # 연결·별도가 따로 나오면 나쁜 쪽을 쓴다 — '적정'이 아닌 게 하나라도 있으면 그게 의견이다
        bad = [o for o in ops if o.replace("의견", "").strip() != "적정"]
        text = " ".join((r.get("emphs_matter") or "") + " " + (r.get("adt_reprt_spcmnt_matter") or "") for r in cur)
        aud, paud = (cur[0].get("adtor") or "").strip(), (prv[0].get("adtor") or "").strip() if prv else ""
        rno = cur[0]["rcept_no"]
        row = {"rcept_no": rno, "rcept_dt": f"{rno[:4]}-{rno[4:6]}-{rno[6:8]}",
               "code": u["code"], "corp_code": cmap[u["code"]], "corp_name": u.get("name"), "kind": "audit",
               "report_nm": f"감사의견 {year}",
               "detail": {"year": year, "opinion": (bad or ops or [""])[0], "auditor": aud, "prev_auditor": paud,
                          "auditor_changed": bool(paud and aud and paud != aud),
                          "going_concern": "계속기업" in text}}
        out.append(row)
        buf.append(row)
        if i % 200 == 0:
            print(f"  {i}/{len(todo)}", flush=True)
    put(buf)
    return out


def put(rows):
    for i in range(0, len(rows), 500):
        sb.table("dart_event").upsert(rows[i:i + 500], on_conflict="rcept_no").execute()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=int, default=14)
    a = ap.parse_args()
    today = date.today()
    try:
        ev = scan(a.days, today)
        put(ev)
        kinds = {}
        for e in ev:
            kinds[e["kind"]] = kinds.get(e["kind"], 0) + 1
        print(f"주요사항보고 {a.days}일: {len(ev):,}건 {dict(sorted(kinds.items(), key=lambda x: -x[1]))}")
        au = audits(today)
        # 의견 칸이 빈 응답도 온다(2026-10 실측 9건) — 그건 '비적정'이 아니라 '모름'이다
        nb = [e for e in au if e["detail"]["opinion"] and e["detail"]["opinion"].replace("의견", "").strip() != "적정"]
        blank = sum(1 for e in au if not e["detail"]["opinion"])
        print(f"감사의견 {len(au)}건 적재 · 비적정 {len(nb)} · 의견 칸 빈 응답 {blank} · 감사인 교체 "
              f"{sum(e['detail']['auditor_changed'] for e in au)} · 계속기업 {sum(e['detail']['going_concern'] for e in au)}")
    except (DailyLimit, DartBlocked) as e:
        print(f"⚠️ DART 중단({e}) — 여기까지 저장됨. 다음 실행이 이어받는다")


if __name__ == "__main__":
    main()
