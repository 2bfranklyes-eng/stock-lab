# ingest.py — 원천 지표 수집 → Supabase indicator_raw (미국 + 한국)
import os
import sys
from dotenv import load_dotenv
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
#     한국 유동성은 이 글로벌 지표 + usdkrw(원/달러) + kr_bond(금리)로 계산.
JOBS = {
    "US": {"vix": "^VIX", "us_index": "^GSPC", "us_bond": "TLT",
           "rsp": "RSP", "spy": "SPY",
           "us_10y": "^TNX", "us_3m": "^IRX", "dxy": "DX-Y.NYB",
           "hyg": "HYG", "iei": "IEI"},
    "KR": {"kr_index": "^KS11", "kr_bond": "148070.KS", "kr_kosdaq": "^KQ11",
           "usdkrw": "USDKRW=X"},
}


def fetch_close(symbol, start="2015-01-01"):
    """야후 파이낸스에서 종가 시계열(Series)을 가져온다."""
    df = yf.Ticker(symbol).history(start=start, auto_adjust=True)
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


def run(market):
    total = 0
    for code, sym in JOBS[market].items():
        rows = to_rows(fetch_close(sym), market, code)
        upsert(rows)
        total += len(rows)
        print(f"  [{market}] {code} ({sym}): {len(rows)} rows")
    sb.table("ingest_log").insert(
        {"source": "yfinance", "market": market, "rows": total, "status": "ok"}).execute()
    print(f"[{market}] 완료: 총 {total} rows")


if __name__ == "__main__":
    # 인자 없으면 미국+한국 둘 다 (크론이 인자 없이 호출). `python ingest.py KR` 로 개별 실행도 가능.
    markets = [a.upper() for a in sys.argv[1:]] or ["US", "KR"]
    for m in markets:
        run(m)
