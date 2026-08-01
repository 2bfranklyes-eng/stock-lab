# krx.py — KRX OPEN API에서 코스피·코스닥 '진짜 회전율'(거래대금÷시가총액) 수집 → indicator_raw
#   profile.py의 G&H 감쇠가 쓰던 회전율 프록시(거래량÷직전1년 거래량합)를 실제값으로 대체하기 위함.
#   지수 API가 일자당 1콜로 거래대금·시가총액을 주지만, KOSPI 시리즈가 401이면(컨텐츠 승인 누락)
#   유가증권 일별매매정보(종목별)를 합산하는 폴백으로 같은 값을 얻는다.
#   증분 수집: indicator_raw의 마지막 날짜 다음부터 오늘까지만. 처음 실행하면 2021-08-01부터 백필.
#   사용: python krx.py            (증분 — 크론용)
#         python krx.py 20240101  (해당 날짜부터 강제 재수집)
import os
import sys
import json
import time
import urllib.request
from datetime import date, timedelta
from dotenv import load_dotenv
from supabase import create_client

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

load_dotenv()
sb = create_client(os.environ["SUPABASE_URL"], os.environ["SUPABASE_SERVICE_KEY"])
KEY = os.environ.get("KRX_API_KEY", "").strip()
BASE = "http://data-dbg.krx.co.kr/svc/apis"
BACKFILL_START = date(2021, 8, 1)          # profile.py의 5년 창과 정렬

# code → (지수 API 경로, 지수명 필터, 폴백 종목 API 경로, 메타 이름)
TARGETS = {
    "kr_turn_kospi":  ("idx/kospi_dd_trd", "코스피", "sto/stk_bydd_trd", "코스피 회전율(거래대금/시총)"),
    "kr_turn_kosdaq": ("idx/kosdaq_dd_trd", "코스닥", "sto/ksq_bydd_trd", "코스닥 회전율(거래대금/시총)"),
}
# 개별종목 매물대용 워치리스트 — stock_meta 시총 상위 N + SCREENER_ALWAYS(보유 종목).
# API는 '하루치 전 종목'을 한 번에 주므로 종목 수를 늘려도 호출 수는 그대로다(저장량만 늘어남).
WATCH_N = int(os.environ.get("VP_STOCK_N", "30"))
ALWAYS = [c.strip() for c in os.environ.get("SCREENER_ALWAYS", "").split(",") if c.strip()]
MKT_PATH = {"KOSPI": "sto/stk_bydd_trd", "KOSDAQ": "sto/ksq_bydd_trd"}
# 종목 스캔과 같은 날짜 루프에서 지수 OHLC도 받아 stock_daily에 함께 적재한다.
# 야후 ^KS11은 하루 늦고 거래'량'만 주는데, KRX는 당일 고저가 + 거래'대금' + 시총을 준다
# → 매물대 가중치가 저가주 왜곡 없는 거래대금이 되고, 회전율 분모까지 같은 소스로 맞춰진다.
IDX_TARGETS = {"kospi": ("idx/kospi_dd_trd", "코스피"), "kosdaq": ("idx/kosdaq_dd_trd", "코스닥")}


def get(path, bas_dd):
    url = f"{BASE}/{path}?basDd={bas_dd}"
    req = urllib.request.Request(url, headers={"AUTH_KEY": KEY})
    for attempt in (1, 2, 3):              # 읽기 타임아웃 등 일시 오류는 재시도 (401은 즉시 전파)
        try:
            with urllib.request.urlopen(req, timeout=30) as r:
                return json.loads(r.read().decode("utf-8")).get("OutBlock_1", [])
        except urllib.error.HTTPError:
            raise
        except Exception:
            if attempt == 3:
                raise
            time.sleep(2 * attempt)


def turnover_of_day(code, bas_dd):
    """하루치 회전율. 휴장일이면 None. 지수 API 401이면 종목 API 합산 폴백."""
    idx_path, idx_name, sto_path, _ = TARGETS[code]
    try:
        rows = [r for r in get(idx_path, bas_dd)
                if r["IDX_NM"].strip() == idx_name and r.get("ACC_TRDVAL") and r.get("MKTCAP")]
        if rows:
            return float(rows[0]["ACC_TRDVAL"]) / float(rows[0]["MKTCAP"])
        return None                        # 휴장일(빈 응답) — 폴백 불필요
    except urllib.error.HTTPError as e:
        if e.code != 401:
            raise
    rows = get(sto_path, bas_dd)           # 폴백: 종목별 합산(값은 동일, 콜이 무거울 뿐)
    tv = sum(float(r["ACC_TRDVAL"]) for r in rows if r.get("ACC_TRDVAL"))
    mc = sum(float(r["MKTCAP"]) for r in rows if r.get("MKTCAP"))
    return tv / mc if mc else None


def last_dt(code):
    r = sb.table("indicator_raw").select("dt").eq("market", "KR").eq("code", code) \
          .order("dt", desc=True).limit(1).execute().data
    return date.fromisoformat(r[0]["dt"]) if r else None


def upsert_meta():
    rows = [{"code": code, "name": name, "market": "KR", "category": "가격",
             "role": "turnover", "source": f"krx:{idx_path}"}
            for code, (idx_path, _n, _s, name) in TARGETS.items()]
    sb.table("indicator_meta").upsert(rows, on_conflict="code").execute()


def run(force_start=None):
    if not KEY:
        print("[KR] KRX_API_KEY 없음 — 회전율 수집 건너뜀 (profile.py는 프록시 회전율로 동작)")
        return
    upsert_meta()
    today = date.today()
    total = 0
    for code in TARGETS:
        start = force_start or (
            (ld := last_dt(code)) and ld + timedelta(days=1) or BACKFILL_START)
        d, recs, calls, saved = start, [], 0, 0

        def flush():                       # 20일 단위로 바로바로 저장 — 중간에 죽어도 재실행이 이어받음
            nonlocal recs, saved
            if recs:
                sb.table("indicator_raw").upsert(recs, on_conflict="market,dt,code").execute()
                saved += len(recs)
                print(f"  [KR] {code}: ~{recs[-1]['dt']} 누적 {saved}행", flush=True)
                recs = []

        while d <= today:
            if d.weekday() < 5:            # 주말 스킵(휴일은 빈 응답이라 그대로 넘어감)
                v = turnover_of_day(code, d.strftime("%Y%m%d"))
                calls += 1
                if v is not None:
                    recs.append({"market": "KR", "dt": d.isoformat(), "code": code, "value": v})
                if len(recs) >= 20:
                    flush()
                time.sleep(0.15)           # KRX 호출 간격 — 일일 한도·차단 방어
            d += timedelta(days=1)
        flush()
        total += saved
        print(f"[KR] {code}: {start}~{today} 조회 {calls}콜 → {saved}행 적재")
    sb.table("ingest_log").insert(
        {"source": "krx", "market": "KR", "rows": total, "status": "ok"}).execute()


def watchlist():
    """{code: market} — 시총 상위 N + 지정 종목. stock_meta가 비었으면 빈 dict."""
    rows = sb.table("stock_meta").select("code,name,market,marcap") \
             .order("marcap", desc=True).limit(WATCH_N).execute().data or []
    have = {r["code"] for r in rows}
    if ALWAYS:
        extra = sb.table("stock_meta").select("code,name,market") \
                  .in_("code", [c for c in ALWAYS if c not in have]).execute().data or []
        rows += extra
    return {r["code"]: r["market"] for r in rows if r["market"] in MKT_PATH}


def num(v):
    """KRX 응답의 숫자 문자열 → float. 빈값·'-'는 None."""
    v = (v or "").strip().replace(",", "")
    try:
        return float(v)
    except ValueError:
        return None


def run_stocks(force_start=None):
    """워치리스트 종목의 일별 시세(거래대금·시총·상장주식수)를 stock_daily에 적재.
    스캔은 '날짜 단위'(한 콜에 그 날 전 종목) — 워치리스트가 바뀌어 과거가 빈 종목이 생기면
    `python krx.py --stocks 20210801` 로 전체 재스캔해야 메워진다."""
    codes = watchlist()
    if not codes:
        print("[KR] stock_meta 비어 있음 — 종목은 건너뛰고 지수 OHLC만 수집")
    paths = sorted({MKT_PATH[m] for m in codes.values()})
    r = sb.table("stock_daily").select("dt").order("dt", desc=True).limit(1).execute().data
    start = force_start or (date.fromisoformat(r[0]["dt"]) + timedelta(days=1) if r else BACKFILL_START)
    today = date.today()
    print(f"[KR] 종목 {len(codes)}개 + 지수 {len(IDX_TARGETS)}종 · {start}~{today} "
          f"· 하루 {len(paths) + len(IDX_TARGETS)}콜")

    d, recs, calls, saved = start, [], 0, 0
    while d <= today:
        if d.weekday() < 5:                # 주말 스킵(휴일은 빈 응답)
            bas = d.strftime("%Y%m%d")
            for p in paths:
                for x in get(p, bas):
                    if x["ISU_CD"] not in codes:
                        continue
                    recs.append({"code": x["ISU_CD"], "dt": d.isoformat(),
                                 "open": num(x["TDD_OPNPRC"]), "high": num(x["TDD_HGPRC"]),
                                 "low": num(x["TDD_LWPRC"]), "close": num(x["TDD_CLSPRC"]),
                                 "tval": num(x["ACC_TRDVAL"]), "shares": num(x["LIST_SHRS"]),
                                 "mktcap": num(x["MKTCAP"])})
                calls += 1
                time.sleep(0.15)
            for key, (p, idx_nm) in IDX_TARGETS.items():     # 지수 OHLC도 같은 날짜 루프에서
                for x in get(p, bas):
                    if x["IDX_NM"].strip() != idx_nm or not num(x["CLSPRC_IDX"]):
                        continue
                    recs.append({"code": key, "dt": d.isoformat(),
                                 "open": num(x["OPNPRC_IDX"]), "high": num(x["HGPRC_IDX"]),
                                 "low": num(x["LWPRC_IDX"]), "close": num(x["CLSPRC_IDX"]),
                                 "tval": num(x["ACC_TRDVAL"]), "shares": None,
                                 "mktcap": num(x["MKTCAP"])})
                    break
                calls += 1
                time.sleep(0.15)
            if len(recs) >= 600:
                sb.table("stock_daily").upsert(recs, on_conflict="code,dt").execute()
                saved += len(recs)
                print(f"  [KR] 종목: ~{recs[-1]['dt']} 누적 {saved}행", flush=True)
                recs = []
        d += timedelta(days=1)
    if recs:
        sb.table("stock_daily").upsert(recs, on_conflict="code,dt").execute()
        saved += len(recs)
    print(f"[KR] 개별종목: 조회 {calls}콜 → {saved}행 적재")
    sb.table("ingest_log").insert(
        {"source": "krx_stock", "market": "KR", "rows": saved, "status": "ok"}).execute()


if __name__ == "__main__":
    if "--stocks" in sys.argv:             # 개별종목만 (지수 회전율은 건너뜀)
        rest = [a for a in sys.argv[1:] if a != "--stocks"]
        s = rest[0] if rest else None
        run_stocks(date(int(s[:4]), int(s[4:6]), int(s[6:])) if s else None)
        sys.exit()
    arg = sys.argv[1] if len(sys.argv) > 1 else None
    forced = date(int(arg[:4]), int(arg[4:6]), int(arg[6:])) if arg else None
    run(forced)
    run_stocks(forced)                     # 인자 없이 부르면 지수 회전율 + 개별종목 둘 다(크론)
