# ingest.py — 원천 지표 수집 → Supabase indicator_raw (미국 + 한국)
import os
import sys
import time
import json
import urllib.request
from dotenv import load_dotenv
import pandas as pd
import yfinance as yf
from supabase import create_client

try:  # 윈도우 콘솔(cp949)에서도 한글·기호 출력이 깨지지 않게
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

load_dotenv()
sb = create_client(os.environ["SUPABASE_URL"], os.environ["SUPABASE_SERVICE_KEY"])

# 시장별 수집 대상 (code → yfinance 심볼)
#   한국: VKOSPI(내재변동성)는 어떤 소스에서도 안 받아져(yfinance·FDR·pykrx 전부 실패),
#         공포 지표는 sentiment.py에서 코스피 '실현변동성'으로 파생한다.
#         kr_index=코스피, kr_bond=국고채10년(미국 TLT 대응),
#         kr_kosdaq=코스닥(코스피와의 20일 수익률차 → 위험선호/시장 폭, 미국 RSP-SPY 대응).
#         (동일가중 KOSPI200 ETF는 시총가중과 상관 0.99로 거의 안 갈라져 노이즈라 코스닥으로 교체)
#   유동성(L) 지표: us_10y·us_3m(금리·커브), dxy(달러), hyg·lqd(신용 스프레드) → 미국 계정에.
#     한국 유동성은 국내물(국고채3·10년, 회사채3년 AA- via ECOS) + usdkrw(원/달러)로 계산.
#     ↳ 커브(국고채10-3년)·신용(회사채-국고채)까지 국내물로 → 미국 지수와 뚜렷이 갈라짐.
#   물가(I) 지표: tip·ief(기대인플레=물가연동채/국채), uso(유가), dbc(원자재), dbb(산업금속) → 미국 계정에.
#     원자재·유가는 글로벌이라 한국 물가에도 그대로 작용. 한국은 여기에 usdkrw(원 약세=수입물가)를 더해 계산.
JOBS = {
    "US": {"vix": "^VIX", "us_index": "^GSPC", "us_bond": "TLT",
           "rsp": "RSP", "spy": "SPY",
           "us_10y": "^TNX", "us_3m": "^IRX", "dxy": "DX-Y.NYB",
           "hyg": "HYG", "iei": "IEI",
           "tip": "TIP", "ief": "IEF", "uso": "USO", "dbc": "DBC", "dbb": "DBB"},
    "KR": {"kr_index": "^KS11", "kr_bond": "148070.KS", "kr_kosdaq": "^KQ11",
           "usdkrw": "USDKRW=X"},
}

# ── ECOS(한국은행) 시장금리 일별 — 한국 유동성용 국내 금리 (yfinance엔 없음) ──
# 통계표 817Y002 / 주기 D. 국고채10-3년(커브)·회사채-국고채(신용)를 국내물로 계산하기 위함.
# indicator_raw.code → indicator_meta.code FK가 있어 메타부터 등록해야 함(run_ecos가 자동 upsert).
ECOS_KEY = os.environ.get("ECOS_API_KEY", "").strip()
ECOS_START = "20150101"           # yfinance 수집 시작과 정렬(usdkrw·kr_index 등과 교집합)
ECOS_ITEMS = {                    # code → (ECOS 817Y002 항목코드, 메타 name, 메타 role)
    "kr_3y":     ("010200000", "국고채 3년", "rate"),
    "kr_10y":    ("010210000", "국고채 10년", "rate"),
    "kr_corp3y": ("010300000", "회사채 3년(AA-)", "credit"),
}


def fetch_close(symbol, start="2015-01-01"):
    """야후 파이낸스에서 종가 시계열(Series)을 가져온다. 빈 응답이면 빈 Series."""
    df = yf.Ticker(symbol).history(start=start, auto_adjust=True)
    if df.empty or "Close" not in df.columns:
        return pd.Series(dtype="float64")
    return df["Close"].dropna()


def to_rows(series, market, code):
    """Series → Supabase에 넣을 dict 리스트로 변환."""
    return [{"market": market, "dt": d.strftime("%Y-%m-%d"),
             "code": code, "value": float(v)} for d, v in series.items()]


def upsert(rows, chunk=1000):
    """PK(market, dt, code) 기준 upsert — 재실행해도 중복 없음."""
    for i in range(0, len(rows), chunk):
        sb.table("indicator_raw").upsert(
            rows[i:i + chunk], on_conflict="market,dt,code").execute()


def get_series(market, code, sym):
    """한 지표를 받아온다. 빈 응답/오류면 2초 뒤 1회 재시도(야후 일시적 throttle 방어)."""
    for attempt in (1, 2):
        try:
            s = fetch_close(sym)
            if not s.empty:
                return s
        except Exception as e:
            print(f"  [{market}] {code} ({sym}): 시도{attempt} 오류 — {e}")
        if attempt == 1:
            time.sleep(2)
    return pd.Series(dtype="float64")


def run(market):
    total, failed = 0, []
    for i, (code, sym) in enumerate(JOBS[market].items()):
        if i:
            time.sleep(0.8)   # 요청을 살짝 벌려 야후 throttle 방지 (지표 수 늘어난 뒤 대비)
        s = get_series(market, code, sym)
        if s.empty:
            # 한 티커가 비어도 전체를 죽이지 않는다 — 건너뛰고 나머지 진행.
            failed.append(f"{code}({sym})")
            print(f"  [{market}] {code} ({sym}): 데이터 없음 — 건너뜀")
            continue
        rows = to_rows(s, market, code)
        upsert(rows)
        total += len(rows)
        print(f"  [{market}] {code} ({sym}): {len(rows)} rows")
    sb.table("ingest_log").insert(
        {"source": "yfinance", "market": market, "rows": total,
         "status": "ok" if not failed else "partial"}).execute()
    tail = f"  (건너뜀: {', '.join(failed)})" if failed else ""
    print(f"[{market}] 완료: 총 {total} rows{tail}")


def upsert_ecos_meta():
    """ECOS 신규 코드를 indicator_meta에 등록(FK 충족). on_conflict=code 라 재실행 안전."""
    rows = [{"code": code, "name": name, "market": "KR", "category": "유동성",
             "role": role, "source": f"ecos:817Y002/{item}"}
            for code, (item, name, role) in ECOS_ITEMS.items()]
    sb.table("indicator_meta").upsert(rows, on_conflict="code").execute()


def fetch_ecos(item, start=ECOS_START):
    """ECOS 817Y002(시장금리 일별)에서 한 항목의 일별 금리를 페이지네이션으로 수집 → {dt: value}."""
    end = time.strftime("%Y%m%d")
    rows, page, size = [], 1, 1000
    while True:
        url = (f"https://ecos.bok.or.kr/api/StatisticSearch/{ECOS_KEY}/json/kr/"
               f"{page}/{page + size - 1}/817Y002/D/{start}/{end}/{item}")
        with urllib.request.urlopen(url, timeout=30) as r:
            d = json.loads(r.read().decode("utf-8"))
        if "RESULT" in d:                          # ECOS 오류(키 오류/데이터 없음 등)
            print(f"  [KR] ECOS {item}: {d['RESULT'].get('MESSAGE', '오류')}")
            break
        page_rows = d.get("StatisticSearch", {}).get("row", [])
        rows += page_rows
        if len(page_rows) < size:
            break
        page += size
        time.sleep(0.3)
    ser = {}                                       # TIME(YYYYMMDD)+DATA_VALUE, 빈값/비수치 방어
    for r in rows:
        v, t = r.get("DATA_VALUE", "").strip(), r.get("TIME", "")
        if v not in ("", "-") and len(t) == 8:
            try:
                ser[f"{t[:4]}-{t[4:6]}-{t[6:]}"] = float(v)
            except ValueError:
                pass
    return ser


def run_ecos():
    """ECOS 국내 금리 3종(국고채3·10년, 회사채3년 AA-)을 indicator_raw(market=KR)에 적재."""
    if not ECOS_KEY:
        print("[KR] ECOS_API_KEY 없음 — 국내 금리 수집 건너뜀 (한국 유동성 커브·신용 계산 불가)")
        return
    upsert_ecos_meta()                             # FK 충족: 신규 코드 메타 먼저 등록
    total, failed = 0, []
    for code, (item, _name, _role) in ECOS_ITEMS.items():
        try:
            ser = fetch_ecos(item)
        except Exception as e:
            failed.append(f"{code}({item})")
            print(f"  [KR] {code} ({item}): 오류 — {e}")
            continue
        if not ser:
            failed.append(f"{code}({item})")
            print(f"  [KR] {code} ({item}): 데이터 없음 — 건너뜀")
            continue
        upsert([{"market": "KR", "dt": dt, "code": code, "value": v} for dt, v in ser.items()])
        total += len(ser)
        print(f"  [KR] {code} ({item}): {len(ser)} rows")
        time.sleep(0.5)
    sb.table("ingest_log").insert(
        {"source": "ecos", "market": "KR", "rows": total,
         "status": "ok" if not failed else "partial"}).execute()
    print(f"[KR] ECOS 완료: 총 {total} rows" + (f"  (건너뜀: {', '.join(failed)})" if failed else ""))


if __name__ == "__main__":
    # 인자 없으면 미국+한국 둘 다 (크론이 인자 없이 호출). `python ingest.py KR` 로 개별 실행도 가능.
    markets = [a.upper() for a in sys.argv[1:]] or ["US", "KR"]
    for m in markets:
        run(m)
    if "KR" in markets:                            # 한국 국내 금리(ECOS)는 yfinance 뒤에 별도 수집
        run_ecos()
