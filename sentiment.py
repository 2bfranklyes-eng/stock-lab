# sentiment.py — indicator_raw 읽어 S(t) 심리점수 계산 → sentiment_daily
# v0 구성: 변동성(VIX) + 모멘텀(지수 vs 125일선) + 안전자산선호(주식-채권 20일)
import os
from dotenv import load_dotenv
import pandas as pd
from supabase import create_client

load_dotenv()
sb = create_client(os.environ["SUPABASE_URL"], os.environ["SUPABASE_SERVICE_KEY"])
MARKET = "US"


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


def main():
    raw = fetch_raw(MARKET)
    if not raw:
        print("indicator_raw 가 비어있음 — ingest.py 를 먼저 실행하세요.")
        return

    df = pd.DataFrame(raw)
    df["dt"] = pd.to_datetime(df["dt"])
    w = df.pivot(index="dt", columns="code", values="value").sort_index()
    # 5개 지표가 모두 있는 날만 사용 — 미국 휴장일에 VIX만 값이 들어오는 등
    # 불완전한 행 하나가 rolling 창을 오염시켜 이후 전체가 NaN 되는 것을 방지
    w = w.dropna()

    # ── 파생 지표 ──
    vix = w["vix"]                                                    # 변동성 (공포)
    mom = w["us_index"] / w["us_index"].rolling(125).mean() - 1       # 모멘텀 (탐욕)
    shv = w["us_index"].pct_change(20) - w["us_bond"].pct_change(20)  # 안전자산선호 (탐욕)
    brd = w["rsp"].pct_change(20) - w["spy"].pct_change(20)           # 시장 폭 (탐욕): 동일가중-시총가중

    # ── 정규화(백분위) + 방향 보정 ──
    c_vix = 100 - pct_rank(vix)   # 공포지표 → 뒤집기
    c_mom = pct_rank(mom)         # 탐욕지표
    c_shv = pct_rank(shv)         # 탐욕지표
    c_breadth = pct_rank(brd)     # 탐욕지표 (시장 폭)
    s_raw = pd.concat([c_vix, c_mom, c_shv, c_breadth], axis=1).mean(axis=1)
    s = s_raw.ewm(span=10).mean()  # 10일 지수이동평균으로 평활 → 게이지로 읽히게

    out = pd.DataFrame({"s_score": s, "c_vix": c_vix, "c_mom": c_mom,
                        "c_shv": c_shv, "c_breadth": c_breadth}).dropna()
    out["band"] = out["s_score"].map(band)

    # ── 적재 ──
    rows = [{"market": MARKET, "dt": d.strftime("%Y-%m-%d"),
             "s_score": round(float(r.s_score), 2), "band": r.band,
             "c_vix": round(float(r.c_vix), 2), "c_mom": round(float(r.c_mom), 2),
             "c_shv": round(float(r.c_shv), 2), "c_breadth": round(float(r.c_breadth), 2)}
            for d, r in out.iterrows()]
    for i in range(0, len(rows), 1000):
        sb.table("sentiment_daily").upsert(rows[i:i + 1000], on_conflict="market,dt").execute()
    print(f"S(t) 적재 완료: {len(rows)}일\n")

    # ── 검증: 최근값 + 과거 위기 구간에 반응하는지 ──
    print("[최근 5일]")
    print(out[["s_score", "band"]].tail(5).round(1).to_string())
    print("\n[과거 검증 — 공포/탐욕이 상식과 맞나]")
    for label, day in [("코로나 폭락 2020-03", "2020-03-23"),
                       ("강세장 2021-11", "2021-11-19"),
                       ("약세장 2022-10", "2022-10-12")]:
        near = out[out.index <= day]
        if len(near):
            v = near.iloc[-1]["s_score"]
            print(f"  {label}: S={v:.0f}  → {band(v)}")


if __name__ == "__main__":
    main()
