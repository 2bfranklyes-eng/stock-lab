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


if __name__ == "__main__":
    arg = sys.argv[1] if len(sys.argv) > 1 else None
    run(date(int(arg[:4]), int(arg[4:6]), int(arg[6:])) if arg else None)
