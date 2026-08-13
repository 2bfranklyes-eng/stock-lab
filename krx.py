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
# 개별종목 매물대 대상 — 시총 상위 비율로 자른다(코스피 50% / 코스닥 70%).
# API는 '하루치 전 종목'을 한 번에 주므로 종목 수를 늘려도 호출 수는 그대로고 저장량만 늘어난다.
# 그래서 히스토리를 차등한다: 상위 DEEP_N은 5년, 나머지는 2년. 무료 티어 용량 방어.
MKT_PATH = {"KOSPI": "sto/stk_bydd_trd", "KOSDAQ": "sto/ksq_bydd_trd"}
MKT_PCT = {"KOSPI": float(os.environ.get("VP_PCT_KOSPI", "0.5")),
           "KOSDAQ": float(os.environ.get("VP_PCT_KOSDAQ", "0.7"))}
DEEP_N = int(os.environ.get("VP_DEEP_N", "200"))     # 5년치를 보관할 시총 상위 종목 수
DEEP_DAYS, SHALLOW_DAYS = 1825, 730
ALWAYS = [c.strip() for c in os.environ.get("SCREENER_ALWAYS", "").split(",") if c.strip()]
# 종목 스캔과 같은 날짜 루프에서 지수 OHLC도 받아 stock_daily에 함께 적재한다.
# 야후 ^KS11은 하루 늦고 거래'량'만 주는데, KRX는 당일 고저가 + 거래'대금' + 시총을 준다
# → 매물대 가중치가 저가주 왜곡 없는 거래대금이 되고, 회전율 분모까지 같은 소스로 맞춰진다.
IDX_TARGETS = {"kospi": ("idx/kospi_dd_trd", "코스피"), "kosdaq": ("idx/kosdaq_dd_trd", "코스닥")}
# 같은 종가를 indicator_raw에도 덮어쓴다 — 심리·유동성·물가·자산배분이 전부 여기서 읽는데,
# ingest.py의 야후 값은 하루 늦어 '금요일 지수가 목요일로 보이는' 오독을 만들었다(실사용 지적).
# refresh.yml에서 ingest.py 뒤에 돌므로 이 값이 이긴다. 2021-08 이전 이력은 야후분이 남는다
# (KRX 백필 시작이 BACKFILL_START라서) — 두 소스 값이 같음은 확인했다.
IDX_TO_INDICATOR = {"kospi": "kr_index", "kosdaq": "kr_kosdaq"}


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


def watchlist(bas_dd):
    """대상 종목을 KRX 일별매매정보(그 날 전 종목)에서 직접 만든다 → vp_stocks에 저장.
    stock_meta(스크리너용 500종목)에 매이지 않으므로 코스닥 소형주까지 커버된다.
    → {code: (market, hist_days)}"""
    uni = []
    for mkt, path in MKT_PATH.items():
        rows = [x for x in get(path, bas_dd) if num(x.get("MKTCAP"))]
        rows.sort(key=lambda x: -num(x["MKTCAP"]))
        keep = rows[:int(len(rows) * MKT_PCT[mkt])]
        pinned = [x for x in rows if x["ISU_CD"] in ALWAYS and x not in keep]
        uni += [(x["ISU_CD"], x["ISU_NM"], mkt, num(x["MKTCAP"])) for x in keep + pinned]
        print(f"  [{mkt}] 전체 {len(rows)} → 상위 {MKT_PCT[mkt]*100:.0f}% {len(keep)}종목"
              f"{f' + 지정 {len(pinned)}' if pinned else ''}")
    uni.sort(key=lambda x: -x[3])                    # 시총 내림차순 → 앞의 DEEP_N개만 5년 보관
    out, recs = {}, []
    for i, (code, name, mkt, cap) in enumerate(uni):
        hist = DEEP_DAYS if i < DEEP_N else SHALLOW_DAYS
        out[code] = (mkt, hist)
        recs.append({"code": code, "name": name, "market": mkt, "marcap": cap, "hist_days": hist})
    for i in range(0, len(recs), 500):
        sb.table("vp_stocks").upsert(recs[i:i + 500], on_conflict="code").execute()
    print(f"  vp_stocks 갱신: {len(recs)}종목 (5년 {min(DEEP_N, len(recs))} / 2년 {max(0, len(recs)-DEEP_N)})")
    return out


def num(v):
    """KRX 응답의 숫자 문자열 → float. 빈값·'-'는 None."""
    v = (v or "").strip().replace(",", "")
    try:
        return float(v)
    except ValueError:
        return None


PIT_KEEP_DAYS = 45               # 일별 버퍼 보관일 — 한 달 집계에 필요한 만큼만(용량 14MB 고정)


def pit_flush(rows):
    """전 종목 일별을 버퍼에 upsert. 실패해도 본 적재를 되돌리지 않는다 —
    point-in-time은 부가 기능이라, 여기서 죽으면 매물대·지표가 통째로 멈춘다."""
    if not rows:
        return
    try:
        for i in range(0, len(rows), 1000):
            sb.table("pit_daily").upsert(rows[i:i + 1000], on_conflict="code,dt").execute()
        print(f"[KR] pit_daily {len(rows):,}행 (전 종목 {len({r['code'] for r in rows})}개)")
    except Exception as e:
        print(f"[KR] pit_daily 적재 실패 — 건너뜀: {e}")


def pit_aggregate(rows, skip_ym=None):
    """일별 행들 → 월말 스냅샷 행들. 버퍼 롤업과 과거 백필이 같은 로직을 쓴다.

    변동성은 그달 안의 일간 수익률 표준편차다. 한국 주식은 일일 가격제한폭이 ±30%라
    |수익률| > 31%면 액면분할·병합 같은 코퍼릿 액션이므로 그 하루만 뺀다
    (수정주가가 아니라서 생기는 오염을 주식수 비교 없이 걸러내는 가장 단순한 방법)."""
    by = {}
    for r in rows:
        ym = r["dt"][:7]
        if skip_ym and ym >= skip_ym:            # 아직 안 끝난 달은 집계하지 않는다
            continue
        by.setdefault((r["code"], ym), []).append(r)
    out = []
    for (code, ym), g in by.items():
        g.sort(key=lambda x: x["dt"])
        closes = [x["close"] for x in g if x["close"]]
        if len(closes) < 2:
            continue
        rets = [closes[i] / closes[i - 1] - 1 for i in range(1, len(closes))]
        rets = [v for v in rets if abs(v) <= 0.31]     # ±30% 초과 = 코퍼릿 액션 → 제외
        mean = sum(rets) / len(rets) if rets else 0.0
        var = sum((v - mean) ** 2 for v in rets) / len(rets) if len(rets) > 1 else None
        tv = [x["tval"] for x in g if x["tval"] is not None]
        last = g[-1]
        out.append({"code": code, "ym": ym, "name": last.get("name"),
                    "market": last.get("market"), "close": last["close"],
                    "mktcap": last.get("mktcap"), "shares": last.get("shares"),
                    "tval_avg": (sum(tv) / len(tv)) if tv else None,
                    "vol": (var ** 0.5) if var else None, "n_days": len(g)})
    return out


def pit_put(rows):
    for i in range(0, len(rows), 1000):
        sb.table("pit_monthly").upsert(rows[i:i + 1000], on_conflict="code,ym").execute()


def pit_rollup(today):
    """버퍼에서 '이미 끝난 달'을 월말 스냅샷으로 넘기고, 오래된 버퍼를 지운다."""
    try:
        rows, off = [], 0
        while True:
            r = (sb.table("pit_daily").select("code,dt,market,name,close,tval,shares,mktcap")
                 .order("code").order("dt").range(off, off + 999).execute().data)
            rows += r
            off += 1000
            if len(r) < 1000:
                break
        out = pit_aggregate(rows, skip_ym=today.strftime("%Y-%m")) if rows else []
        if out:
            pit_put(out)
            print(f"[KR] pit_monthly {len(out):,}행 집계 "
                  f"({', '.join(sorted({r['ym'] for r in out}))})")
        cut = (today - timedelta(days=PIT_KEEP_DAYS)).isoformat()
        sb.table("pit_daily").delete().lt("dt", cut).execute()
    except Exception as e:
        print(f"[KR] pit 집계 실패 — 건너뜀: {e}")


def pit_day(bas):
    """그 날짜의 전 종목(코스피+코스닥). 휴장일이면 빈 리스트."""
    out = []
    for mkt, path in MKT_PATH.items():
        for x in get(path, bas):
            if not num(x["TDD_CLSPRC"]):
                continue
            out.append({"code": x["ISU_CD"], "dt": f"{bas[:4]}-{bas[4:6]}-{bas[6:]}",
                        "market": mkt, "name": (x.get("ISU_NM") or "").strip(),
                        "close": num(x["TDD_CLSPRC"]), "tval": num(x["ACC_TRDVAL"]),
                        "shares": num(x["LIST_SHRS"]), "mktcap": num(x["MKTCAP"])})
        time.sleep(0.15)
    return out


def pit_backfill(start_ym="201501"):
    """과거 point-in-time 유니버스 백필.

    처음엔 '과거는 복구 불가'로 판단했는데 틀렸다 — KRX 일별매매정보는 날짜만 주면 그 시점의
    전 종목을 돌려주고, 2015년까지 살아 있다. 2015-01-02 응답에 AJ렌터카(2019년 상장폐지)가
    들어 있는 걸로 확인했다. 즉 상장폐지 종목이 그 시점 기록 그대로 남아 있는 진짜 PIT다.

    일별은 저장하지 않는다 — 11년치를 다 넣으면 800만 행(약 1GB)이라 무료 티어가 감당 못 한다.
    한 달치를 메모리에서 집계해 pit_monthly에만 쓰고 버린다(11년 ≈ 39만 행 ≈ 50MB).
    이미 있는 달은 건너뛰므로 중간에 끊겨도 다시 돌리면 이어진다(약 40분짜리 작업이라 중요)."""
    if not KEY:
        print("[KR] KRX_API_KEY 없음 — PIT 백필 불가")
        return
    done = set()
    off = 0
    while True:                                   # 이미 채운 달 목록
        r = sb.table("pit_monthly").select("ym").order("ym").range(off, off + 999).execute().data
        done |= {x["ym"] for x in r}
        off += 1000
        if len(r) < 1000:
            break
    today = date.today()
    y, mo = int(start_ym[:4]), int(start_ym[4:6])
    total = 0
    while (y, mo) < (today.year, today.month):    # 이번 달은 아직 안 끝났으니 제외
        ym = f"{y:04d}-{mo:02d}"
        if ym in done:
            print(f"  [PIT] {ym} 이미 있음 — 건너뜀", flush=True)
        else:
            rows, d = [], date(y, mo, 1)
            while d.month == mo:
                if d.weekday() < 5:
                    rows += pit_day(d.strftime("%Y%m%d"))
                d += timedelta(days=1)
            out = pit_aggregate(rows)
            if out:
                pit_put(out)
                total += len(out)
                print(f"  [PIT] {ym}: {len(out):,}종목 적재 (누적 {total:,}행)", flush=True)
            else:
                print(f"  [PIT] {ym}: 데이터 없음", flush=True)
        mo += 1
        if mo > 12:
            y, mo = y + 1, 1
    print(f"[KR] PIT 백필 완료: 총 {total:,}행")


def prune_dropped(codes, today):
    """워치리스트를 '벗어난' 종목의 창 밖 행을 지운다.

    바로 위 삭제는 codes(=이번에 뽑은 현재 워치리스트)만 훑는다. 그래서 상장폐지되거나
    시총 컷 아래로 떨어져 목록에서 빠진 종목의 행에는 영영 닿지 않고 영구히 남았다
    (실측 2026-08-12: 33종목 11,144행). 종목당 양은 2년치로 묶여 있지만 이탈 종목 수가
    해마다 늘어 총량은 상한이 없고, 갱신이 멈춘 낡은 행이 분석에 섞이는 문제도 있었다.

    티어는 vp_stocks에 남아 있는 hist_days를 그대로 쓴다 — 일시적으로 목록을 벗어난
    5년 티어 종목을 2년으로 잘라버리면 전체 재스캔 없이는 복구가 안 되기 때문이다.
    (vp_stocks는 upsert만 하므로 이탈 종목의 마지막 티어가 남아 있다.)"""
    rows, step, start = [], 1000, 0
    while True:
        r = sb.table("vp_stocks").select("code,hist_days") \
              .order("code").range(start, start + step - 1).execute().data
        rows += r
        if len(r) < step:
            break
        start += step

    by_tier = {}
    for x in rows:
        if x["code"] in codes:
            continue
        by_tier.setdefault(int(x.get("hist_days") or SHALLOW_DAYS), []).append(x["code"])
    if not by_tier:
        print("  워치리스트 이탈 종목 없음")
        return

    for tier, cs in sorted(by_tier.items()):
        cut = (today - timedelta(days=tier)).isoformat()
        for i in range(0, len(cs), 100):
            sb.table("stock_daily").delete().in_("code", cs[i:i + 100]) \
              .lt("dt", cut).execute()
        print(f"  워치리스트 이탈 {len(cs)}종목({tier}일 티어) — {cut} 이전 행 정리")


def run_stocks(force_start=None):
    """워치리스트 종목의 일별 시세(거래대금·시총·상장주식수)를 stock_daily에 적재.
    스캔은 '날짜 단위'(한 콜에 그 날 전 종목) — 워치리스트가 바뀌어 과거가 빈 종목이 생기면
    `python krx.py --stocks 20210801` 로 전체 재스캔해야 메워진다."""
    today = date.today()
    r = sb.table("stock_daily").select("dt").order("dt", desc=True).limit(1).execute().data
    start = force_start or (date.fromisoformat(r[0]["dt"]) + timedelta(days=1) if r else BACKFILL_START)
    # 워치리스트는 '직전 거래일'로 뽑는다. 월요일에 하루 전(=일요일)을 물으면 빈 응답이 와서
    # 종목 0개로 스캔이 조용히 끝나 버린다 — 아침 크론은 화~토라 안 걸리지만 수동 실행에서 걸린다.
    back = 3 if today.weekday() == 0 else (1 if today.weekday() < 5 else today.weekday() - 4)
    codes = watchlist((today - timedelta(days=back)).strftime("%Y%m%d"))
    paths = sorted({MKT_PATH[m] for m, _h in codes.values()})
    shallow_from = today - timedelta(days=SHALLOW_DAYS)   # 2년 티어는 이 날짜부터만 저장
    print(f"[KR] 종목 {len(codes)}개 + 지수 {len(IDX_TARGETS)}종 · {start}~{today} "
          f"· 하루 {len(paths) + len(IDX_TARGETS)}콜")

    d, recs, calls, saved = start, [], 0, 0
    idx_rows = []                          # 지수 종가 → indicator_raw 덮어쓰기용(야후 지연 보정)
    pit = []                               # point-in-time: 그날 상장돼 있던 '전 종목'(필터 전)
    while d <= today:
        if d.weekday() < 5:                # 주말 스킵(휴일은 빈 응답)
            bas = d.strftime("%Y%m%d")
            for p in paths:
                mkt = "KOSPI" if p == MKT_PATH["KOSPI"] else "KOSDAQ"
                for x in get(p, bas):
                    # ↓ 필터 '전'에 전 종목을 따로 담는다. 응답엔 이미 다 들어와 있는데
                    #   아래 tier 필터로 버리고 있었다 — 그래서 과거 유니버스가 복구 불가였다.
                    if num(x["TDD_CLSPRC"]):
                        pit.append({"code": x["ISU_CD"], "dt": d.isoformat(), "market": mkt,
                                    "name": (x.get("ISU_NM") or "").strip(),
                                    "close": num(x["TDD_CLSPRC"]), "tval": num(x["ACC_TRDVAL"]),
                                    "shares": num(x["LIST_SHRS"]), "mktcap": num(x["MKTCAP"])})
                    tier = codes.get(x["ISU_CD"])
                    if not tier or (tier[1] == SHALLOW_DAYS and d < shallow_from):
                        continue           # 대상 아님 / 얕은 티어의 오래된 날짜
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
                    idx_rows.append({"market": "KR", "dt": d.isoformat(),
                                     "code": IDX_TO_INDICATOR[key],
                                     "value": num(x["CLSPRC_IDX"])})
                    break
                calls += 1
                time.sleep(0.15)
            if len(recs) >= 2000:
                sb.table("stock_daily").upsert(recs, on_conflict="code,dt").execute()
                saved += len(recs)
                print(f"  [KR] 종목: ~{recs[-1]['dt']} 누적 {saved:,}행", flush=True)
                recs = []
        d += timedelta(days=1)
    if recs:
        sb.table("stock_daily").upsert(recs, on_conflict="code,dt").execute()
        saved += len(recs)
    print(f"[KR] 개별종목: 조회 {calls}콜 → {saved}행 적재")
    # point-in-time: 위 루프에서 이미 받아둔 '전 종목'을 버퍼에 넣고, 끝난 달은 월말 스냅샷으로
    # 넘긴 뒤 버퍼를 정리한다. 추가 API 호출은 0 — 응답에 이미 다 들어 있던 데이터다.
    pit_flush(pit)
    pit_rollup(today)
    # 지수 종가를 indicator_raw에 덮어쓴다(야후분보다 하루 빠른 값). 메타는 ingest.py가 이미
    # 등록해 둬서 FK는 충족된다 — 실패해도 종목 적재를 되돌리지 않게 예외를 삼킨다.
    if idx_rows:
        try:
            for i in range(0, len(idx_rows), 1000):
                sb.table("indicator_raw").upsert(idx_rows[i:i + 1000],
                                                 on_conflict="market,dt,code").execute()
            print(f"[KR] 지수 종가 → indicator_raw {len(idx_rows)}행 (야후 지연 보정)")
        except Exception as e:
            print(f"[KR] 지수 종가 indicator_raw 적재 실패 — 야후 값 유지: {e}")
    # 2년 티어의 창을 벗어난 옛 행을 지운다. 안 지우면 매일 하루씩만 쌓여 1,545종목의
    # 히스토리가 해마다 1년씩 길어지고(=티어를 둔 의미가 사라지고) 용량이 계속 늘어난다.
    shallow = [c for c, (_m, h) in codes.items() if h == SHALLOW_DAYS]
    for i in range(0, len(shallow), 100):
        sb.table("stock_daily").delete().in_("code", shallow[i:i + 100]) \
          .lt("dt", shallow_from.isoformat()).execute()
    prune_dropped(codes, today)
    sb.table("ingest_log").insert(
        {"source": "krx_stock", "market": "KR", "rows": saved, "status": "ok"}).execute()


if __name__ == "__main__":
    if "--pit-backfill" in sys.argv:       # 과거 point-in-time 유니버스 백필 (약 40분, 재개 가능)
        rest = [a for a in sys.argv[1:] if a != "--pit-backfill"]
        pit_backfill(rest[0] if rest else "201501")
        sys.exit()
    if "--stocks" in sys.argv:             # 개별종목만 (지수 회전율은 건너뜀)
        rest = [a for a in sys.argv[1:] if a != "--stocks"]
        s = rest[0] if rest else None
        run_stocks(date(int(s[:4]), int(s[4:6]), int(s[6:])) if s else None)
        sys.exit()
    arg = sys.argv[1] if len(sys.argv) > 1 else None
    forced = date(int(arg[:4]), int(arg[4:6]), int(arg[6:])) if arg else None
    run(forced)
    run_stocks(forced)                     # 인자 없이 부르면 지수 회전율 + 개별종목 둘 다(크론)
