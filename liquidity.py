# liquidity.py — indicator_raw 읽어 유동성 지수 L(t) 계산 → liquidity_daily (미국 + 한국)
# 4성분(정규화 후 평균, 높을수록 '완화/풍부'):
#   금리(낮을수록) + 일드커브(가파를수록) + 환율(통화 강세) + 신용(스프레드 좁을수록)
#   유동성은 글로벌 지표(미 금리·달러·HYG/LQD)가 한국에도 작용 → 코드 단위로 조회.
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

NEEDED = ["us_10y", "us_3m", "dxy", "hyg", "iei",       # 미국 유동성
          "kr_3y", "kr_10y", "kr_corp3y", "usdkrw"]     # 한국 유동성(국내물 + 원/달러)

# 검증용 과거 기준일 (상식과 맞나: 2021 초완화 → 높음, 2022 긴축 → 낮음)
CHECKS = [("초완화 2021-08", "2021-08-16"),
          ("긴축전환 2022-10", "2022-10-14"),
          ("현재 부근 2024-07", "2024-07-15")]


def fetch_codes(codes):
    """지정 코드들의 indicator_raw 전체를 페이지네이션으로 가져온다(시장 무관)."""
    rows, step, start = [], 1000, 0
    while True:
        # dt,code 총순서로 정렬 — dt만으로 정렬하면 페이지 경계에서 같은 날짜 행이 중복/누락됨
        r = sb.table("indicator_raw").select("dt,code,value") \
              .in_("code", codes).order("dt").order("code") \
              .range(start, start + step - 1).execute().data
        rows += r
        if len(r) < step:
            break
        start += step
    return rows


def pct_rank(s, win=252):
    return s.rolling(win).apply(lambda x: (x.iloc[-1] > x.iloc[:-1]).mean() * 100, raw=False)


def band(v):
    if pd.isna(v):
        return None
    if v < 20: return "극단긴축"
    if v < 40: return "긴축"
    if v < 60: return "중립"
    if v < 80: return "완화"
    return "극단완화"


def compute(w, market):
    if market == "US":
        d = w[["us_10y", "us_3m", "dxy", "hyg", "iei"]].dropna()
        c_rate = 100 - pct_rank(d["us_10y"])              # 미10년물 높으면 긴축 → 뒤집기
        curve = d["us_10y"] - d["us_3m"]                  # 10년-3개월 (%p)
        c_curve = pct_rank(curve)                         # 커브 가파를수록 완화적
        c_fx = 100 - pct_rank(d["dxy"])                   # 강달러 = 긴축 → 뒤집기
        # 신용: HYG/IEI(듀레이션 근접 국채)↑ = 스프레드 좁음 = 완화. LQD는 장기물이라 금리에 오염돼 부적합.
        c_credit = pct_rank(d["hyg"] / d["iei"])
        raw_10y, raw_b, raw_krw = d["us_10y"], d["dxy"], None   # 카드: 미10년물 / DXY
    else:  # KR — 4성분 전부 국내물(커브·신용까지). 미국·글로벌 영향은 원/달러(c_fx)로 유입.
        d = w[["kr_3y", "kr_10y", "kr_corp3y", "usdkrw"]].dropna()
        c_rate = 100 - pct_rank(d["kr_10y"])                    # 국고채10년 높으면 긴축 → 뒤집기
        curve = d["kr_10y"] - d["kr_3y"]                        # 국고채 10년-3년 (%p)
        c_curve = pct_rank(curve)                              # 한국 커브 가파를수록 완화적
        c_fx = 100 - pct_rank(d["usdkrw"])                     # 원 약세(원/달러↑) = 긴축 → 뒤집기
        spread = d["kr_corp3y"] - d["kr_3y"]                   # 회사채-국고채 신용스프레드
        c_credit = 100 - pct_rank(spread)                     # 스프레드 넓을수록 신용경색=긴축 → 뒤집기
        raw_10y, raw_b, raw_krw = d["kr_10y"], spread, d["usdkrw"]  # 카드: 국고채10년 / 신용스프레드 / 원달러

    L = pd.concat([c_rate, c_curve, c_fx, c_credit], axis=1).mean(axis=1).ewm(span=10).mean()
    out = pd.DataFrame({"l_score": L, "c_rate": c_rate, "c_curve": c_curve,
                        "c_fx": c_fx, "c_credit": c_credit}).dropna()
    out["band"] = out["l_score"].map(band)
    # 헤드라인 원자료 수치(카드용) — anon은 indicator_raw 못 읽으니 여기 함께 저장.
    # ⚠️ 컬럼명은 US 기준이라 KR에선 의미가 다름: raw_us10y=국고채10년, raw_dxy=신용스프레드(%p).
    out["raw_us10y"] = raw_10y.reindex(out.index)
    out["raw_dxy"] = raw_b.reindex(out.index)
    out["raw_usdkrw"] = raw_krw.reindex(out.index) if raw_krw is not None else float("nan")
    out["raw_curve"] = curve.reindex(out.index)       # 일드커브 실제값(%p) — 툴팁용(양 시장 공통)
    return out


def main(markets):
    w = pd.DataFrame(fetch_codes(NEEDED))
    if w.empty:
        print("indicator_raw 에 유동성 지표가 없음 — ingest.py 를 먼저 실행하세요.")
        return
    w["dt"] = pd.to_datetime(w["dt"])
    w = w.drop_duplicates(subset=["dt", "code"])  # 페이지 경계 중복 방어
    w = w.pivot(index="dt", columns="code", values="value").sort_index()

    for market in markets:
        out = compute(w, market)
        def rnd(v, n):
            return None if pd.isna(v) else round(float(v), n)
        rows = [{"market": market, "dt": d.strftime("%Y-%m-%d"),
                 "l_score": round(float(r.l_score), 2), "band": r.band,
                 "c_rate": round(float(r.c_rate), 2), "c_curve": round(float(r.c_curve), 2),
                 "c_fx": round(float(r.c_fx), 2), "c_credit": round(float(r.c_credit), 2),
                 "raw_us10y": rnd(r.raw_us10y, 2), "raw_dxy": rnd(r.raw_dxy, 2),
                 "raw_usdkrw": rnd(r.raw_usdkrw, 2), "raw_curve": rnd(r.raw_curve, 2)}
                for d, r in out.iterrows()]
        for i in range(0, len(rows), 1000):
            sb.table("liquidity_daily").upsert(rows[i:i + 1000], on_conflict="market,dt").execute()
        print(f"[{market}] L(t) 적재 완료: {len(rows)}일")
        print(out[["l_score", "band"]].tail(5).round(1).to_string())
        print(f"[{market}] 과거 검증 — 완화/긴축이 상식과 맞나")
        for label, day in CHECKS:
            near = out[out.index <= day]
            if len(near):
                v = near.iloc[-1]["l_score"]
                print(f"  {label}: L={v:.0f}  → {band(v)}")
        print()


if __name__ == "__main__":
    markets = [a.upper() for a in sys.argv[1:]] or ["US", "KR"]
    main(markets)
