# crossval.py — 매물대 모델 교차검증: '거래량 감쇠 추정'(A) vs '투자자 순매수 실측'(B)
#
#   A = profile.py의 매물대. 전체 거래량을 가격대에 뿌리고 회전율로 감쇠시켜
#       '아직 안 팔린 물량'을 추정한다. 가정(G&H 비례 소진)이 들어간 모델이다.
#   B = 투자자별(기관·외국인·개인·기타법인) 일별 순매수 수량을 그날 고가~저가에 뿌린 것.
#       순매수는 이미 '사서 안 판 것'이라 감쇠 가정이 필요 없다. 대신 주체가 4개뿐이라
#       같은 주체 안에서의 손바뀜(개인↔개인)은 안 잡히고, 창 이전의 물량도 모른다.
#
#   서로 데이터 출처도 가정도 다르므로, 둘이 같은 가격대를 지목하면 A가 검증된 것이다.
#   B는 KRX 정보데이터시스템 로그인이 필요하다(pykrx, .env의 KRX_ID/KRX_PW).
#
#   사용: python crossval.py                 → 삼성전자·SK하이닉스, 1년 창
#         python crossval.py 005930 --win 730
import os
import sys
import numpy as np
import pandas as pd
from dotenv import load_dotenv

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

load_dotenv()                       # KRX_ID/KRX_PW를 환경에 올린 뒤 pykrx를 임포트해야 로그인이 붙는다
import profile as vp                # noqa: E402  매물대 모델(A) 재사용
# 주체별 보유분포 코어(TYPES·day_spread·holdings_profile·avg_cost)는 holders.py로 옮겼다 —
# 대시보드 production이 본체고, holders는 pykrx를 지연 임포트해 로그인 차단에도 캐시 재계산이 돈다.
from holders import TYPES, day_spread, holdings_profile, avg_cost  # noqa: E402, F401
from pykrx import stock             # noqa: E402

DEFAULT = ["005930", "000660"]


def load_price(code, win_days):
    """stock_daily에서 창 구간 일봉 + 분할 보정."""
    rows = vp.page("stock_daily", "dt,high,low,close,tval,shares,mktcap", code=code)
    df = pd.DataFrame(rows)
    df["dt"] = pd.to_datetime(df["dt"])
    df = df.set_index("dt").astype(float)
    df = df[(df["close"] > 0) & (df["high"] > 0) & (df["mktcap"] > 0)]
    f, events = vp.split_adjust(df)
    for c in ("high", "low", "close"):
        df[c] = df[c] * f
    df = df.rename(columns={"high": "High", "low": "Low", "close": "Close"})
    return df[df.index >= df.index[-1] - pd.Timedelta(days=win_days)], events


def wmean(profile, edges):
    mid = (edges[:-1] + edges[1:]) / 2
    s = profile.sum()
    return float((profile * mid).sum() / s) if s > 0 else float("nan")


def peak(profile, edges):
    b = int(np.argmax(profile))
    return float(edges[b]), float(edges[b + 1])


def run(code, win_days, nbins=60):
    df, events = load_price(code, win_days)
    if len(df) < 60:
        print(f"[{code}] 데이터 부족({len(df)}일) — 건너뜀")
        return
    frm, to = df.index[0].strftime("%Y%m%d"), df.index[-1].strftime("%Y%m%d")
    px = float(df["Close"].iloc[-1])
    name = stock.get_market_ticker_name(code)
    print(f"\n{'=' * 72}\n{name}({code}) · 최근 {win_days}일 ({df.index[0].date()}~{df.index[-1].date()}) "
          f"· 현재가 {px:,.0f}\n{'=' * 72}")
    for e in events:
        print(f"  (주가 보정: {e})")

    # ── A: 매물대 모델 (거래수량 배분 + 회전율 감쇠) ──
    V = np.clip(df["tval"] / df["mktcap"], 0, 0.5).to_numpy()
    edgesA, remA, _ = vp.build(df, nbins, V, vp.qty(df))
    edges = edgesA                                    # A와 B가 같은 구간 경계를 쓰도록 통일
    remA = remA / remA.sum() * 100

    # ── B: 투자자 순매수 실측 (주체별 보유 물량의 매입 가격대) ──
    vol = stock.get_market_trading_volume_by_date(frm, to, code).reindex(df.index).fillna(0)
    val = stock.get_market_trading_value_by_date(frm, to, code).reindex(df.index).fillna(0)
    totB, invB = holdings_profile(vol, df["Low"].to_numpy(), df["High"].to_numpy(), edges)
    remB = totB / totB.sum() * 100

    # ── 비교 ──
    corr = float(np.corrcoef(remA, remB)[0, 1])
    mid = (edges[:-1] + edges[1:]) / 2
    upA = remA[mid > px].sum()
    upB = remB[mid > px].sum()
    pa, pb = peak(remA, edges), peak(remB, edges)
    print(f"\n  [분포 일치도] 가격대별 상관 {corr:+.2f}")
    print(f"  {'':14}{'A 모델(거래량 감쇠)':>24}{'B 실측(투자자 순매수)':>26}")
    print(f"  {'가중평균 가격':14}{wmean(remA, edges):>24,.0f}{wmean(remB, edges):>26,.0f}")
    print(f"  {'최대 매물 구간':14}{f'{pa[0]:,.0f}~{pa[1]:,.0f}':>24}{f'{pb[0]:,.0f}~{pb[1]:,.0f}':>26}")
    print(f"  {'현재가 위 매물':14}{f'{upA:.0f}%':>24}{f'{upB:.0f}%':>26}")

    print("\n  [주체별 추정 평균 매입단가] — 창 구간 내 누적 순매수 기준")
    for t, (pos, c) in avg_cost(vol, val).items():
        if pos > 0:
            print(f"    {t:8} 보유 {pos/1e6:8.2f}백만주 · 평단 {c:>10,.0f}"
                  f" · 평가손익 {px/c*100-100:+.1f}%")
        else:
            print(f"    {t:8} 창 구간 순매도 (보유 물량 없음)")


if __name__ == "__main__":
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    win = 365
    if "--win" in sys.argv:
        win = int(sys.argv[sys.argv.index("--win") + 1])
        args = [a for a in args if a != str(win)]
    for c in args or DEFAULT:
        run(c, win)
