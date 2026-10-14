# fin_hist.py — 분기별 재무 이력 → fin_q (사업보고서 점검 1단계)
#
# 왜 dart.py 와 따로 두나: dart.py(dart_fin)는 종목당 '최신 분기 1행'을 덮어써서 구루 채점에 쓴다.
# 점검은 "지난 분기 대비 무엇이 바뀌었나"가 핵심이라 보고서 한 건을 한 행으로 쌓아야 한다.
# 같은 API(fnlttSinglAcntAll)라서 요청 간격·차단 처리는 dart.py 것을 그대로 빌린다.
#
# 대상: 코스피·코스닥 보통주 중 시총 500억 이상 · 월평균 하루 거래대금 5억 이상(factor.py 와 같은 기준),
#      금융업 제외(사용자 결정). 업종코드 64·65·66 은 빼되 64992(지주회사)는 재무제표 모양으로 가른다 —
#      금융지주(KB·신한)와 일반 지주(LG·SK)가 같은 코드를 쓰는데, 금융사 재무상태표엔 유동자산 칸이 없다.
#      12월 결산만 담는다(결산월이 다르면 분기말 계산이 어긋난다).
#
# 값은 보고서가 주는 그대로 둔다. 손익은 연초부터 누적(사업보고서는 연간), 현금흐름표는 원래 누적만 준다
# (2026-10 실측: 손익은 3개월·누적 두 칸, 현금흐름은 누적 한 칸). 3개월 값은 fin_q3m 뷰가 뺄셈으로 만든다.
#
# 실행:  python fin_hist.py              → 최근 14일 정기공시 + 처음 보는 종목 백필 (주 1회 크론)
#        python fin_hist.py --backfill   → 유니버스 전체 2023 1분기~. 이미 있는 분기는 건너뛴다(재개 가능)
#        python fin_hist.py --dry 005930 → 적재 없이 출력
# DART 는 하루 2만 건 한도다(넘으면 status 020). 걸리면 거기까지 저장하고 멈춘다 — 다음 날 다시 돌리면 이어진다.
import argparse
import json
import re
import sys
import time
from datetime import date, datetime, timedelta, timezone

import dart                                   # fetch(간격·재시도·차단 감지)·corp_map·num 재사용
from dart import sb, fetch, num, corp_map, DartBlocked

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

START_YEAR = 2023                             # 2023 1분기부터 — 2023 분기 3개월 값이 다 나와야 TTM 이 2023말부터 선다
MIN_CAP = 5e10                                # 시총 500억 (factor.py 와 같다)
MIN_TVAL = 5e8                                # 월평균 하루 거래대금 5억
QEND = {"11013": (3, 31), "11012": (6, 30), "11014": (9, 30), "11011": (12, 31)}
DEADLINE = {"11013": 45, "11012": 45, "11014": 45, "11011": 90}     # 분기말 뒤 법정 제출기한(일)
NM_REPRT = {"03": "11013", "06": "11012", "09": "11014", "12": "11011"}
FIN_KSIC = ("64", "65", "66")                 # 금융 및 보험업
HOLDING = "64992"                             # 지주회사 — 금융지주와 일반 지주가 섞여 있다

# 손익·현금흐름(누적). (표 종류, account_id 후보, 계정명 폴백)
# 계정명 폴백은 회사가 자체 코드(entity…)를 쓴 경우를 위한 것이다 — 이름은 서식 표준이라 더 고르다.
FLOW = {
    "revenue_ytd": (("IS", "CIS"), ["ifrs-full_Revenue", "ifrs-full_RevenueFromContractsWithCustomers"],
                    ["매출액", "수익(매출액)", "영업수익"]),
    "op_income_ytd": (("IS", "CIS"), ["dart_OperatingIncomeLoss", "ifrs-full_ProfitLossFromOperatingActivities"],
                      ["영업이익", "영업이익(손실)"]),
    "net_income_ytd": (("IS", "CIS"), ["ifrs-full_ProfitLoss"], ["당기순이익", "당기순이익(손실)", "분기순이익",
                                                                 "분기순이익(손실)", "반기순이익", "반기순이익(손실)"]),
    "ocf_ytd": (("CF",), ["ifrs-full_CashFlowsFromUsedInOperatingActivities"],
                ["영업활동현금흐름", "영업활동으로인한현금흐름", "영업활동으로인한순현금흐름"]),
    "capex_ppe": (("CF",), ["ifrs-full_PurchaseOfPropertyPlantAndEquipmentClassifiedAsInvestingActivities"],
                  ["유형자산의취득", "유형자산취득"]),
    "capex_int": (("CF",), ["ifrs-full_PurchaseOfIntangibleAssetsClassifiedAsInvestingActivities"],
                  ["무형자산의취득", "무형자산취득"]),
    "interest_ytd": (("CF",), ["ifrs-full_InterestPaidClassifiedAsOperatingActivities",
                               "ifrs-full_InterestPaidClassifiedAsFinancingActivities"],
                     ["이자의지급", "이자지급", "이자의지급(영업)", "이자지급액"]),
}
# 재무상태표(분기말 잔액). 매출채권은 회사마다 '매출채권' / '매출채권및기타채권' 으로 갈린다(실측).
BS = {
    "assets": (["ifrs-full_Assets"], ["자산총계"]),
    "liabilities": (["ifrs-full_Liabilities"], ["부채총계"]),
    "equity": (["ifrs-full_Equity"], ["자본총계"]),
    "cur_assets": (["ifrs-full_CurrentAssets"], ["유동자산"]),
    "cur_liabilities": (["ifrs-full_CurrentLiabilities"], ["유동부채"]),
    "ppe": (["ifrs-full_PropertyPlantAndEquipment"], ["유형자산"]),
    "cash": (["ifrs-full_CashAndCashEquivalents"], ["현금및현금성자산"]),
    "receivables": (["ifrs-full_CurrentTradeReceivables", "dart_ShortTermTradeReceivable",
                     "ifrs-full_TradeAndOtherCurrentReceivables"], ["매출채권", "매출채권및기타채권"]),
    "inventory": (["ifrs-full_Inventories"], ["재고자산"]),
}


class DailyLimit(Exception):
    """DART 하루 2만 건 한도 초과(status 020). 오늘은 더 받아봐야 전부 실패한다."""


def get(path, **params):
    j = json.loads(fetch(path, **params))
    if j.get("status") == "020":
        raise DailyLimit(j.get("message", ""))
    return j


# ── 대상 종목 ─────────────────────────────────────────────────────────────
def universe():
    """pit_monthly 최신 달(그 시점 상장 전 종목 · 시총 · 거래대금)에서 거른다.
    DB 가 비어 있으면(보관 직후) 보관 파일의 최신 달을 쓴다."""
    r = sb.table("pit_monthly").select("ym").order("ym", desc=True).limit(1).execute().data
    if r:
        ym, rows, off = r[0]["ym"], [], 0
        while True:
            d = (sb.table("pit_monthly").select("code,name,market,mktcap,tval_avg")
                 .eq("ym", ym).range(off, off + 999).execute().data)
            rows += d
            off += 1000
            if len(d) < 1000:
                break
    else:
        import archive
        df = archive.load_pit_archive()
        ym = df["ym"].max()
        rows = df[df["ym"] == ym][["code", "name", "market", "mktcap", "tval_avg"]].to_dict("records")
    out = [x for x in rows
           if x["code"].endswith("0")                       # 보통주 (우선주는 끝자리 5·7·9·K·L·M)
           and x["market"] in ("KOSPI", "KOSDAQ")
           and (x.get("mktcap") or 0) >= MIN_CAP and (x.get("tval_avg") or 0) >= MIN_TVAL]
    print(f"유니버스 {ym}: 전체 {len(rows):,} → 보통주·시총·거래대금 통과 {len(out):,}")
    return out


def corp_info(uni, cmap):
    """종목 → dart_corp 행. 없거나 30일 지난 것만 company.json 으로 채운다(종목당 1콜)."""
    have, off = {}, 0
    while True:
        d = sb.table("dart_corp").select("*").range(off, off + 999).execute().data
        have.update({x["corp_code"]: x for x in d})
        off += 1000
        if len(d) < 1000:
            break
    stale = (datetime.now(timezone.utc) - timedelta(days=30)).isoformat()
    need = [u for u in uni if cmap.get(u["code"])
            and (cmap[u["code"]] not in have or (have[cmap[u["code"]]].get("updated_at") or "") < stale)]
    if need:
        print(f"기업 정보 {len(need)}건 조회 (업종·결산월)")
    buf = []
    for i, u in enumerate(need, 1):
        cc = cmap[u["code"]]
        j = get("company.json", corp_code=cc)
        ind, mt = (j.get("induty_code") or "").strip(), (j.get("acc_mt") or "").strip()
        kind = have.get(cc, {}).get("fin_kind")              # 재무제표로 판정한 fin_holding 은 유지
        if ind.startswith(FIN_KSIC) and ind != HOLDING:
            kind = "financial"
        elif mt and mt != "12":
            kind = "non_dec_fy"
        row = {"corp_code": cc, "code": u["code"], "name": u["name"], "induty_code": ind,
               "acc_mt": mt, "fin_kind": kind, "updated_at": datetime.now(timezone.utc).isoformat()}
        have[cc] = row
        buf.append(row)
        if len(buf) >= 100 or i == len(need):
            sb.table("dart_corp").upsert(buf, on_conflict="corp_code").execute()
            buf = []
            print(f"  {i}/{len(need)}", flush=True)
    return {u["code"]: have[cmap[u["code"]]] for u in uni if cmap.get(u["code"]) in have}


# ── 보고서 한 건 → 행 ─────────────────────────────────────────────────────
def _key(nm):
    return re.sub(r"\s+", "", nm or "")


def _pick(rows, sjs, ids, names):
    for sj in sjs:                                 # 표를 못박는다 — 같은 id 가 SCE(자본변동표)에 쪼개져 나온다
        for aid in ids:
            for r in rows:
                if r.get("sj_div") == sj and r.get("account_id") == aid:
                    return r
    for sj in sjs:
        for r in rows:
            if r.get("sj_div") == sj and _key(r.get("account_nm")) in names:
                return r
    return None


def parse(rows, reprt):
    v = {}
    for k, (sjs, ids, names) in FLOW.items():
        r = _pick(rows, sjs, ids, names)
        if r is None:
            v[k] = None
        elif sjs == ("CF",) or reprt in ("11013", "11011"):
            v[k] = num(r.get("thstrm_amount"))     # 현금흐름표는 원래 누적 한 칸 · 1분기는 3개월=누적 · 사업은 연간
        else:
            # 반기·3분기 손익은 누적 칸만 믿는다. 비었다고 '당기' 칸(3개월)으로 메우면 뷰가 그걸 누적으로
            # 알고 빼서 엉뚱한 분기 값이 나온다 — 모르면 비워 둔다.
            v[k] = num(r.get("thstrm_add_amount"))
    for k, (ids, names) in BS.items():
        r = _pick(rows, ("BS",), ids, names)
        v[k] = num(r.get("thstrm_amount")) if r else None
    # 설비투자 = 유형 + 무형 취득. 부호는 회사마다 달라(양수/음수) 크기만 쓴다.
    ppe_buy, int_buy = v.pop("capex_ppe"), v.pop("capex_int")
    v["capex_ytd"] = None if ppe_buy is None and int_buy is None else abs(ppe_buy or 0) + abs(int_buy or 0)
    if v["interest_ytd"] is not None:
        v["interest_ytd"] = abs(v["interest_ytd"])
    return v


def report(cc, year, reprt):
    """(fs_div, 값, rcept_no) — 연결 우선, 없으면 별도. 보고서가 없으면 (None, None, None)."""
    for div in ("CFS", "OFS"):
        j = get("fnlttSinglAcntAll.json", corp_code=cc, bsns_year=str(year), reprt_code=reprt, fs_div=div)
        if j.get("status") != "000" or not j.get("list"):
            continue                                # 013 = 데이터 없음 → 별도로
        rows = j["list"]
        return div, parse(rows, reprt), rows[0].get("rcept_no")
    return None, None, None


def fq_of(year, reprt):
    m, d = QEND[reprt]
    return date(year, m, d)


def targets(today):
    """START_YEAR 1분기부터 제출기한이 지난 분기까지."""
    out = []
    for y in range(START_YEAR, today.year + 1):
        for rc in ("11013", "11012", "11014", "11011"):
            fq = fq_of(y, rc)
            if fq + timedelta(days=DEADLINE[rc]) < today:
                out.append((y, rc))
    return out


def recent_filings(days, today):
    """최근 n일 정기공시(사업·반기·분기) → {(종목코드, 연도, 보고서코드)}. 정정공시도 포함 — 숫자가 바뀌었을 수 있다."""
    out, page = set(), 1
    while True:
        j = get("list.json", bgn_de=(today - timedelta(days=days)).strftime("%Y%m%d"),
                end_de=today.strftime("%Y%m%d"), pblntf_ty="A", page_no=str(page), page_count="100")
        for x in j.get("list", []):
            m = re.search(r"(사업|반기|분기)보고서\s*\((\d{4})\.(\d{2})\)", x.get("report_nm", ""))
            sc = (x.get("stock_code") or "").strip()
            if m and sc and m.group(3) in NM_REPRT:
                out.add((sc, int(m.group(2)), NM_REPRT[m.group(3)]))
        if page >= int(j.get("total_page") or 1):
            return out
        page += 1


def existing():
    have, off = set(), 0
    while True:
        d = sb.table("fin_q").select("code,fiscal_q").range(off, off + 999).execute().data
        have |= {(x["code"], x["fiscal_q"]) for x in d}
        off += 1000
        if len(d) < 1000:
            return have


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--backfill", action="store_true")
    ap.add_argument("--dry", action="store_true")
    ap.add_argument("codes", nargs="*")
    a = ap.parse_args()
    if not dart.KEY:
        print("DART_API_KEY 없음 — 건너뜀")
        return
    today = date.today()
    uni = universe()
    if a.codes:
        uni = [u for u in uni if u["code"] in a.codes] or [{"code": c, "name": c} for c in a.codes]
    cmap = corp_map()
    info = corp_info(uni, cmap) if not a.dry else {}
    skip = {k: sum(1 for u in uni if (info.get(u["code"]) or {}).get("fin_kind") == k)
            for k in ("financial", "fin_holding", "non_dec_fy")}
    uni = [u for u in uni if cmap.get(u["code"]) and not (info.get(u["code"]) or {}).get("fin_kind")]
    print(f"대상 {len(uni):,}종목 (제외: 금융 {skip['financial']} · 금융지주 {skip['fin_holding']} "
          f"· 12월 결산 아님 {skip['non_dec_fy']})")

    have = existing() if not a.dry else set()
    tg = targets(today)
    jobs = []                                       # (종목, 연도, 보고서코드, 덮어쓰기)
    if a.backfill or a.codes:
        for u in uni:
            for y, rc in tg:
                if a.codes or (u["code"], fq_of(y, rc).isoformat()) not in have:
                    jobs.append((u, y, rc))
    else:
        by = {u["code"]: u for u in uni}
        for sc, y, rc in sorted(recent_filings(14, today)):
            if sc in by and y >= START_YEAR:
                jobs.append((by[sc], y, rc))        # 최근 공시는 있어도 다시 받는다(정정 반영)
        known = {c for c, _ in have}
        for u in uni:
            if u["code"] not in known:              # 새로 유니버스에 들어온 종목 → 이력 통째로
                jobs += [(u, y, rc) for y, rc in tg]
    print(f"받을 보고서 {len(jobs):,}건 (분기 {len(tg)}개 기준)")

    buf, saved, miss, t0 = [], 0, 0, time.time()
    fin_holding = set()

    def flush():
        nonlocal buf, saved
        if buf and not a.dry:
            sb.table("fin_q").upsert(buf, on_conflict="code,fiscal_q").execute()
        saved += len(buf)
        buf = []

    stop = None
    try:
        for i, (u, y, rc) in enumerate(jobs, 1):
            cc = cmap[u["code"]]
            if cc in fin_holding:
                continue
            div, v, rno = report(cc, y, rc)
            if div is None:
                miss += 1
                continue
            ind = (info.get(u["code"]) or {}).get("induty_code")
            if ind == HOLDING and v["cur_assets"] is None:
                # 금융지주 — 유동/비유동 구분이 없는 금융사 서식. 표시해 두고 이 회사는 더 받지 않는다.
                fin_holding.add(cc)
                if not a.dry:
                    sb.table("dart_corp").update({"fin_kind": "fin_holding"}).eq("corp_code", cc).execute()
                print(f"  금융지주로 판정: {u['code']} {u.get('name')}")
                continue
            row = {"code": u["code"], "fiscal_q": fq_of(y, rc).isoformat(), "bsns_year": y, "reprt": rc,
                   "corp_code": cc, "fs_div": div, "rcept_no": rno,
                   "rcept_dt": f"{rno[:4]}-{rno[4:6]}-{rno[6:8]}" if rno else None,
                   **v, "updated_at": datetime.now(timezone.utc).isoformat()}
            if a.dry:
                print(json.dumps(row, ensure_ascii=False))
            buf.append(row)
            if len(buf) >= 50:
                flush()
            if i % 200 == 0:
                el = time.time() - t0
                print(f"  {i:,}/{len(jobs):,} · 적재 {saved + len(buf):,} · 없음 {miss} "
                      f"· {el / 60:.0f}분 (남은 ~{el / i * (len(jobs) - i) / 60:.0f}분)", flush=True)
    except DailyLimit as e:
        stop = f"DART 하루 한도 초과({e}) — 내일 다시 돌리면 이어받습니다"
    except DartBlocked as e:
        stop = f"DART 가 연결을 끊음({e}) — 30분쯤 뒤 다시 돌리면 이어받습니다"
    finally:
        flush()
    print(f"완료: 적재 {saved:,}행 · 보고서 없음 {miss} · {(time.time() - t0) / 60:.0f}분")
    if stop:
        print(f"⚠️ {stop}")


if __name__ == "__main__":
    main()
