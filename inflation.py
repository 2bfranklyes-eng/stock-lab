# inflation.py — indicator_raw 읽어 물가지수 I(t) 계산 → inflation_daily (미국 + 한국)
# 4성분(정규화 후 평균, 높을수록 '물가 압력↑'). CPI는 월간·후행이라, 시장이 매일 반영하는
# '물가 압력'을 유동성과 똑같은 방식(시장 데이터·퍼센타일)으로 잰다. FRED 키 불필요.
#   기대인플레(TIP/IEF) + 에너지(WTI) + 식품(곡물 3종) + 산업금속(구리)
#
# v0(USO·DBC·DBB) 에서 바뀐 이유 — 둘 다 구조적 결함이었다:
#   ① 선물 롤오버 ETF는 콘탱고에서 가격이 깎여 '물가 수준'의 대리변수가 못 된다.
#      2015~2026 누적: USO -14% vs 실제 WTI +70% (84%p 괴리, 일간 상관도 0.50뿐).
#   ② DBC(원자재)는 구성의 절반이 에너지 → 유가를 두 번 세는 꼴. 성분 상관 USO↔DBC 0.84.
#      곡물로 바꾸니 에너지와 상관 0.40으로 새 정보가 들어오고 최대중복 0.84→0.68.
#      WTI 단독과의 상관은 0.83으로 v0와 같다(= 유가 지수로 퇴화하지 않음).
#      ※ 'ETF만 원물로' 바꾼 안(BE+WTI+GSCI+구리)은 오히려 0.88로 더 유가 지수에 가까워져 탈락.
#
# 한국: 물가 재료는 글로벌(유가·곡물·구리)이 그대로 작용하되, 실제로 치르는 값은 원화 기준이다.
#   → 원자재를 원/달러로 환산해 넣는다. usdkrw를 '기대인플레 성분'으로 따로 쓰던 v0는
#     유동성 c_fx(= 100 - pct_rank(usdkrw))와 상관이 정확히 -1.00이라, 두 요인이
#     설계상 반대로 움직이게 만들었다. 환산 방식으로 바꾸니 그 결합이 -0.23 → -0.08로 풀린다.
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

NEEDED = ["tip", "ief", "usdkrw", "wti", "copper", "corn", "wheat", "soy", "gsci"]
GRAINS = ["corn", "wheat", "soy"]          # 등가중 곡물지수로 합성 → 식품 성분
# 성분 점수(0~100)만 보면 "에너지 90"이 무슨 뜻인지 와닿지 않아, 대응하는 원물 시세를 같이 싣는다.
#   c_energy→WTI · c_metal→구리 · c_food→곡물(지수라 카드엔 안 씀) · 한국은 원/달러도
RAW = ["wti", "copper", "gsci", "usdkrw"]

# 검증용 과거 기준일 (상식과 맞나: 2021~22 인플레 급등 → 높음, 2020 코로나 초기 → 낮음)
CHECKS = [("코로나 저물가 2020-05", "2020-05-15"),
          ("인플레 급등 2022-06", "2022-06-15"),
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
    if v < 20: return "극단저물가"
    if v < 40: return "저물가"
    if v < 60: return "중립"
    if v < 80: return "고물가"
    return "극단고물가"


def compute(w, market):
    cols = ["tip", "ief", "wti", "copper"] + GRAINS + (["usdkrw"] if market == "KR" else [])
    d = w[cols].dropna()
    grain = (d[GRAINS] / d[GRAINS].iloc[0]).mean(axis=1)   # 등가중 곡물지수(옥수수·밀·대두)
    # 한국은 실제로 치르는 값이 원화 기준 → 원자재에 원/달러를 곱한다. 기대인플레는 글로벌 공통.
    fx = d["usdkrw"] if market == "KR" else 1.0

    c_be = pct_rank(d["tip"] / d["ief"])          # 물가연동채/국채↑ = 기대인플레↑
    c_energy = pct_rank(d["wti"] * fx)            # 유가↑ = 물가↑
    c_food = pct_rank(grain * fx)                 # 곡물↑ = 식품물가↑
    c_metal = pct_rank(d["copper"] * fx)          # 구리↑ = 실물수요·물가↑

    I = pd.concat([c_be, c_energy, c_food, c_metal], axis=1).mean(axis=1).ewm(span=10).mean()
    out = pd.DataFrame({"i_score": I, "c_be": c_be, "c_energy": c_energy,
                        "c_food": c_food, "c_metal": c_metal}).dropna()
    out["band"] = out["i_score"].map(band)

    # 실제 수치는 점수 계산과 분리 — dropna 대상에 넣으면 원물 휴장일에 점수 이력이 잘린다.
    # 휴장으로 빈 날은 직전 시세로 채워(ffill) 붙인다. reindex(columns=)라 미수집 코드도 NaN 안전.
    raws = w.reindex(columns=RAW).ffill().reindex(out.index)
    return out.join(raws.add_prefix("raw_"))


def main(markets):
    w = pd.DataFrame(fetch_codes(NEEDED))
    if w.empty:
        print("indicator_raw 에 물가 지표가 없음 — ingest.py 를 먼저 실행하세요.")
        return
    w["dt"] = pd.to_datetime(w["dt"])
    w = w.drop_duplicates(subset=["dt", "code"])  # 페이지 경계 중복 방어
    w = w.pivot(index="dt", columns="code", values="value").sort_index()

    for market in markets:
        out = compute(w, market)
        rows = []
        for d, r in out.iterrows():
            row = {"market": market, "dt": d.strftime("%Y-%m-%d"),
                   "i_score": round(float(r.i_score), 2), "band": r.band,
                   "c_be": round(float(r.c_be), 2), "c_energy": round(float(r.c_energy), 2),
                   "c_food": round(float(r.c_food), 2), "c_metal": round(float(r.c_metal), 2),
                   "c_comm": None}   # c_comm(원자재 DBC)은 식품으로 대체 — 컬럼만 남김
            for c in RAW:                       # 구리는 센트 단위라 소수 4자리까지 살린다
                v = r.get("raw_" + c)
                row["raw_" + c] = None if pd.isna(v) else round(float(v), 4 if c == "copper" else 2)
            rows.append(row)
        for i in range(0, len(rows), 1000):
            sb.table("inflation_daily").upsert(rows[i:i + 1000], on_conflict="market,dt").execute()
        print(f"[{market}] I(t) 적재 완료: {len(rows)}일")
        print(out[["i_score", "band"]].tail(5).round(1).to_string())
        print(f"[{market}] 과거 검증 — 물가 압력이 상식과 맞나")
        for label, day in CHECKS:
            near = out[out.index <= day]
            if len(near):
                v = near.iloc[-1]["i_score"]
                print(f"  {label}: I={v:.0f}  → {band(v)}")
        print()


if __name__ == "__main__":
    markets = [a.upper() for a in sys.argv[1:]] or ["US", "KR"]
    main(markets)
