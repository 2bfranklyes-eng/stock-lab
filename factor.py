# factor.py — 횡단면 팩터 백테스트 (로컬 전용, Supabase 적재 없음)
#
# 왜 만드나 — 이 프로젝트가 지금까지 검증한 건 전부 '시계열'(언제 사야 하나)이고, 거기서
# 계속 발목을 잡은 게 사건 수였다. 상관 -0.39가 겹침 착시로 무너지고, 초과 +45%가 기간을
# 나누면 사라지고… 국면 하나를 세면 4~60건이라 무엇도 우연과 구별하기 어려웠다.
# 횡단면(어떤 종목이 다른 종목보다 나은가)으로 가면 문제의 성격이 바뀐다. 매달 수백 종목을
# 동시에 관측하므로 월별 롱숏 수익률 하나가 이미 수백 종목의 평균이다. 게다가 롱숏은
# 시장 중립이라 '코스피가 오를까'를 안 맞혀도 된다.
#
# ⚠️ 이 스크립트의 존재 이유의 절반은 '거래비용'이다. 지금까지 낸 모든 통계에 비용이 하나도
#    안 들어갔다. 한국 주식 왕복 0.3%(거래세 0.18% + 수수료·슬리피지)를 월별 리밸런싱에
#    물리면 연 5~7%가 깎여, 우리가 봐 온 '초과 +3%p' 같은 건 그냥 사라진다.
#    그래서 모든 결과를 비용 전/후로 나란히 찍는다. 안 그러면 자기기만이다.
#
# 🚨 이 백테스트의 가장 큰 한계 — 유니버스가 point-in-time이 아니다.
#   vp_stocks는 매일 '현재 시총' 기준으로 재구성되고 stock_daily는 그 유니버스만 보관한다
#   (상위 200종목 5년 · 나머지 2년). 그래서 과거 어느 시점을 봐도 '오늘 살아남은 종목'만
#   들어 있고, 그 사이 상장폐지·시총 급감으로 빠진 종목은 흔적도 없다.
#   실측한 편향의 크기:
#     · 5년 내내 존재한 175종목의 5년 수익률 중앙값 +87% (평균 +233%)
#     · 그중 5년 전 시총 하위였던 88종목은 +137%, 당시 상위였던 종목은 +19%
#   → '소형주 팩터 +74%/년'은 팩터가 아니라 이 편향이다. 5년 전 작았는데 지금까지 상위
#     200에 남으려면 그 사이 크게 올랐어야 하니까. 유니버스가 넓어지는 2024-08 이후
#     구간에서는 실제로 -5%로 사라진다.
#   그래서 기본 판단은 BROAD_FROM 이후(유니버스가 거의 전체인 구간)로만 한다. 그 구간도
#   '오늘 기준 선택'인 건 같지만, 표본이 173종목에서 1,600종목대로 늘어 편향이 훨씬 작다.
#   제대로 고치려면 매 시점의 실제 상장종목 전체(상장폐지 포함)를 따로 쌓아야 한다.
#
# 못 하는 것: 밸류(PBR/PER) 팩터. stock_meta는 500종목의 '현재 스냅샷' 하나뿐이라
#   과거 시점의 PBR을 모른다. 재무 시계열을 쌓기 전엔 검증 자체가 불가능하다.
#
# 사용: python factor.py            (캐시 사용, 없으면 받아서 저장)
#       python factor.py --refresh  (Supabase에서 다시 받기, 약 5분)
import os
import sys
import pickle
import time
import numpy as np
import pandas as pd
from dotenv import load_dotenv
from supabase import create_client

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

load_dotenv()
sb = create_client(os.environ["SUPABASE_URL"], os.environ["SUPABASE_SERVICE_KEY"])
CACHE = "factor_cache.pkl"          # .gitignore 대상 — 94만 행이라 매번 받으면 5분씩 든다

# ── 거래 가능성 필터 ──
# 소형·저유동 종목을 빼는 이유: 백테스트에서 초과수익 대부분이 '실제로는 못 사는 종목'에서
# 나오는 게 이 바닥의 고전적 함정이다. 호가 몇 개로 가격이 밀리는 종목은 통계에 넣으면 안 된다.
MIN_TVAL = 5e8                      # 월평균 일거래대금 5억원
MIN_CAP = 5e10                      # 시총 500억원
COST_RT = 0.003                     # 왕복 거래비용 0.3% (거래세 0.18% + 수수료·슬리피지)
NQ = 10                             # 10분위


def fetch_panel():
    rows, off, t0 = [], 0, time.time()
    while True:
        d = (sb.table("stock_daily").select("code,dt,close,tval,mktcap,shares")
             .order("code").order("dt").range(off, off + 999).execute().data)
        rows += d
        off += 1000
        if len(rows) % 100000 < 1000:
            print(f"  {len(rows):,}행 ({time.time()-t0:.0f}초)", flush=True)
        if len(d) < 1000:
            break
    df = pd.DataFrame(rows)
    df["dt"] = pd.to_datetime(df["dt"])
    return df


def load_panel(refresh=False):
    if not refresh and os.path.exists(CACHE):
        with open(CACHE, "rb") as f:
            df = pickle.load(f)
        print(f"캐시 사용: {len(df):,}행  {df.dt.min().date()} ~ {df.dt.max().date()}")
        return df
    print("Supabase에서 stock_daily 적재 중… (약 5분)")
    df = fetch_panel()
    with open(CACHE, "wb") as f:
        pickle.dump(df, f)
    print(f"적재 완료: {len(df):,}행 → {CACHE} 저장")
    return df


def split_adjust(df):
    """액면분할·병합·인적분할 보정. stock_daily는 수정주가가 아니라, 그대로 수익률을 내면
    분할일에 -50% 같은 값이 찍혀 모멘텀·반전 팩터가 통째로 오염된다.
    판정 규칙은 profile.py의 split_adjust와 동일하게 맞춘다 — 상장주식수가 급변한 날
    주가가 그 역수만큼 움직였으면(=시총 연속) 분할류로 보고 이전 구간 가격에 배율을 적용.
    유상증자는 시총이 함께 늘어 주가가 안 꺾이므로 걸리지 않는다."""
    out = []
    for code, g in df.groupby("code", sort=False):
        g = g.sort_values("dt")
        sh, px = g["shares"].to_numpy(), g["close"].to_numpy()
        f = np.ones(len(g))
        for i in range(1, len(g)):
            if not (sh[i - 1] > 0 and sh[i] > 0 and px[i - 1] > 0):
                continue
            r = sh[i] / sh[i - 1]
            if (r > 1.5 or r < 0.67) and abs(px[i] / px[i - 1] * r - 1) < 0.25:
                f[:i] /= r
        g = g.copy()
        g["close"] = g["close"] * f
        out.append(g)
    return pd.concat(out, ignore_index=True)


def build_monthly(df):
    """일별 → 월별 패널. 팩터 재료를 월말 시점 기준으로 만든다(룩어헤드 방지)."""
    df = df.dropna(subset=["close"]).sort_values(["code", "dt"])
    df = split_adjust(df)
    df["ret"] = df.groupby("code")["close"].pct_change()
    # 분할 보정 후에도 남는 극단값(거래정지 후 재개, 데이터 오류)은 잘라낸다 —
    # 한 종목의 +500% 한 달이 분위 평균을 통째로 흔든다.
    df.loc[df["ret"].abs() > 0.5, "ret"] = np.nan
    df["ym"] = df["dt"].dt.to_period("M")
    g = df.groupby(["code", "ym"])
    m = g.agg(close=("close", "last"), mktcap=("mktcap", "last"),
              tval=("tval", "mean"), vol=("ret", "std"), n=("close", "size")).reset_index()
    m = m[m["n"] >= 10]                          # 거래일이 너무 적은 달은 제외(상장·거래정지)
    m = m.sort_values(["code", "ym"])
    # 다음 달 수익률 — 팩터는 t월말, 성과는 t→t+1. 이 한 칸이 룩어헤드의 전부다.
    m["fwd"] = m.groupby("code")["close"].shift(-1) / m["close"] - 1
    # 연속된 달인지 확인(중간에 빠진 달이 있으면 fwd가 두 달치가 된다)
    nxt = m.groupby("code")["ym"].shift(-1)
    m.loc[nxt != m["ym"] + 1, "fwd"] = np.nan
    return m


def make_factors(m):
    """월말 t 시점에 '그때 알 수 있는 정보'만으로 팩터를 만든다."""
    m = m.sort_values(["code", "ym"]).copy()
    g = m.groupby("code")["close"]
    # 모멘텀 12-1: 최근 1개월을 건너뛴다 — 단기반전과 섞이면 두 효과가 서로 지운다(표준 정의)
    m["MOM"] = g.shift(1) / g.shift(12) - 1
    m["REV"] = -(m["close"] / g.shift(1) - 1)    # 단기반전: 많이 떨어진 쪽이 유리 → 부호 뒤집기
    m["LOWVOL"] = -m["vol"]                       # 저변동성 이상현상 → 변동성 낮을수록 높은 점수
    m["SMALL"] = -np.log(m["mktcap"].where(m["mktcap"] > 0))
    # Amihud 비유동성: 가격 충격 대비 거래대금. 유동성이 낮을수록 프리미엄이 있다는 가설
    m["ILLIQ"] = m["vol"] / (m["tval"] / 1e8)
    return m


def fixed_universe(m):
    """전 기간 내내 존재한 종목만. 왜 필요한가 — stock_daily는 상위 200종목만 5년,
    나머지는 2년치를 보관한다(krx.py의 DEEP_N/SHALLOW_DAYS 티어). 그래서 그냥 돌리면
    2024년 이전은 대형주 177종목, 이후는 900종목대가 되어 '전반 vs 후반'이 사실은
    '대형주 vs 전체'가 된다. 기간분할로 안정성을 보려면 유니버스가 고정돼야 한다."""
    span = m.groupby("code")["ym"].agg(["min", "max"])
    lo, hi = m["ym"].min(), m["ym"].max()
    return set(span[(span["min"] <= lo + 1) & (span["max"] >= hi - 1)].index)


def decile_test(m, factor, label, universe=None):
    """10분위 롱숏. 상위-하위 스프레드를 월별로 이어붙여 성과를 낸다."""
    d = m.dropna(subset=[factor, "fwd", "mktcap", "tval"])
    if universe is not None:
        d = d[d["code"].isin(universe)]
    d = d[(d["tval"] >= MIN_TVAL) & (d["mktcap"] >= MIN_CAP)]
    out, prev_top, prev_bot = [], set(), set()
    for ym, grp in d.groupby("ym"):
        if len(grp) < NQ * 5:                    # 분위당 최소 5종목은 되어야 평균이 의미 있다
            continue
        q = pd.qcut(grp[factor].rank(method="first"), NQ, labels=False)
        top, bot = grp[q == NQ - 1], grp[q == 0]
        tset, bset = set(top["code"]), set(bot["code"])
        # 회전율 = 이번 달 새로 들어온 비율. 비용은 여기에 비례한다.
        turn = ((len(tset - prev_top) / len(tset) if prev_top else 1.0)
                + (len(bset - prev_bot) / len(bset) if prev_bot else 1.0))
        prev_top, prev_bot = tset, bset
        out.append({"ym": ym, "n": len(grp), "long": top["fwd"].mean(),
                    "short": bot["fwd"].mean(), "mkt": grp["fwd"].mean(), "turn": turn})
    r = pd.DataFrame(out)
    if len(r) < 12:
        print(f"  {label:14} 표본 부족({len(r)}개월)")
        return None
    r["ls"] = r["long"] - r["short"]
    r["ls_net"] = r["ls"] - r["turn"] * COST_RT          # 롱·숏 두 다리 각각에 비용
    r["lo"] = r["long"] - r["mkt"]                        # 롱온리 초과(시장=동일가중 평균)
    r["lo_net"] = r["lo"] - (r["turn"] / 2) * COST_RT     # 롱만 굴리면 다리 하나
    return r


def summ(r, col):
    x = r[col].dropna()
    if len(x) < 12:
        return None
    ann = (1 + x).prod() ** (12 / len(x)) - 1
    vol = x.std() * np.sqrt(12)
    cum = (1 + x).cumprod()
    mdd = (cum / cum.cummax() - 1).min()
    return {"ann": ann * 100, "vol": vol * 100, "sharpe": ann / vol if vol else 0,
            "win": (x > 0).mean() * 100, "mdd": mdd * 100, "n": len(x)}


def report(r, label):
    print(f"\n  ── {label} ──   {r.ym.min()} ~ {r.ym.max()} · {len(r)}개월 · "
          f"평균 유니버스 {r.n.mean():.0f}종목 · 월 회전율 {r.turn.mean()/2*100:.0f}%")
    print(f"    {'':22}{'연율':>9}{'변동성':>9}{'샤프':>7}{'월승률':>8}{'MDD':>9}")
    for col, nm in (("ls", "롱숏 (비용 전)"), ("ls_net", "롱숏 (비용 후)"),
                    ("lo", "롱온리 초과 (전)"), ("lo_net", "롱온리 초과 (후)")):
        s = summ(r, col)
        if s:
            print(f"    {nm:22}{s['ann']:>+8.2f}%{s['vol']:>8.1f}%{s['sharpe']:>7.2f}"
                  f"{s['win']:>7.0f}%{s['mdd']:>8.1f}%")


if __name__ == "__main__":
    df = load_panel("--refresh" in sys.argv)
    m = make_factors(build_monthly(df))
    print(f"\n월별 패널: {len(m):,}행 · {m.code.nunique():,}종목 · "
          f"{m.ym.min()} ~ {m.ym.max()}")
    print(f"필터: 월평균 거래대금 ≥{MIN_TVAL/1e8:.0f}억 · 시총 ≥{MIN_CAP/1e8:.0f}억 · "
          f"왕복비용 {COST_RT*100:.1f}%")

    FACTORS = [("MOM", "모멘텀 12-1"), ("REV", "단기반전 1M"), ("LOWVOL", "저변동성"),
               ("SMALL", "소형주"), ("ILLIQ", "비유동성")]
    # 유니버스가 '거의 전체'가 되는 첫 달 — 그 전은 오늘의 상위 200만 있어 편향이 지배한다
    cnt = m.groupby("ym")["code"].nunique()
    broad = cnt[cnt > cnt.max() * 0.7]
    BROAD_FROM = broad.index.min() if len(broad) else None
    print(f"월별 종목수: {cnt.iloc[0]}종목({cnt.index[0]}) → {cnt.iloc[-1]}종목({cnt.index[-1]})")
    print(f"⚠️ 유니버스가 넓어지는 시점: {BROAD_FROM} — 그 전 구간은 생존 편향이 지배한다")

    fixed = fixed_universe(m)
    mb = m[m["ym"] >= BROAD_FROM] if BROAD_FROM is not None else m
    print(f"\n{'#'*82}\n### ★ 신뢰 구간: {BROAD_FROM} 이후 (유니버스 거의 전체) ★\n{'#'*82}")
    print(f"  {'팩터':14}{'롱숏(비용후)':>14}{'롱온리 초과':>13}{'월승률':>9}{'개월':>7}")
    for f, label in FACTORS:
        r = decile_test(mb, f, label)
        if r is None:
            continue
        s, lo = summ(r, "ls_net"), summ(r, "lo_net")
        print(f"  {label:14}{s['ann']:>+13.2f}%{lo['ann']:>+12.2f}%{s['win']:>8.0f}%{s['n']:>7}")
    print("  ↑ 이 표만 참고하세요. 아래 두 표는 편향이 얼마나 큰지 보여주는 대조군입니다.")

    for uni, uname in ((None, "커지는 유니버스 — 참고용"),
                       (fixed, "고정 유니버스 — 생존 편향 시연용")):
        results = {}
        print(f"\n\n{'#'*82}\n### {uname}\n{'#'*82}")
        for f, label in FACTORS:
            r = decile_test(m, f, label, uni)
            if r is None:
                continue
            results[f] = r
            print(f"\n{'='*82}\n{label} · {uname}\n{'='*82}")
            report(r, "전체")
            half = r.ym.min() + (len(r) // 2)
            early, late = r[r.ym <= half], r[r.ym > half]
            if len(early) >= 12 and len(late) >= 12:
                report(early, "전반")
                report(late, "후반")

        if results:
            print(f"\n{'='*82}\n요약 [{uname}] — 비용 후 연율\n{'='*82}")
            print(f"  {'팩터':14}{'롱숏 전체':>11}{'전반':>10}{'후반':>10}{'부호':>9}"
                  f"{'롱온리 초과':>13}")
            for f, label in FACTORS:
                if f not in results:
                    continue
                r = results[f]
                half = r.ym.min() + (len(r) // 2)
                a, b = summ(r[r.ym <= half], "ls_net"), summ(r[r.ym > half], "ls_net")
                s, lo = summ(r, "ls_net"), summ(r, "lo_net")
                ok = "○" if a and b and (a["ann"] > 0) == (b["ann"] > 0) else "✗"
                print(f"  {label:14}{s['ann']:>+10.2f}%{a['ann']:>+9.2f}%{b['ann']:>+9.2f}%"
                      f"{ok:>7}{lo['ann']:>+12.2f}%")
