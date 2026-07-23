# ingest.py — 미국 원천 지표 수집 → Supabase indicator_raw
import os
from dotenv import load_dotenv
import yfinance as yf
from supabase import create_client

load_dotenv()
sb = create_client(os.environ["SUPABASE_URL"], os.environ["SUPABASE_SERVICE_KEY"])


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


def run_us():
    jobs = {"vix": "^VIX", "us_index": "^GSPC", "us_bond": "TLT",
            "rsp": "RSP", "spy": "SPY"}
    total = 0
    for code, sym in jobs.items():
        rows = to_rows(fetch_close(sym), "US", code)
        upsert(rows)
        total += len(rows)
        print(f"  {code} ({sym}): {len(rows)} rows")
    sb.table("ingest_log").insert(
        {"source": "yfinance", "market": "US", "rows": total, "status": "ok"}).execute()
    print(f"완료: 총 {total} rows")


if __name__ == "__main__":
    run_us()
