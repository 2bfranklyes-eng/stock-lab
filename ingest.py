# ingest.py — 원천 지표 수집 → Supabase indicator_raw (미국 + 한국)
import os
import sys
import time
import json
import urllib.request
from datetime import date, timedelta
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
    "US": {"vix": "^VIX", "us_index": "^GSPC", "us_nasdaq": "^IXIC", "us_dow": "^DJI",
           "us_bond": "TLT",
           "rsp": "RSP", "spy": "SPY",
           "us_10y": "^TNX", "us_3m": "^IRX", "dxy": "DX-Y.NYB",
           "hyg": "HYG", "iei": "IEI",
           "tip": "TIP", "ief": "IEF", "uso": "USO", "dbc": "DBC", "dbb": "DBB",
           "wti": "CL=F", "copper": "HG=F", "gsci": "^SPGSCI",
           "corn": "ZC=F", "wheat": "ZW=F", "soy": "ZS=F",
           # ↓ 자산배분(allocation.py)용. 금·은은 선물이 ETF보다 이력이 길다(2000~, GLD는 2004~).
           #   은은 자산 카드가 아니라 금/은 비율(금 밸류에이션 렌즈)의 재료로만 쓴다.
           "gold": "GC=F", "silver": "SI=F", "btc": "BTC-USD"},
    "KR": {"kr_index": "^KS11", "kr_bond": "148070.KS", "kr_kosdaq": "^KQ11",
           "usdkrw": "USDKRW=X"},
}

# indicator_raw.code → indicator_meta.code FK가 있어, 메타에 없는 코드는 적재가 통째로 막힌다.
# JOBS에 티커만 추가하고 메타를 빠뜨리면 조용히 0행이 되므로, ECOS(upsert_ecos_meta)와 똑같이
# 수집 직전에 자동 등록한다 — Supabase SQL 수동 등록 불필요. code → (name, category, role).
# source는 JOBS의 심볼에서 만들어 쓰므로 여기 중복해 적지 않는다.
YF_META = {
    "vix": ("VIX 변동성", "심리", "fear"),
    "us_index": ("S&P500 종가", "가격", "price"),
    "us_nasdaq": ("나스닥 종합", "가격", "price"),
    "us_dow": ("다우존스 산업평균", "가격", "price"),
    "us_bond": ("미장기채 TLT", "가격", "price"),
    "rsp": ("동일가중 S&P (RSP)", "가격", "price"),
    "spy": ("S&P ETF (SPY)", "가격", "price"),
    "us_10y": ("미 10년물 금리", "유동성", "rate"),
    "us_3m": ("미 3개월 금리", "유동성", "rate"),
    "dxy": ("달러지수 DXY", "유동성", "fx"),
    "hyg": ("하이일드 HYG", "유동성", "credit"),
    "iei": ("미국채 3-7년 IEI", "유동성", "credit"),
    "tip": ("물가연동채 TIP", "물가", "inflation"),
    "ief": ("미국채 7-10년 IEF", "물가", "inflation"),
    "uso": ("유가 USO", "물가", "energy"),
    "dbc": ("원자재 DBC", "물가", "commodity"),
    "dbb": ("산업금속 DBB", "물가", "metal"),
    # ↓ 점수 계산엔 안 쓰고 대시보드에 '실제 수치'로 보여주기만 하는 원자재 원물 시세
    "wti": ("WTI 유가($/배럴)", "물가", "energy"),
    "copper": ("구리($/lb)", "물가", "metal"),
    "gsci": ("원자재지수 GSCI", "물가", "commodity"),
    # 곡물 3종 = 물가의 '식품' 성분. 에너지와 상관 0.40으로 낮아 새 정보를 준다
    # (기존 DBC 원자재는 절반이 에너지라 에너지를 두 번 세는 꼴이었음).
    "corn": ("옥수수", "물가", "food"),
    "wheat": ("밀", "물가", "food"),
    "soy": ("대두", "물가", "food"),
    "kr_index": ("코스피", "가격", "price"),
    "kr_bond": ("국고채10년 ETF (KOSEF)", "가격", "price"),
    "kr_kosdaq": ("코스닥", "가격", "greed"),
    "usdkrw": ("원/달러", "유동성", "fx"),
    "gold": ("금 선물($/온스)", "자산", "asset"),
    "silver": ("은 선물($/온스)", "자산", "asset"),
    "btc": ("비트코인($)", "자산", "asset"),
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
    # 일드커브의 '단기' 쪽. 미국은 10년-3개월(정책금리 대비)인데 한국은 3년물을 써서
    # 커브가 정책 스탠스를 못 읽었다 → 단기 자금금리로 교체. 둘 다 받아 liquidity.py가 있는 걸 고른다.
    # (항목코드가 틀리면 run_ecos가 '데이터 없음'으로 건너뛰고, liquidity.py는 국고채3년으로 되돌아감)
    "kr_cd91":   ("010502000", "CD 91일", "rate"),
    "kr_call":   ("010101000", "콜금리(1일물)", "rate"),
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


def upsert_yf_meta(market):
    """이 시장에서 수집할 코드를 indicator_meta에 먼저 등록(FK 충족). on_conflict=code 라 재실행 안전."""
    rows = [{"code": code, "name": YF_META[code][0], "market": market,
             "category": YF_META[code][1], "role": YF_META[code][2],
             "source": f"yfinance:{sym}"}
            for code, sym in JOBS[market].items() if code in YF_META]
    if rows:
        sb.table("indicator_meta").upsert(rows, on_conflict="code").execute()


def run(market):
    upsert_yf_meta(market)    # FK 충족: 신규 코드 메타 먼저 등록
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
        try:
            upsert(rows)
        except Exception as e:
            # 적재 실패(FK 누락 등)도 한 코드만 건너뛴다 — 안 그러면 크론 전체가 멈춤.
            failed.append(f"{code}(적재실패)")
            print(f"  [{market}] {code} ({sym}): 적재 실패 — {e}")
            continue
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


# ── 경기종합지수 순환변동치(통계청, ECOS 901Y067) 월별 ──
# 이 프로젝트에서 검증을 통과한 유일한 거시 관계다. 1996~2026 355개월에서
#   · 동행지수 순환변동치 '수준' → 공표 후 12개월 코스피: 밴드 5개가 완전 단조
#     (바닥권 +31% / 정점권 -4%, 전체 +12.8%) · 사건 11~31개 · 기간 분할 4/4 부호 일치
#   · 방향이 역(-)이다: 경기가 좋을수록 이후 주가가 나쁘다
# ⚠️ 선행지수는 주가 예측에 쓰면 안 된다 — 통계청 선행종합지수의 구성지표에 코스피가
#    들어 있어 순환논리다. 실측에서도 최대 상관이 시차 -3개월(주가가 지수를 선행)이었다.
#    그래도 함께 받는 이유는 '선행지수를 보고 판단하면 안 된다'를 화면에서 보여주기 위해서다.
# 발표 시차 약 2개월(6월치가 8월 말 공표) — 화면·백테스트 모두 이 시차를 반영해야 한다.
ECOS_CYCLE_STAT = "901Y067"
ECOS_CYCLE_ITEMS = {              # code → (ECOS 항목코드, 메타 name)
    "kr_coincident": ("I16D", "동행지수 순환변동치"),
    "kr_leading":    ("I16E", "선행지수 순환변동치"),
}


def fetch_ecos_monthly(stat, item, start="197001"):
    """ECOS 월별 통계 한 항목 → {YYYY-MM-01: value}. 월 지표라 그 달 1일로 정규화한다."""
    end = time.strftime("%Y%m")
    url = (f"https://ecos.bok.or.kr/api/StatisticSearch/{ECOS_KEY}/json/kr/1/2000/"
           f"{stat}/M/{start}/{end}/{item}")
    with urllib.request.urlopen(url, timeout=60) as r:
        d = json.loads(r.read().decode("utf-8"))
    if "RESULT" in d:
        print(f"  [KR] ECOS {stat}/{item}: {d['RESULT'].get('MESSAGE', '오류')}")
        return {}
    out = {}
    for x in d.get("StatisticSearch", {}).get("row", []):
        t, v = x.get("TIME", ""), (x.get("DATA_VALUE") or "").strip()
        if len(t) == 6 and v not in ("", "-"):
            try:
                out[f"{t[:4]}-{t[4:6]}-01"] = float(v)
            except ValueError:
                pass
    return out


def run_kr_index_long():
    """월말 코스피를 1996년부터 indicator_raw에 적재(code=kr_index_m).

    kr_index는 2015년부터라(다른 지표와 창을 맞춘 것) 경기 국면 통계를 내기엔 짧다.
    순환변동치는 1970년부터 있는데 주가가 11년뿐이면 국면이 몇 개 안 잡힌다.
    kr_index를 늘리면 심리·유동성·자산배분 계산의 창이 통째로 바뀌므로 건드리지 않고,
    월별 통계 전용 코드를 따로 둔다. 야후 ^KS11은 1996-12부터 준다."""
    # get_series()는 fetch_close의 기본 시작일(2015-01-01)을 쓰므로 여기선 직접 부른다 —
    # 이 코드의 존재 이유가 '더 긴 이력'이라 기본값을 쓰면 의미가 없다.
    s = pd.Series(dtype="float64")
    for attempt in (1, 2):
        try:
            s = fetch_close("^KS11", start="1990-01-01")
            if not s.empty:
                break
        except Exception as e:
            print(f"  [KR] kr_index_m: 시도{attempt} 오류 — {e}")
        time.sleep(2)
    if s.empty:
        print("[KR] 월말 코스피(kr_index_m): 응답 없음 — 건너뜀")
        return
    sb.table("indicator_meta").upsert(
        [{"code": "kr_index_m", "name": "코스피 월말종가(장기)", "market": "KR",
          "category": "가격", "role": "price", "source": "yfinance:^KS11(월말)"}],
        on_conflict="code").execute()
    month = {}                                  # 같은 달이면 뒤엣값이 남아 월말 종가가 된다
    for d, v in s.items():
        month[d.strftime("%Y-%m-01")] = float(v)
    upsert([{"market": "KR", "dt": dt, "code": "kr_index_m", "value": v}
            for dt, v in month.items()])
    print(f"  [KR] kr_index_m: {len(month)}개월  {min(month)} ~ {max(month)}")


def run_ecos_cycle():
    """경기 선행·동행지수 순환변동치를 indicator_raw(market=KR)에 적재. 1970-01부터."""
    if not ECOS_KEY:
        print("[KR] ECOS_API_KEY 없음 — 경기종합지수 수집 건너뜀")
        return
    sb.table("indicator_meta").upsert(
        [{"code": code, "name": name, "market": "KR", "category": "경기",
          "role": "cycle", "source": f"ecos:{ECOS_CYCLE_STAT}/{item}"}
         for code, (item, name) in ECOS_CYCLE_ITEMS.items()], on_conflict="code").execute()
    total, failed = 0, []
    for code, (item, name) in ECOS_CYCLE_ITEMS.items():
        try:
            ser = fetch_ecos_monthly(ECOS_CYCLE_STAT, item)
        except Exception as e:
            failed.append(code)
            print(f"  [KR] {code}: 오류 — {e}")
            continue
        if not ser:
            failed.append(code)
            continue
        upsert([{"market": "KR", "dt": dt, "code": code, "value": v} for dt, v in ser.items()])
        total += len(ser)
        print(f"  [KR] {code} ({name}): {len(ser)}개월  {min(ser)} ~ {max(ser)}")
        time.sleep(0.3)
    sb.table("ingest_log").insert(
        {"source": "ecos_cycle", "market": "KR", "rows": total,
         "status": "ok" if not failed else "partial"}).execute()
    print(f"[KR] 경기종합지수 완료: 총 {total} rows")


# ── KRX 투자자별 순매수(코스피 전체) 일별 — 수급 원자료 ──
# 왜 필요한가 — holders.py가 채우는 investor_flow는 종목별 실측이라 정밀하지만 2024-07부터고
# 200종목뿐이다. 수급 가설(외국인이 언제 사고 파는가, 환율 레짐이 선행하는가, 개인 항복이
# 바닥인가)을 검증하려면 사건 수가 필요한데, 2년 표본으로는 국면이 4~16개밖에 안 잡혀
# 어떤 가설도 우연과 구별되지 않았다. 이 시계열은 2015년부터라 표본이 5배 이상 늘어난다.
#
# 종목별이 아니라 시장 전체 합계라 investor_flow를 대체하지 않는다 — 역할이 다르다.
#   · investor_flow  : 종목별·정밀·짧음 → 매물대(holder_profile), 종목 단위 분석
#   · kr_foreign 계열: 시장 전체·긴 이력 → 레짐/타이밍 가설 검증
#
# pykrx는 임포트 시점에 KRX 로그인을 시도하므로 지연 임포트한다(holders.py와 같은 이유).
# KRX_ID/KRX_PW가 없으면 조용히 건너뛴다 — refresh_kr.yml(오후 크론)엔 그 시크릿이 없고,
# 없다고 해서 나머지 지표 수집까지 멈추면 안 된다.
# 코스피만이 아니라 코스닥까지 받는 이유 — '외국인'은 하나의 집단이 아니다. 실측하니 코스피
# 외국인은 순매수 자기상관 +0.478에 기관과 -0.261로 반대편인데, 코스닥 외국인은 +0.008 / -0.058로
# 성격이 딴판이었다. 한 몸이면 나올 수 없는 차이라, 두 시장을 나눠 둬야 '외국인'을 뭉뚱그리지 않는다.
# 공매도를 따로 받는 이유 — '선물·공매도로 시세를 조종한다'는 통념을 사건 수 확보된 상태로
# 검증하려면 현물 순매수와 별개 채널로 있어야 한다. 거래대금(tval)은 공매도·순매수를 규모로
# 정규화할 분모다(대금 수준끼리 비교하면 거래가 활발한 시기가 전부 커 보인다).
KRX_ID = os.environ.get("KRX_ID", "").strip()
KRX_PW = os.environ.get("KRX_PW", "").strip()
KR_INVESTOR_START = "20150101"    # yfinance·ECOS 수집 시작과 정렬
KR_SHORT_START = "20160101"       # 공매도 투자자별은 2016-12-29부터 존재(그 전은 빈 응답)
KR_MARKETS = {"KOSPI": ("kr", "코스피"), "KOSDAQ": ("kq", "코스닥")}
KR_INV_COLS = {                   # 코드 접미사 → (pykrx 컬럼명, 메타 name 조각)
    "foreign": ("외국인합계", "외국인"),
    "inst":    ("기관합계",   "기관"),
    "indiv":   ("개인",       "개인"),
}


def _last_dt(code):
    r = sb.table("indicator_raw").select("dt").eq("market", "KR").eq("code", code) \
          .order("dt", desc=True).limit(1).execute().data
    return date.fromisoformat(r[0]["dt"]) if r else None


def _meta(rows):
    sb.table("indicator_meta").upsert(rows, on_conflict="code").execute()


def run_kr_investor():
    """코스피·코스닥 투자자별 일별 순매수 + 전체 거래대금 → indicator_raw(market=KR). 단위: 억원.

    증분 수집 — 이미 있는 마지막 날짜 다음부터 오늘까지만. 처음이면 2015-01-01부터 백필.
    (전 구간이 몇 콜이면 끝나지만, 매일 11년치를 다시 upsert할 이유는 없다.)"""
    if not (KRX_ID and KRX_PW):
        print("[KR] KRX_ID/KRX_PW 없음 — 투자자별 순매수 수집 건너뜀")
        return
    _meta([{"code": f"{pfx}_{suf}", "name": f"{mk} {nm} 순매수(억원)", "market": "KR",
            "category": "수급", "role": "flow",
            "source": f"pykrx:get_market_trading_value_by_date/{market}"}
           for market, (pfx, mk) in KR_MARKETS.items()
           for suf, (_col, nm) in KR_INV_COLS.items()]
          + [{"code": f"{pfx}_tval", "name": f"{mk} 전체 거래대금(억원)", "market": "KR",
              "category": "수급", "role": "turnover",
              "source": f"pykrx:get_market_trading_value_by_date/{market}?on=매수"}
             for market, (pfx, mk) in KR_MARKETS.items()])

    end = date.today().strftime("%Y%m%d")
    total = 0
    for market, (pfx, mk) in KR_MARKETS.items():
        # 증분 기준은 '이 시장에서 쓰는 코드들 중 가장 뒤처진 것'이다. 대표 코드 하나로 잡으면
        # 나중에 코드를 추가했을 때(tval이 그랬다) 신규 코드만 영원히 빈 채로 남는다.
        lds = [_last_dt(f"{pfx}_{s}") for s in list(KR_INV_COLS) + ["tval"]]
        ld = None if any(x is None for x in lds) else min(lds)
        start = (ld + timedelta(days=1)).strftime("%Y%m%d") if ld else KR_INVESTOR_START
        if start > end:
            print(f"[KR] {mk} 투자자별: 최신 상태({ld}) — 건너뜀")
            continue
        try:
            from pykrx import stock             # 임포트 = KRX 로그인 시도라 여기서
            net = stock.get_market_trading_value_by_date(start, end, market)
            buy = stock.get_market_trading_value_by_date(start, end, market, on="매수")
        except Exception as e:
            print(f"[KR] {mk} 투자자별 실패 — {e}")
            sb.table("ingest_log").insert(
                {"source": "krx_investor", "market": "KR", "rows": 0, "status": "error"}).execute()
            continue
        if net is None or net.empty:
            print(f"[KR] {mk} 투자자별: {start}~{end} 응답 없음(휴장 구간일 수 있음)")
            continue
        for suf, (col, _nm) in KR_INV_COLS.items():
            if col not in net.columns:
                print(f"  [KR] {pfx}_{suf}: 응답에 '{col}' 열 없음 — 건너뜀")
                continue
            rows = [{"market": "KR", "dt": d.strftime("%Y-%m-%d"), "code": f"{pfx}_{suf}",
                     "value": float(v) / 1e8}      # 원 → 억원
                    for d, v in net[col].items() if pd.notna(v)]
            upsert(rows)
            total += len(rows)
            print(f"  [KR] {pfx}_{suf}: {len(rows)} rows")
        # 매수 합계의 '전체' = 그날 시장 거래대금. 공매도·순매수 정규화의 분모.
        if buy is not None and not buy.empty and "전체" in buy.columns:
            rows = [{"market": "KR", "dt": d.strftime("%Y-%m-%d"), "code": f"{pfx}_tval",
                     "value": float(v) / 1e8}
                    for d, v in buy["전체"].items() if pd.notna(v)]
            upsert(rows)
            total += len(rows)
            print(f"  [KR] {pfx}_tval: {len(rows)} rows")
    sb.table("ingest_log").insert(
        {"source": "krx_investor", "market": "KR", "rows": total, "status": "ok"}).execute()
    print(f"[KR] 투자자별 순매수 완료: 총 {total} rows")


def run_kr_shorting():
    """코스피·코스닥 투자자별 일별 공매도 대금 → indicator_raw. 단위: 억원(항상 양수).

    이 엔드포인트는 긴 구간을 한 번에 못 준다(10년 요청 시 빈 응답) — 연도별로 나눠 받는다."""
    if not (KRX_ID and KRX_PW):
        print("[KR] KRX_ID/KRX_PW 없음 — 공매도 수집 건너뜀")
        return
    _meta([{"code": f"{pfx}_short_{suf}", "name": f"{mk} {nm} 공매도 대금(억원)", "market": "KR",
            "category": "수급", "role": "short",
            "source": f"pykrx:get_shorting_investor_value_by_date/{market}"}
           for market, (pfx, mk) in KR_MARKETS.items()
           # 공매도 응답의 열 이름은 순매수 쪽과 달리 '기관/개인/외국인'(합계 표기 없음)
           for suf, nm in (("foreign", "외국인"), ("inst", "기관"), ("indiv", "개인"))])
    SHORT_COLS = {"foreign": "외국인", "inst": "기관", "indiv": "개인"}

    today = date.today()
    total = 0
    for market, (pfx, mk) in KR_MARKETS.items():
        ld = _last_dt(f"{pfx}_short_foreign")
        start = (ld + timedelta(days=1)) if ld else date.fromisoformat(
            f"{KR_SHORT_START[:4]}-{KR_SHORT_START[4:6]}-{KR_SHORT_START[6:]}")
        if start > today:
            print(f"[KR] {mk} 공매도: 최신 상태({ld}) — 건너뜀")
            continue
        acc = {suf: [] for suf in SHORT_COLS}
        from pykrx import stock
        for y in range(start.year, today.year + 1):
            a = max(start, date(y, 1, 1)).strftime("%Y%m%d")
            b = min(today, date(y, 12, 31)).strftime("%Y%m%d")
            try:
                df = stock.get_shorting_investor_value_by_date(a, b, market)
            except Exception as e:
                print(f"  [KR] {mk} 공매도 {y}: 실패 — {e}")
                continue
            if df is None or df.empty:
                continue
            for suf, col in SHORT_COLS.items():
                if col in df.columns:
                    acc[suf] += [{"market": "KR", "dt": d.strftime("%Y-%m-%d"),
                                  "code": f"{pfx}_short_{suf}", "value": float(v) / 1e8}
                                 for d, v in df[col].items() if pd.notna(v)]
            time.sleep(0.2)                     # KRX 호출 간격 — 연도 루프라 콜이 여러 번
        for suf, rows in acc.items():
            if rows:
                upsert(rows)
                total += len(rows)
                print(f"  [KR] {pfx}_short_{suf}: {len(rows)} rows")
    sb.table("ingest_log").insert(
        {"source": "krx_short", "market": "KR", "rows": total, "status": "ok"}).execute()
    print(f"[KR] 공매도 완료: 총 {total} rows")


# ── FRED(세인트루이스 연준) 일별 — 실질금리 (yfinance엔 없음) ──
# 금 밸류에이션의 제1 렌즈: 금은 이자가 없어 보유의 기회비용이 물가연동국채(TIPS) 실질수익률이다.
# 채권 카드에도 '실질수익률 수준'으로 쓴다. fuel.py의 fred()와 같은 API지만 그쪽은 주간 유동성용
# 자기완결 스크립트라 여기 일별 지표 수집과는 결이 달라 최소 구현을 따로 둔다.
FRED_KEY = os.environ.get("FRED_API_KEY", "").strip()
FRED_ITEMS = {                    # code → (FRED series id, 메타 name)
    "us_real10y": ("DFII10", "미 10년 실질금리(TIPS)"),
}


def run_fred():
    if not FRED_KEY:
        print("[US] FRED_API_KEY 없음 — 실질금리 수집 건너뜀 (금·채권 자산 카드의 앵커 계산 불가)")
        return
    rows_meta = [{"code": c, "name": n, "market": "US", "category": "자산",
                  "role": "rate", "source": f"fred:{sid}"}
                 for c, (sid, n) in FRED_ITEMS.items()]
    sb.table("indicator_meta").upsert(rows_meta, on_conflict="code").execute()
    total, failed = 0, []
    for code, (sid, _name) in FRED_ITEMS.items():
        url = (f"https://api.stlouisfed.org/fred/series/observations?series_id={sid}"
               f"&api_key={FRED_KEY}&file_type=json&observation_start=2015-01-01")
        try:
            with urllib.request.urlopen(url, timeout=30) as r:
                obs = json.loads(r.read().decode("utf-8")).get("observations", [])
        except Exception as e:
            failed.append(code)
            print(f"  [US] {code} ({sid}): 오류 — {e}")
            continue
        rows = [{"market": "US", "dt": o["date"], "code": code, "value": float(o["value"])}
                for o in obs if o.get("value") not in ("", ".")]   # FRED 결측은 "."
        if not rows:
            failed.append(code)
            print(f"  [US] {code} ({sid}): 데이터 없음 — 건너뜀")
            continue
        upsert(rows)
        total += len(rows)
        print(f"  [US] {code} ({sid}): {len(rows)} rows")
    sb.table("ingest_log").insert(
        {"source": "fred", "market": "US", "rows": total,
         "status": "ok" if not failed else "partial"}).execute()
    print(f"[US] FRED 완료: 총 {total} rows" + (f"  (건너뜀: {', '.join(failed)})" if failed else ""))


if __name__ == "__main__":
    # 인자 없으면 미국+한국 둘 다 (크론이 인자 없이 호출). `python ingest.py KR` 로 개별 실행도 가능.
    markets = [a.upper() for a in sys.argv[1:]] or ["US", "KR"]
    for m in markets:
        run(m)
    if "US" in markets:                            # 미국 실질금리(FRED)는 yfinance 뒤에 별도 수집
        run_fred()
    if "KR" in markets:                            # 한국 국내 금리(ECOS)는 yfinance 뒤에 별도 수집
        run_ecos()
        run_ecos_cycle()                           # 경기 선행·동행지수 순환변동치(월별)
        run_kr_index_long()                        # 월말 코스피 장기(경기 국면 통계용)
        run_kr_investor()                          # 코스피·코스닥 투자자별 순매수 + 거래대금
        run_kr_shorting()                          # 코스피·코스닥 투자자별 공매도 (둘 다 KRX 로그인 필요)
