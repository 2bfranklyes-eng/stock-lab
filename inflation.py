# inflation.py — indicator_raw 읽어 물가지수 I(t) 계산 → inflation_daily (미국 + 한국)
# 4성분(정규화 후 평균, 높을수록 '물가 압력↑'). CPI는 월간·후행이라, 시장이 매일 반영하는
# '물가 압력'을 유동성과 똑같은 방식(시장 데이터·퍼센타일)으로 잰다. FRED 키 불필요.
#   기대인플레(물가연동채 TIP / 국채 IEF) + 유가(USO) + 원자재(DBC) + 산업금속(DBB)
#   물가는 글로벌 지표(유가·원자재)가 한국에도 작용 → 코드 단위로 조회.
#   한국은 기대인플레 대신 usdkrw(원 약세 = 수입물가↑)를 쓴다.
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

NEEDED = ["tip", "ief", "uso", "dbc", "dbb", "usdkrw"]

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
    if market == "US":
        d = w[["tip", "ief", "uso", "dbc", "dbb"]].dropna()
        c_be = pct_rank(d["tip"] / d["ief"])          # 물가연동채/국채↑ = 기대인플레↑
    else:  # KR
        d = w[["usdkrw", "uso", "dbc", "dbb"]].dropna()
        c_be = pct_rank(d["usdkrw"])                  # 원 약세(원/달러↑) = 수입물가↑
    c_energy = pct_rank(d["uso"])                     # 유가↑ = 물가↑
    c_comm = pct_rank(d["dbc"])                       # 원자재↑ = 물가↑
    c_metal = pct_rank(d["dbb"])                      # 산업금속↑ = 실물수요·물가↑

    I = pd.concat([c_be, c_energy, c_comm, c_metal], axis=1).mean(axis=1).ewm(span=10).mean()
    out = pd.DataFrame({"i_score": I, "c_be": c_be, "c_energy": c_energy,
                        "c_comm": c_comm, "c_metal": c_metal}).dropna()
    out["band"] = out["i_score"].map(band)
    return out


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
        rows = [{"market": market, "dt": d.strftime("%Y-%m-%d"),
                 "i_score": round(float(r.i_score), 2), "band": r.band,
                 "c_be": round(float(r.c_be), 2), "c_energy": round(float(r.c_energy), 2),
                 "c_comm": round(float(r.c_comm), 2), "c_metal": round(float(r.c_metal), 2)}
                for d, r in out.iterrows()]
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
