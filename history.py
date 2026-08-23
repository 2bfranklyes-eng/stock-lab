# history.py — 2015년 이전 위기 리플레이용 과거 시세 (asset_daily 는 2015년부터)
#
# 왜 별도 모듈인가 — allocation_shock.py 의 위기 리플레이는 asset_daily 를 쓰는데 그 테이블은
# 2015-01-01 부터다. 닷컴(2000)·금융위기(2007)를 같은 표에 얹으려면 그 구간만 외부에서 받아야 한다.
# Supabase 에 적재하지 않고 실행할 때마다 받는다 — 과거 구간은 값이 변하지 않으니 저장할 이유가
# 없고, 무료 티어 500MB 를 이 용도로 쓰는 건 낭비다(README 의 용량 표 참조).
#
# ⚠️ 자산 이름은 ASSETS 와 같지만 '같은 상품'이 아닐 수 있다 —
#    · dbc : DBC ETF 는 2006-02 상장이라 그 이전 구간은 S&P GSCI 지수로 대체한다.
#            GSCI 는 에너지 비중이 커서 DBC 와 수익률이 다르다. 웹 카드에 이 사실을 표기할 것.
#    · gold: GC=F 선물은 2000-08-30 부터 → 닷컴 구간(2000-03 시작)은 커버 못 해 자동 제외된다.
#    · us_bond: TLT 는 2002-07-30 상장 → 닷컴 구간 제외, 금융위기는 커버.
#    · kr_bond·btc: 해당 시기 시세원이 없다. 제외되는 게 맞다(억지 대체는 통계를 오염시킨다).
#    구간을 다 못 채우는 자산은 allocation_shock.py 가 알아서 건너뛴다(NaN 검사).
import json
import os
import urllib.request

import pandas as pd

# 자산 → 후보 티커(우선순위). 구간을 완전히 덮는 첫 후보를 쓴다.
HIST_SOURCES = {
    "us_index": [("yf", "^GSPC")],
    "kr_index": [("yf", "^KS11")],
    "gold":     [("yf", "GC=F")],
    "us_bond":  [("yf", "TLT")],
    "dbc":      [("yf", "DBC"), ("yf", "^SPGSCI")],   # 실물 ETF 우선, 없으면 지수로 대체
    "usdkrw":   [("fred", "DEXKOUS")],
}
PROXY_NOTE = {"^SPGSCI": "DBC 미상장 구간 — S&P GSCI 지수로 대체"}


def _fred(sid, start, end):
    key = os.environ.get("FRED_API_KEY", "").strip()
    if not key:
        return pd.Series(dtype=float)
    url = (f"https://api.stlouisfed.org/fred/series/observations?series_id={sid}"
           f"&api_key={key}&file_type=json&observation_start={start}&observation_end={end}")
    obs = json.load(urllib.request.urlopen(url, timeout=30))["observations"]
    s = pd.Series({o["date"]: float(o["value"]) for o in obs if o.get("value") not in ("", ".")})
    s.index = pd.to_datetime(s.index)
    return s.sort_index()


def _yf(ticker, start, end):
    import yfinance as yf
    df = yf.download(ticker, start=start, end=end, progress=False, auto_adjust=False)
    if df is None or df.empty:
        return pd.Series(dtype=float)
    s = df["Close"]
    if hasattr(s, "columns"):          # yfinance 버전에 따라 MultiIndex 로 온다
        s = s.iloc[:, 0]
    return s.dropna()


def panel(a0, a1, pad_days=40):
    """[a0, a1] 구간을 덮는 과거 시세 패널. 구간을 못 덮는 자산은 아예 넣지 않는다.

    pad_days — 시작 전 여유. reindex(method='ffill') 가 구간 첫날을 채우려면 그 이전 값이 필요하다.
    """
    lo = (pd.Timestamp(a0) - pd.Timedelta(days=pad_days)).strftime("%Y-%m-%d")
    hi = (pd.Timestamp(a1) + pd.Timedelta(days=5)).strftime("%Y-%m-%d")
    out, used = {}, {}
    for asset, cands in HIST_SOURCES.items():
        for kind, tk in cands:
            try:
                s = _yf(tk, lo, hi) if kind == "yf" else _fred(tk, lo, hi)
            except Exception as e:
                print(f"  [{asset}] {tk} 실패: {e}")
                continue
            # 구간 시작·끝을 실제로 덮는지 확인 — 부분 구간은 mdd 를 과소평가하므로 쓰지 않는다.
            if len(s) < 30 or s.index[0] > pd.Timestamp(a0) or s.index[-1] < pd.Timestamp(a1):
                continue
            out[asset], used[asset] = s, tk
            break
        if asset not in out:
            print(f"  [{asset}] 구간 {a0}~{a1} 을 덮는 시세원 없음 — 제외")
    return out, used
