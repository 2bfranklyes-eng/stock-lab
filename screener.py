# screener.py — 개별 종목 재무 스냅샷 + 월말 종가 → stock_meta / stock_monthly
# 스크리너(A)와 포트폴리오 구성·진단(B)의 공용 원자료. 주 1회면 충분하다 —
# 재무는 분기 단위로만 바뀌고, 발표까지 분기말+45일, 야후 반영까지 며칠~2주가 더 걸린다.
#
# ⚠️ 이 데이터로 '검증된 전략'은 못 만든다(sql/stocks.sql 주석 참고).
#    생존편향(현재 상장 종목만) · 시점데이터 부재(최신 수정본) · 재무이력 4~5년.
#    화면에서도 '과거에 이랬다'까지만 말한다.
import os
import sys
import time
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

TOP_N = int(os.environ.get("SCREENER_TOP_N", "500"))   # 시총 상위 몇 종목까지
MONTHS = 121                                            # 월말 종가 보관 개월 수(≈10년)
# 유니버스 밖이어도 반드시 포함할 코드(보유 종목 등). 쉼표 구분.
ALWAYS = [c.strip() for c in os.environ.get("SCREENER_ALWAYS", "").split(",") if c.strip()]
BENCH = {"KOSPI": "^KS11", "KOSDAQ": "^KQ11"}


# FDR의 Market 값 → 우리 표기. 'KOSDAQ GLOBAL'은 코스닥 안의 우량기업 세그먼트라
# 값이 따로 나오는데, 이걸 빼먹으면 50종목이 통째로 사라진다(SFA넥셀 등). KONEX도 받아
# 두되 시총 상위에는 사실상 안 들어오므로 SCREENER_ALWAYS 로만 실효가 있다.
MARKET_MAP = {"KOSPI": "KOSPI", "KOSDAQ": "KOSDAQ",
              "KOSDAQ GLOBAL": "KOSDAQ", "KONEX": "KONEX"}


def universe():
    """FDR 전 종목 목록에서 시총 상위 N + 지정 코드. Marcap이 있어 한 번에 순위가 난다."""
    import FinanceDataReader as fdr
    d = fdr.StockListing("KRX")
    d = d[d["Market"].isin(MARKET_MAP)].dropna(subset=["Marcap"]).copy()
    d["Market"] = d["Market"].map(MARKET_MAP)   # KOSDAQ GLOBAL → KOSDAQ 로 통일
    top = d.nlargest(TOP_N, "Marcap")
    extra = d[d["Code"].isin(ALWAYS) & ~d["Code"].isin(top["Code"])]
    out = pd.concat([top, extra])
    print(f"유니버스: 시총 상위 {len(top)} + 지정 {len(extra)} = {len(out)}종목")
    return out


def ysym(code, market):
    # 코스닥(글로벌 세그먼트 포함)·코넥스는 .KQ, 코스피는 .KS
    return f"{code}.{'KS' if market == 'KOSPI' else 'KQ'}"


def snapshot(row):
    """한 종목의 재무 지표. 한국 종목은 야후가 PER/PBR을 안 줘서 직접 계산한다.
       PER = 시총÷순이익,  PBR = 시총÷자본 = PER × ROE (자본 = 순이익÷ROE)."""
    info = yf.Ticker(ysym(row["Code"], row["Market"])).info
    mc = info.get("marketCap")
    ni = info.get("netIncomeToCommon")
    roe = info.get("returnOnEquity")
    per = mc / ni if mc and ni and ni > 0 else None
    pbr = per * roe if per and roe and roe > 0 else None
    return {
        "code": row["Code"], "name": row["Name"], "market": row["Market"],
        "sector": info.get("sector"), "industry": info.get("industry"),
        "close": float(row["Close"]) if pd.notna(row["Close"]) else None,
        "marcap": float(row["Marcap"]),
        "per": per, "pbr": pbr, "roe": roe,
        "debt_to_equity": info.get("debtToEquity"),
        "op_margin": info.get("operatingMargins"),
        "profit_margin": info.get("profitMargins"),
        "rev_growth": info.get("revenueGrowth"),
        "earn_growth": info.get("earningsGrowth"),
        "div_yield": info.get("dividendYield"),
        "beta": info.get("beta"),
    }


def rnd(v, n=4):
    if v is None or (isinstance(v, float) and pd.isna(v)):
        return None
    try:
        return round(float(v), n)
    except (TypeError, ValueError):
        return None


def run_meta(uni):
    rows, miss = [], {}
    t0 = time.time()
    for i, (_, r) in enumerate(uni.iterrows(), 1):
        try:
            s = snapshot(r)
        except Exception as e:
            print(f"  [{r['Code']} {r['Name']}] 실패 — {str(e)[:60]}")
            continue
        for k, v in s.items():
            if v is None and k not in ("code", "name", "market"):
                miss[k] = miss.get(k, 0) + 1
        rows.append({k: (rnd(v) if isinstance(v, (int, float)) and k != "code" else v)
                     for k, v in s.items()})
        if i % 100 == 0:
            print(f"  {i}/{len(uni)}  ({time.time() - t0:.0f}초)")
    for i in range(0, len(rows), 500):
        sb.table("stock_meta").upsert(rows[i:i + 500], on_conflict="code").execute()
    print(f"stock_meta 적재: {len(rows)}종목 ({time.time() - t0:.0f}초)")
    # 야후는 비공식 스크래퍼라 필드가 조용히 사라진다 → 결측률을 남겨 이상을 조기에 알아채게
    print("  필드별 결측:", ", ".join(
        f"{k} {v}({v / len(rows) * 100:.0f}%)" for k, v in sorted(miss.items(), key=lambda x: -x[1])[:8]) or "없음")
    return rows


def run_monthly(uni):
    """월별 종가. 일별이면 프론트가 못 받는다 — 포트폴리오 단위 분석엔 월 단위로 충분.
    ※ 진행 중인 달은 '그 달 마지막 거래일까지의 최신 종가'가 들어간다(월말 확정치가 아님)."""
    syms = [ysym(r["Code"], r["Market"]) for _, r in uni.iterrows()]
    code_of = {ysym(r["Code"], r["Market"]): r["Code"] for _, r in uni.iterrows()}
    for b, s in BENCH.items():
        syms.append(s)
        code_of[s] = b

    rows, done = [], 0
    for i in range(0, len(syms), 100):     # 한 번에 다 부르면 야후가 막는다
        chunk = syms[i:i + 100]
        d = yf.download(" ".join(chunk), period="10y", interval="1mo",
                        progress=False, auto_adjust=True, group_by="ticker")
        for sym in chunk:
            try:
                s = (d[sym]["Close"] if isinstance(d.columns, pd.MultiIndex) else d["Close"]).dropna()
            except (KeyError, TypeError):
                continue
            for dt, v in s.tail(MONTHS).items():
                # 라벨을 반드시 '그 달 1일'로 맞춘다 — 야후가 종목에 따라 월중 날짜로 주는 경우가
                # 있는데(상장 직후 등), 그러면 다른 종목과 겹치는 달이 없어져 시뮬레이션이 통째로 막힌다.
                rows.append({"code": code_of[sym],
                             "dt": pd.Timestamp(dt).strftime("%Y-%m-01"),
                             "close": rnd(v, 2)})
            done += 1
        print(f"  월말종가 {min(i + 100, len(syms))}/{len(syms)}")
    for i in range(0, len(rows), 1000):
        sb.table("stock_monthly").upsert(rows[i:i + 1000], on_conflict="code,dt").execute()
    print(f"stock_monthly 적재: {done}종목 / {len(rows)}행")


if __name__ == "__main__":
    uni = universe()
    run_meta(uni)
    run_monthly(uni)
