# allocation.py — 자산배분 국면 지도 + 자산별 위치 점수 → regime_daily · asset_daily
#
# ① 국면(사분면): 성장기대 G(t) × 물가압력 I(t)
#    G(t) = ewm( mean( pct_rank(Δ63 구리/금), pct_rank(Δ126), pct_rank(Δ252) ), span=10 )
#      - 구리=산업 수요, 금=피난처 → 비율이 '오르는 중'이면 시장이 성장 쪽으로 기대를 옮기는 중.
#        수준이 아니라 모멘텀을 쓰는 이유: 자산 가격은 기대의 '변화'에 반응한다.
#      - 성분은 역사 앵커 6건(2017-11 골디락스↑, 2018-12 성장쇼크↓, 2020-03 코로나↓,
#        2021-06 리플레이션↑, 2022-06 스태그공포↓, 2022-10 침체공포↓) 실측 대조로 선정:
#        구리/금+커브(10y-3m) 5/6, 구리/금+커브(10y-2y) 5/6, Δ126 단독 6/6,
#        blend(Δ63·126·252) 6/6 — blend가 창 선택 의존이 없고 전환도 적어(27회, 평균 93일) 채택.
#        커브 기각 근거: 10y-3m은 연준을 늦게 반영(2022-06 G=79 오독), 호황기 평탄화를
#        침체로 오독(2017). ⚠️ 앵커로 골랐다는 것 자체가 in-sample — 웹 해설에 자인한다.
#      - ⚠️ 이건 '시장이 가격에 반영한 성장 기대'지 실물 성장이 아니다 — 괴리 가능. 웹 해설에 명시.
#      - 주가/이동평균 성분은 의도적으로 뺐다: 주가로 국면을 정의하고 그 국면에서 주식 이후수익을
#        재면 순환논법이 된다(설계 심사에서 기각). 신용(HYG) 성분도 주식 동행성이 높아 같은 이유로 제외.
#    I(t) = inflation_daily(US).i_score 의 '스냅샷' — 상류 로직이 바뀌어도 국면 이력이
#      소급해 출렁이지 않게 regime_daily에 박제한다(재현성).
#    사분면 경계 50/50 + 히스테리시스: 축이 50±3 밴드를 완전히 벗어나야 국면 전환.
#      경계 위 잦은 깜빡임(하루 단위 국면 교체)을 막는다. |축-50|<5면 transition(전환주의) 플래그.
#
# ② 자산별 위치 점수: 합성 단일 점수를 만들지 않는다 — 게이지 2개 병렬.
#    c_trend = pct_rank(12-1 모멘텀), c_heat = pct_rank(가격/200일선 - 1)
#    두 지표는 방향이 자주 반대라(추세 강한데 단기 과열 등) 합치면 정보가 상쇄되고
#    '추천 점수'처럼 읽힌다. 자산별 앵커(금=실질금리 등)는 회귀 없이 참고 실수치로만.
#
# 백분위 창은 liquidity.py와 같은 3년(756일) — 자산 사이클도 금리처럼 몇 년짜리라 1년 창은
# 오래된 추세를 중립으로 오독한다. min_periods=252로 초기 이력 보존.
#
# 사용: python allocation.py          → 계산 + Supabase 적재 (크론용)
#       python allocation.py --dry    → 적재 없이 콘솔 요약 + 과거 검증만
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

# 국면 재료 + 자산 + 앵커 재료
NEEDED = ["copper", "gold",                                        # 국면 G(t) = 구리/금 모멘텀
          "us_bond", "kr_bond", "dbc", "usdkrw", "us_index", "kr_index", "btc",  # 자산
          "silver", "gsci", "us_real10y", "kr_10y"]                # 앵커 재료

# 자산 목록 — 카드 순서이기도 하다. (은은 자산이 아니라 금 앵커의 재료)
ASSETS = ["gold", "us_bond", "kr_bond", "dbc", "usdkrw", "us_index", "kr_index", "btc"]
# 선물 계열은 야후 글리치(롤오버 이상 프린트) 방어로 하루 ±20% 초과 수익을 결측 처리.
# BTC는 실제로 ±20%가 나는 자산(2020-03-12 -37%)이라 제외.
GLITCH_FILTER = {"gold", "silver", "copper", "gsci", "dbc"}

WIN, MINP = 756, 252
HYST = 3                          # 히스테리시스 폭: 50±3을 완전히 벗어나야 축 방향 전환
WARN = 5                          # |축-50|<5 → 전환주의(transition)

# 검증용 과거 기준일 — '아는 역사'와 맞나 확인하는 in-sample 상식 검증(웹 해설에도 자인).
# G 성분 선정에 쓴 앵커 6건과 동일 — 크론마다 재확인해 성분 열화(데이터 소스 변경 등)를 잡는다.
CHECKS = [("골디락스 2017-11 (성장기대 개선)", "2017-11-15", lambda g, i: g > 50),
          ("성장쇼크 2018-12 (기대 악화)", "2018-12-15", lambda g, i: g < 50),
          ("코로나 폭락 2020-03 (기대 붕괴)", "2020-03-20", lambda g, i: g < 50),
          ("리플레이션 2021-06 (개선·물가↑)", "2021-06-15", lambda g, i: g > 50 and i > 50),
          ("스태그 공포 2022-06 (악화·물가↑)", "2022-06-15", lambda g, i: g < 50 and i > 50),
          ("침체 공포 2022-10 (기대 악화)", "2022-10-14", lambda g, i: g < 50)]


def fetch_codes(codes):
    """indicator_raw 페이지네이션 조회 — liquidity.py와 동일."""
    rows, step, start = [], 1000, 0
    while True:
        r = sb.table("indicator_raw").select("dt,code,value") \
              .in_("code", codes).order("dt").order("code") \
              .range(start, start + step - 1).execute().data
        rows += r
        if len(r) < step:
            break
        start += step
    return rows


def fetch_iscore():
    """inflation_daily(US)의 i_score — 물가축 스냅샷용."""
    rows, step, start = [], 1000, 0
    while True:
        r = sb.table("inflation_daily").select("dt,i_score").eq("market", "US") \
              .order("dt").range(start, start + step - 1).execute().data
        rows += r
        if len(r) < step:
            break
        start += step
    s = pd.Series({pd.Timestamp(r["dt"]): float(r["i_score"]) for r in rows}).sort_index()
    return s


def pct_rank(s, win=WIN, minp=MINP):
    return s.rolling(win, min_periods=minp).apply(
        lambda x: (x.iloc[-1] > x.iloc[:-1]).mean() * 100, raw=False)


def deglitch(s):
    """하루 ±20% 초과 수익(선물 롤오버 글리치)을 결측 처리 후 직전값으로 메움."""
    r = s.pct_change()
    return s.mask(r.abs() > 0.2).ffill()


def quadrant_walk(g, i):
    """히스테리시스 사분면: 축이 50±HYST를 완전히 벗어나야 방향 전환. 반환: (quadrant, days_in)."""
    quads, days = [], []
    gs = is_ = None                          # 각 축의 현재 방향 ('up'/'dn')
    prev, run = None, 0
    for gv, iv in zip(g, i):
        gs = "up" if gv > 50 + HYST else ("dn" if gv < 50 - HYST else (gs or ("up" if gv >= 50 else "dn")))
        is_ = "up" if iv > 50 + HYST else ("dn" if iv < 50 - HYST else (is_ or ("up" if iv >= 50 else "dn")))
        q = f"g_{gs}_i_{is_}"
        run = run + 1 if q == prev else 1
        prev = q
        quads.append(q)
        days.append(run)
    return quads, days


def compute_regime(w, iscore):
    d = w[["copper", "gold"]].dropna()
    ratio = deglitch(d["copper"]) / deglitch(d["gold"])   # 구리/금 — 성장 베팅의 순도 높은 프록시
    c63, c126, c252 = (pct_rank(ratio - ratio.shift(n)) for n in (63, 126, 252))
    G = pd.concat([c63, c126, c252], axis=1).mean(axis=1).ewm(span=10).mean()
    out = pd.DataFrame({"g_score": G, "c_m63": c63, "c_m126": c126, "c_m252": c252,
                        "raw_coppergold": ratio}).dropna()
    # 물가축: inflation_daily가 없는 날(주말 등)은 직전값 — 스냅샷이므로 재계산하지 않는다
    out["i_score"] = iscore.reindex(out.index, method="ffill")
    out = out.dropna(subset=["i_score"])
    quads, days = quadrant_walk(out["g_score"], out["i_score"])
    out["quadrant"], out["days_in"] = quads, days
    out["transition"] = ((out["g_score"] - 50).abs() < WARN) | ((out["i_score"] - 50).abs() < WARN)
    return out


def compute_assets(w):
    """자산별 c_trend/c_heat + raw + 앵커. 각 자산은 자기 거래일 달력으로 계산(BTC는 365일)."""
    real = w.get("us_real10y")
    frames = {}
    for a in ASSETS:
        px = w[a].dropna()
        if a in GLITCH_FILTER:
            px = deglitch(px)
        mom = px.shift(21) / px.shift(252) - 1          # 12-1 모멘텀(최근 1달 제외 — 반전 노이즈 컷)
        heat = px / px.rolling(200, min_periods=120).mean() - 1
        out = pd.DataFrame({
            "c_trend": pct_rank(mom), "c_heat": pct_rank(heat), "raw_px": px,
            "raw_dd252": (px / px.rolling(252, min_periods=120).max() - 1) * 100,
            "raw_r12m": (px / px.shift(252) - 1) * 100,
        })
        # 앵커 — 자산마다 의미가 다른 참고 실수치 (sql/asset_daily.sql 주석과 웹 ASSET_META가 정의)
        if a == "gold" and real is not None:
            rl = real.dropna().reindex(px.index, method="ffill")
            out["anchor_a"] = rl                                      # 실질금리 수준(%)
            out["anchor_b"] = (rl - rl.shift(63)) * 100               # 63일 변화(bp)
            if "silver" in w.columns:
                gs = px / deglitch(w["silver"].dropna()).reindex(px.index, method="ffill")
                out["anchor_c"] = pct_rank(gs)                        # 금/은 비율 백분위
            if "gsci" in w.columns:
                gc = px / deglitch(w["gsci"].dropna()).reindex(px.index, method="ffill")
                out["anchor_d"] = pct_rank(gc)                        # 금/원자재 백분위
        elif a == "us_bond" and real is not None:
            rl = real.dropna().reindex(px.index, method="ffill")
            out["anchor_a"] = rl                                      # 실질금리 수준(%)
            out["anchor_b"] = rl.expanding(min_periods=252).apply(     # 전이력 백분위
                lambda x: (x.iloc[-1] > x.iloc[:-1]).mean() * 100, raw=False)
        elif a == "kr_bond" and "kr_10y" in w.columns:
            ky = w["kr_10y"].dropna().reindex(px.index, method="ffill")
            out["anchor_a"] = ky                                      # 국고채10년 금리(%)
            out["anchor_b"] = ky.expanding(min_periods=252).apply(
                lambda x: (x.iloc[-1] > x.iloc[:-1]).mean() * 100, raw=False)
        elif a == "usdkrw":
            out["anchor_a"] = pct_rank(px, win=1260)                  # 원/달러 5년 백분위
        frames[a] = out.dropna(subset=["raw_px"])
    return frames


def main():
    dry = "--dry" in sys.argv
    w = pd.DataFrame(fetch_codes(NEEDED))
    if w.empty:
        print("indicator_raw 에 재료가 없음 — ingest.py 를 먼저 실행하세요.")
        return
    w["dt"] = pd.to_datetime(w["dt"])
    w = w.drop_duplicates(subset=["dt", "code"])
    w = w.pivot(index="dt", columns="code", values="value").sort_index()

    # ── 국면 ──
    iscore = fetch_iscore()
    if iscore.empty:
        print("inflation_daily(US) 없음 — 물가축을 만들 수 없어 중단. inflation.py 먼저.")
        return
    rg = compute_regime(w, iscore)
    last = rg.iloc[-1]
    print(f"국면: {last['quadrant']} (G={last['g_score']:.0f}, I={last['i_score']:.0f}, "
          f"지속 {int(last['days_in'])}일{', 전환주의' if last['transition'] else ''}) — {rg.index[-1].date()}")
    print("과거 검증 — 국면이 아는 역사와 맞나 (in-sample 상식 확인)")
    ok = 0
    for label, day, cond in CHECKS:
        near = rg[rg.index <= day]
        if len(near):
            g, i = near.iloc[-1]["g_score"], near.iloc[-1]["i_score"]
            hit = cond(g, i)
            ok += hit
            print(f"  {label}: G={g:.0f} I={i:.0f} → {'✅' if hit else '❌'}")
    if ok < len(CHECKS) - 1:                            # 6건 중 5건 미만이면 뭔가 무너진 것
        print("⚠️ 상식 검증 실패(5/6 미만) — 적재를 중단합니다. 성분·데이터 소스를 점검하세요.")
        return

    # ── 자산 ──
    frames = compute_assets(w)
    for a, f in frames.items():
        r = f.iloc[-1]
        t = f"추세 {r['c_trend']:.0f} 과열 {r['c_heat']:.0f}" if pd.notna(r["c_trend"]) else "창 부족"
        print(f"  {a:<9} {t} · 가격 {r['raw_px']:,.2f} · 52주고점 대비 {r['raw_dd252']:+.1f}%")

    if dry:
        print("\n--dry: 적재 생략")
        return

    def rnd(v, n=2):
        return None if pd.isna(v) else round(float(v), n)

    rows = [{"market": "GL", "dt": d.strftime("%Y-%m-%d"),
             "g_score": rnd(r.g_score), "i_score": rnd(r.i_score),
             "quadrant": r.quadrant, "days_in": int(r.days_in), "transition": bool(r.transition),
             "c_m63": rnd(r.c_m63), "c_m126": rnd(r.c_m126), "c_m252": rnd(r.c_m252),
             "raw_coppergold": rnd(r.raw_coppergold, 5)}
            for d, r in rg.iterrows()]
    for i in range(0, len(rows), 1000):
        sb.table("regime_daily").upsert(rows[i:i + 1000], on_conflict="market,dt").execute()
    print(f"regime_daily 적재: {len(rows)}일")

    arows = []
    for a, f in frames.items():
        for d, r in f.iterrows():
            arows.append({"asset": a, "dt": d.strftime("%Y-%m-%d"),
                          "c_trend": rnd(r.get("c_trend")), "c_heat": rnd(r.get("c_heat")),
                          "raw_px": rnd(r.raw_px, 4), "raw_dd252": rnd(r.get("raw_dd252")),
                          "raw_r12m": rnd(r.get("raw_r12m")),
                          "anchor_a": rnd(r.get("anchor_a")), "anchor_b": rnd(r.get("anchor_b")),
                          "anchor_c": rnd(r.get("anchor_c")), "anchor_d": rnd(r.get("anchor_d"))})
    for i in range(0, len(arows), 1000):
        sb.table("asset_daily").upsert(arows[i:i + 1000], on_conflict="asset,dt").execute()
    print(f"asset_daily 적재: {len(arows)}행 ({len(frames)}자산)")


if __name__ == "__main__":
    main()
