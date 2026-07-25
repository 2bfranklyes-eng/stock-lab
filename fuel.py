# fuel.py — 증시 실탄(자금유입) 지수 F(t) → fuel_index (미국 주간 / 한국 월간)
# "실제 주식에 투입될 수 있는 돈"을 잰다. 유동성 L(t)가 '돈의 값'이면 이건 '돈의 양·유입'.
#   US(주간, FRED): Fed 순유동성 = 연준자산(WALCL) − 재무부계정(TGA) − 역레포(RRP).
#   KR(월간, ECOS): M2 증가율 + 외국인 순매수. 2성분.
#   ⚠️ 한국은 일간 예탁금(KOFIA)·외국인(KRX) 접근이 막혀 월간 ECOS로 대체 — 웹에 '월간' 표시.
#
# 한국에서 '개인 순매수'를 뺀 이유: 외국인과 개인은 서로의 거래상대라 상관 -0.64로 거울상이다.
#   둘을 평균내면 변동폭의 56%가 상쇄돼 사라진다(표준편차 29.3 → 12.8).
#   실제로 이후60일 상관이 개인 포함 -0.05 → 제외 +0.11 로 뒤집힌다. 신호를 지우고 있었다.
#
# c1~c3 단위: 양 시장 모두 0~100 백분위로 통일한다. 미국의 절대금액($조)은 raw1~raw4로 보낸다.
#   (예전엔 미국만 c1~c3에 절대 $조를 담아, 같은 컬럼이 시장마다 다른 뜻이었다.)
# 자기완결형: indicator_raw 안 거치고 FRED·ECOS를 직접 호출해 fuel_index에 적재.
import os
import sys
import json
import urllib.request
from dotenv import load_dotenv
import pandas as pd
from supabase import create_client

try:  # 윈도우 콘솔(cp949)에서도 한글·기호 출력이 깨지지 않게
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

load_dotenv()
sb = create_client(os.environ["SUPABASE_URL"], os.environ["SUPABASE_SERVICE_KEY"])
FRED_KEY = os.environ.get("FRED_API_KEY", "").strip()
ECOS_KEY = os.environ.get("ECOS_API_KEY", "").strip()

BANDS = [(20, "고갈"), (40, "부족"), (60, "중립"), (80, "여유"), (999, "풍부")]


def band(v):
    if pd.isna(v):
        return None
    for hi, nm in BANDS:
        if v < hi:
            return nm
    return "풍부"


def pct_rank(s, win):
    return s.rolling(win).apply(lambda x: (x.iloc[-1] > x.iloc[:-1]).mean() * 100, raw=False)


# ── 미국: FRED 순유동성(주간) ──
def fred(sid, start="2015-01-01"):
    url = (f"https://api.stlouisfed.org/fred/series/observations?series_id={sid}"
           f"&api_key={FRED_KEY}&file_type=json&observation_start={start}")
    d = json.loads(urllib.request.urlopen(url, timeout=30).read().decode("utf-8"))
    s = {o["date"]: float(o["value"]) for o in d.get("observations", []) if o["value"] not in (".", "")}
    return pd.Series({pd.Timestamp(k): v for k, v in s.items()}).sort_index()


def compute_us():
    if not FRED_KEY:
        print("[US] FRED_API_KEY 없음 — 미국 실탄 건너뜀")
        return None
    walcl = fred("WALCL")                       # 연준 총자산(주간, 백만$)
    tga = fred("WTREGEN")                        # 재무부 일반계정(주간)
    rrp = fred("RRPONTSYD") * 1000               # 역레포(일간, 십억$)→백만$
    idx = walcl.index
    d = pd.DataFrame({"walcl": walcl,
                      "tga": tga.reindex(idx, method="ffill"),
                      "rrp": rrp.reindex(idx, method="ffill")}).dropna()
    netliq = d["walcl"] - d["tga"] - d["rrp"]    # 절대 순유동성($M) — 실제 달러로 뺀 값(올바른 가중)
    # ⚠️ 성분을 백분위로 등가중 평균하면 달러규모(연준$6.7T vs TGA$0.8T) 차이를 무시해 왜곡.
    #    → 종합은 '순유동성 절대값의 백분위'로만 낸다. c1~c3는 표시용 백분위(계산에 안 씀).
    F = pct_rank(netliq, 104).ewm(span=4).mean()  # 종합 = 순유동성($) 백분위 (게이지·밴드용)
    out = pd.DataFrame({"f_score": F,
                        # 성분 백분위(표시용) — 재무부계정·역레포는 늘면 유동성을 빨아들이므로 뒤집는다
                        "c1": pct_rank(d["walcl"], 104),
                        "c2": 100 - pct_rank(d["tga"], 104),
                        "c3": 100 - pct_rank(d["rrp"], 104),
                        "raw1": netliq / 1e6,                    # 순유동성($조)
                        "raw2": d["rrp"] / 1000,                 # 역레포($십억, 헤드라인용)
                        "raw3": d["walcl"] / 1e6,                # 연준자산($조)
                        "raw4": d["tga"] / 1e6}).dropna()        # 재무부계정($조)
    return out


# ── 한국: ECOS 월간(M2·수급) ──
def ecos_m(stat, item, start="200401"):
    end = pd.Timestamp.today().strftime("%Y%m")
    url = (f"https://ecos.bok.or.kr/api/StatisticSearch/{ECOS_KEY}/json/kr/1/1000/"
           f"{stat}/M/{start}/{end}/{item}")
    d = json.loads(urllib.request.urlopen(url, timeout=30).read().decode("utf-8"))
    s = {}
    for r in d.get("StatisticSearch", {}).get("row", []):
        v, t = r.get("DATA_VALUE", "").strip(), r.get("TIME", "")
        if v not in ("", "-") and len(t) == 6:
            try:
                s[pd.Timestamp(f"{t[:4]}-{t[4:6]}-01")] = float(v)
            except ValueError:
                pass
    return pd.Series(s).sort_index()


def compute_kr():
    if not ECOS_KEY:
        print("[KR] ECOS_API_KEY 없음 — 한국 실탄 건너뜀")
        return None
    m2 = ecos_m("161Y008", "BBGA00")             # M2 말잔
    foreign = ecos_m("901Y055", "S22CC")         # 외국인 순매수(월)
    d = pd.DataFrame({"m2": m2, "foreign": foreign}).dropna()
    m2_yoy = d["m2"].pct_change(12) * 100
    c1 = pct_rank(m2_yoy, 60)                     # M2 증가율↑ = 돈 풀림
    c2 = pct_rank(d["foreign"], 60)              # 외국인 순매수↑ = 유입
    # 개인 순매수(c3)는 외국인과 상관 -0.64인 거울상이라 평균에서 서로 지운다 → 제외(위 주석 참고)
    F = pd.concat([c1, c2], axis=1).mean(axis=1).ewm(span=3).mean()
    out = pd.DataFrame({"f_score": F, "c1": c1, "c2": c2,
                        "raw1": m2_yoy,                          # M2 YoY(%)
                        "raw2": d["foreign"]}).dropna()          # 외국인 순매수(월)
    out["c3"] = None
    out["raw3"] = None
    out["raw4"] = None
    return out


def save(market, out, freq):
    out = out.copy()
    out["band"] = out["f_score"].map(band)

    def rnd(v, n):
        return None if pd.isna(v) else round(float(v), n)
    rows = [{"market": market, "dt": d.strftime("%Y-%m-%d"),
             "f_score": round(float(r.f_score), 2), "band": r.band,
             "c1": rnd(r.c1, 2), "c2": rnd(r.c2, 2), "c3": rnd(r.c3, 2),
             "raw1": rnd(r.raw1, 2), "raw2": rnd(r.raw2, 2),
             "raw3": rnd(r.raw3, 2), "raw4": rnd(r.raw4, 2), "freq": freq}
            for d, r in out.iterrows()]
    # delete→insert: 재실행/빈도변경에도 깔끔히 교체
    sb.table("fuel_index").delete().eq("market", market).execute()
    for i in range(0, len(rows), 1000):
        sb.table("fuel_index").insert(rows[i:i + 1000]).execute()
    print(f"[{market}] fuel_index 적재 완료: {len(rows)}행 ({freq})")
    print(out[["f_score", "band"]].tail(4).round(1).to_string())


def main(markets):
    if "US" in markets:
        out = compute_us()
        if out is not None:
            save("US", out, "W")
    if "KR" in markets:
        out = compute_kr()
        if out is not None:
            save("KR", out, "M")


if __name__ == "__main__":
    markets = [a.upper() for a in sys.argv[1:]] or ["US", "KR"]
    main(markets)
