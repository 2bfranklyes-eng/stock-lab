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

NEEDED = ["us_10y", "us_3m", "dxy", "hyg", "iei", "us_credit_spread",  # 미국 유동성
          "kr_3y", "kr_10y", "kr_corp3y", "usdkrw",                 # 한국 유동성(국내물 + 원/달러)
          "kr_cd91", "kr_call"]                                     # 한국 커브의 단기 쪽 후보
# 커브 단기물 우선순위 — 앞에서부터 '충분히 쌓인' 첫 코드를 쓴다.
#   미국은 10년-3개월(정책금리 대비)인데 한국은 3년물을 써서 커브가 정책 스탠스를 못 읽었다.
#   ECOS 항목코드가 틀리면 수집이 비므로, 국고채3년으로 안전하게 되돌아간다.
KR_SHORT = ["kr_cd91", "kr_call", "kr_3y"]

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


# 백분위 창 = 3년(756일). 심리(1년)와 달리 금리·환율은 정책 사이클이 몇 년짜리라,
# 1년 창이면 "오래된 완화/긴축"이 곧 중립으로 읽혀버린다. 실제로 창을 늘리니 체크포인트가
# 1/5 → 3/5로 개선됐다 (2021-08 초완화를 54=중립 → 64=완화로 제대로 읽음).
# min_periods=252 는 이력 보존용 — 초기 구간은 가능한 만큼의 창으로 계산한다(안 그러면 3년치 손실).
WIN = 756


def pct_rank(s, win=WIN, minp=252):
    return s.rolling(win, min_periods=minp).apply(
        lambda x: (x.iloc[-1] > x.iloc[:-1]).mean() * 100, raw=False)


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
        # 수준 그대로 백분위를 매기면 평온기에 계속 1년 신고가라 상위밴드에 59% 체류 = 사실상 상수.
        # → '60일 평균 대비'로 바꿔 국면 변화만 잡는다 (포화 59%→16%, 동시점 상관 0.32→0.48).
        cr = d["hyg"] / d["iei"]
        c_credit = pct_rank(cr / cr.rolling(60).mean())
        raw_10y, raw_b, raw_krw = d["us_10y"], d["dxy"], None   # 카드: 미10년물 / DXY
        # 신용스프레드 절대수준(%p) — c_credit 과 별개다. c_credit 은 60일 평균 대비 상대값이라
        # 평온기엔 중립을 가리키고, '지금이 닷컴·금융위기 초입 대비 어디인가'를 답하지 못한다.
        # dropna 대상에 넣지 않는다 — BAA10Y 결측이 유동성 지수 전체를 날리면 안 된다.
        raw_cr = w["us_credit_spread"] if "us_credit_spread" in w.columns else None
    else:  # KR — 4성분 전부 국내물(커브·신용까지). 미국·글로벌 영향은 원/달러(c_fx)로 유입.
        short = next((c for c in KR_SHORT if c in w.columns and w[c].notna().sum() > 500), "kr_3y")
        d = w[list(dict.fromkeys(["kr_3y", "kr_10y", "kr_corp3y", "usdkrw", short]))].dropna()
        c_rate = 100 - pct_rank(d["kr_10y"])                    # 국고채10년 높으면 긴축 → 뒤집기
        curve = d["kr_10y"] - d[short]                          # 국고채10년 - 단기금리 (%p)
        c_curve = pct_rank(curve)                              # 한국 커브 가파를수록 완화적
        print(f"  [KR] 커브 단기물: {short}" + ("  ⚠️ ECOS 단기금리 미수집 → 국고채3년 대체"
                                             if short == "kr_3y" else ""))
        c_fx = 100 - pct_rank(d["usdkrw"])                     # 원 약세(원/달러↑) = 긴축 → 뒤집기
        spread = d["kr_corp3y"] - d["kr_3y"]                   # 회사채-국고채 신용스프레드
        c_credit = 100 - pct_rank(spread)                     # 스프레드 넓을수록 신용경색=긴축 → 뒤집기
        raw_10y, raw_b, raw_krw = d["kr_10y"], spread, d["usdkrw"]  # 카드: 국고채10년 / 신용스프레드 / 원달러
        raw_cr = spread                                        # 한국은 국내물 스프레드가 곧 절대수준

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
    # 신용스프레드 절대값(%p). dropna() 를 먼저 거는 게 핵심 —
    # raw_cr 은 피벗 컬럼이라 모든 날짜 라벨을 갖고 값만 NaN 이다. 그 상태로 reindex(method="ffill")
    # 하면 라벨이 이미 존재하므로 ffill 이 동작하지 않고 NaN 이 그대로 남는다.
    # FRED BAA10Y 는 하루 늦게 올라와서, 이걸 놓치면 항상 '최신 행만 null' 이 된다.
    out["raw_credit"] = (raw_cr.dropna().reindex(out.index, method="ffill") if raw_cr is not None
                         else pd.Series(float("nan"), index=out.index))
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
                 "raw_credit": rnd(r.raw_credit, 2),
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
