# ai_cycle.py — AI 사이클 계기판 원자료 → ai_daily (반도체 밸류체인 주가·상대강도)
# ⚠️ 예측 지표가 아니다. 반도체 실물지표(한국수출·자본재수주·재고·PPI)의 붕괴 예측력을
#   검증했더니 오경보율 70~82%로 기준선(71%)을 하나도 넘지 못했다(2026-07 검증).
#   이 테이블은 '지금 얼마나 쏠려 있나'를 기술할 뿐, 쏠림의 해소 시점은 말하지 못한다.
#
# 상대강도 = 종목 ÷ 자국 지수. 같은 거래소끼리라 거래일 캘린더가 일치한다:
#   TSMC÷가권(TWSE) · 삼성전자÷코스피 · 하이닉스÷코스피(KRX) · SOX÷S&P500(미국)
# fuel.py 와 같은 자기완결형 — indicator_raw 안 거치고 yfinance 직접 호출.
import os
import sys
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
START = "2010-01-01"      # 2011·2015·2018·2020·2021·2024 반도체 사이클을 담는 범위

PAIRS = [  # (분자 코드, 분자 심볼, 분모 코드, 분모 심볼, 비율 컬럼)
    ("tsmc", "2330.TW", "twii", "^TWII", "r_tsmc"),
    ("samsung", "005930.KS", "kospi", "^KS11", "r_samsung"),
    ("hynix", "000660.KS", "kospi", "^KS11", "r_hynix"),
    ("sox", "^SOX", "spx", "^GSPC", "r_sox"),
]


def fetch(sym):
    s = yf.Ticker(sym).history(start=START, auto_adjust=True)["Close"].dropna()
    s.index = pd.to_datetime(s.index.date)
    return s


def main():
    cols = {}
    for num, nsym, den, dsym, _ in PAIRS:
        for code, sym in ((num, nsym), (den, dsym)):
            if code not in cols:
                cols[code] = fetch(sym)
                print(f"  {code:8s} {sym:10s} {len(cols[code])}일")
    w = pd.DataFrame(cols).sort_index()
    for num, _, den, _, rcol in PAIRS:
        w[rcol] = w[num] / w[den]     # 양쪽 다 있는 날만 값이 생김(캘린더 불일치는 NaN)

    rows = []
    for dt, r in w.iterrows():
        row = {"dt": dt.strftime("%Y-%m-%d")}
        for c in w.columns:
            v = r[c]
            row[c] = None if pd.isna(v) else round(float(v), 6)
        rows.append(row)
    for i in range(0, len(rows), 1000):
        sb.table("ai_daily").upsert(rows[i:i + 1000], on_conflict="dt").execute()
    print(f"ai_daily 적재 완료: {len(rows)}일 ({w.index.min().date()} ~ {w.index.max().date()})")

    # 검증 출력 — 각 상대강도의 125일 고점 대비 (계기판 카드와 같은 정의)
    for _, _, _, _, rcol in PAIRS:
        s = w[rcol].dropna()
        if len(s) < 125:
            continue
        stretch = (s.iloc[-1] / s.iloc[-125:].max() - 1) * 100
        print(f"  {rcol:10s} 최신 {s.iloc[-1]:.4f}   125일 고점 대비 {stretch:+.1f}%")


if __name__ == "__main__":
    main()
