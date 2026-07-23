# sentiment.py — indicator_raw 읽어 S(t) 심리점수 계산 → sentiment_daily (미국 + 한국)
# v0 구성(4성분): 변동성(공포) + 모멘텀(탐욕) + 안전자산선호(탐욕) + 시장 폭(탐욕)
#   미국은 변동성=VIX(내재변동성). 한국은 VKOSPI를 못 받아 코스피 '실현변동성'으로 대체.
import os
import sys
from dotenv import load_dotenv
import pandas as pd
from supabase import create_client

try:  # 윈도우 콘솔(cp949)에서도 한글·기호 출력이 깨지지 않게
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

load_dotenv()
sb = create_client(os.environ["SUPABASE_URL"], os.environ["SUPABASE_SERVICE_KEY"])

# 시장별 지표 코드 매핑 + 검증용 과거 기준일
#   vol=None 이면 index 실현변동성을 공포 지표로 사용(한국). 아니면 그 코드를 VIX처럼 사용(미국).
MARKETS = {
    "US": {"index": "us_index", "bond": "us_bond", "ew": "rsp", "cw": "spy",
           "vol": "vix",
           "checks": [("코로나 폭락 2020-03", "2020-03-23"),
                      ("강세장 2021-11", "2021-11-19"),
                      ("약세장 2022-10", "2022-10-12")]},
    # 시장 폭 = ew-cw 20일 수익률차. 한국은 ew=코스닥·cw=코스피 → (코스닥-코스피) 위험선호.
    "KR": {"index": "kr_index", "bond": "kr_bond", "ew": "kr_kosdaq", "cw": "kr_index",
           "vol": None,
           "checks": [("코로나 폭락 2020-03", "2020-03-19"),
                      ("사상최고 2021-06", "2021-06-25"),
                      ("약세장 2022-09", "2022-09-30")]},
}


def fetch_raw(market):
    """indicator_raw 전체를 페이지네이션으로 가져온다 (API 1000행 제한 우회)."""
    rows, step, start = [], 1000, 0
    while True:
        r = sb.table("indicator_raw").select("dt,code,value") \
              .eq("market", market).order("dt").range(start, start + step - 1).execute().data
        rows += r
        if len(r) < step:
            break
        start += step
    return rows


def pct_rank(s, win=252):
    """각 시점 값이 지난 win일 분포에서 몇 %ile인지 (0~100)."""
    return s.rolling(win).apply(lambda x: (x.iloc[-1] > x.iloc[:-1]).mean() * 100, raw=False)


def band(v):
    if pd.isna(v):
        return None
    if v < 20: return "극단공포"
    if v < 40: return "공포"
    if v < 60: return "중립"
    if v < 80: return "탐욕"
    return "극단탐욕"


def compute(market):
    cfg = MARKETS[market]
    raw = fetch_raw(market)
    if not raw:
        print(f"[{market}] indicator_raw 가 비어있음 — ingest.py 를 먼저 실행하세요.")
        return None

    df = pd.DataFrame(raw)
    df["dt"] = pd.to_datetime(df["dt"])
    w = df.pivot(index="dt", columns="code", values="value").sort_index()
    # 필요한 지표가 모두 있는 날만 사용 — 반쪽 행 하나가 rolling 창을 오염시키는 것 방지
    #   (미국: 휴장일 VIX만 들어오는 행 / 한국: 동일가중 ETF 상장 이전 구간 등)
    w = w.dropna()

    idx = w[cfg["index"]]
    # ── 파생 지표 (4성분) ──
    mom = idx / idx.rolling(125).mean() - 1                             # 모멘텀 (탐욕)
    shv = idx.pct_change(20) - w[cfg["bond"]].pct_change(20)            # 위험선호(주식-채권): 주식이 이기면↑ (탐욕)
    brd = w[cfg["ew"]].pct_change(20) - w[cfg["cw"]].pct_change(20)     # 시장 폭 (탐욕): 동일가중-시총가중

    # 변동성(공포) → 뒤집기. 미국은 VIX, 한국은 코스피 20일 실현변동성.
    if cfg["vol"]:
        vol = w[cfg["vol"]]
    else:
        vol = idx.pct_change().rolling(20).std()
    c_vix = 100 - pct_rank(vol)   # 공포지표 → 뒤집기 (컬럼명은 c_vix로 공용)

    # ── 정규화(백분위) — 나머지는 탐욕지표 ──
    c_mom = pct_rank(mom)
    c_shv = pct_rank(shv)
    c_breadth = pct_rank(brd)
    s_raw = pd.concat([c_vix, c_mom, c_shv, c_breadth], axis=1).mean(axis=1)
    s = s_raw.ewm(span=10).mean()  # 10일 지수이동평균으로 평활 → 게이지로 읽히게

    out = pd.DataFrame({"s_score": s, "c_vix": c_vix, "c_mom": c_mom,
                        "c_shv": c_shv, "c_breadth": c_breadth}).dropna()
    out["band"] = out["s_score"].map(band)
    return out


def main(market):
    cfg = MARKETS[market]
    out = compute(market)
    if out is None or out.empty:
        print(f"[{market}] 계산 결과 없음 — 건너뜀")
        return

    # ── 적재 ──
    rows = [{"market": market, "dt": d.strftime("%Y-%m-%d"),
             "s_score": round(float(r.s_score), 2), "band": r.band,
             "c_vix": round(float(r.c_vix), 2), "c_mom": round(float(r.c_mom), 2),
             "c_shv": round(float(r.c_shv), 2), "c_breadth": round(float(r.c_breadth), 2)}
            for d, r in out.iterrows()]
    for i in range(0, len(rows), 1000):
        sb.table("sentiment_daily").upsert(rows[i:i + 1000], on_conflict="market,dt").execute()
    print(f"[{market}] S(t) 적재 완료: {len(rows)}일")

    # ── 검증: 최근값 + 과거 위기/과열 구간에 반응하는지 ──
    print(f"[{market}] 최근 5일")
    print(out[["s_score", "band"]].tail(5).round(1).to_string())
    print(f"[{market}] 과거 검증 — 공포/탐욕이 상식과 맞나")
    for label, day in cfg["checks"]:
        near = out[out.index <= day]
        if len(near):
            v = near.iloc[-1]["s_score"]
            print(f"  {label}: S={v:.0f}  → {band(v)}")
    print()


if __name__ == "__main__":
    markets = [a.upper() for a in sys.argv[1:]] or ["US", "KR"]
    for m in markets:
        main(m)
