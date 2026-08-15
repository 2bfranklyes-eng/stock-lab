# sentiment_voltest.py — KR 공포 성분(c_vix)의 추정량을 바꿔보고 ①②기준으로 판정한다.
#
# 지금: sentiment.py 는 20일 '종가대종가' 표준편차를 쓴다(VKOSPI를 못 받아 실현변동성으로 대체).
# 후보: volatility.py 에서 Rogers-Satchell 이 CC보다 정확한 추정량으로 확인됐다
#       (이후 20일 실현분산 R² 0.430 → 0.477). 그 개선이 S(t) 품질까지 올리는지가 질문.
#
# ⚠️ OHLC 조달: indicator_raw 엔 종가뿐이고 stock_daily 의 OHLC는 2021-08부터라,
#    그대로 쓰면 KR 심리가 10년→5년으로 잘리고 ①체크포인트가 전부 범위 밖이 된다.
#    그래서 FinanceDataReader로 코스피 OHLC를 로컬에서만 받는다 — DB 적재 없음(용량 영향 0).
#    2026-08-12·13 값이 stock_daily(KRX 원본)와 소수점까지 일치함을 확인하고 쓴다.
#
# ⚠️ 판정은 sentiment.py 상단이 정한 두 기준으로만 한다. 동시점 상관은 보지 않는다 —
#    빠르고 시끄러운 성분을 유리하게 만들어 실제로 되돌린 전례가 있다.
import sys
import numpy as np
import pandas as pd
import FinanceDataReader as fdr
import sentiment as S               # fetch_raw / pct_rank / band / MARKETS 재사용

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

START = "2015-01-01"                # 2016-07 시작인 sentiment_daily 보다 앞서 창을 데운다
FWD = 20                            # 역발상 관측 지평(거래일) ≈ 1달


def kospi_ohlc():
    d = fdr.DataReader("KS11", START)[["Open", "High", "Low", "Close"]]
    d.columns = ["open", "high", "low", "close"]
    return d.astype(float)


def vol_variants(px):
    """20일 변동성 3종. 전부 '표준편차 스케일'로 맞춰 c_vix 계산이 동일하게 돌게 한다."""
    o, h, l, c = (np.log(px[k]) for k in ("open", "high", "low", "close"))
    prev_c = c.shift(1)

    cc = (c - prev_c).rolling(20).std()                                  # 현행
    rs_d = (h - c) * (h - o) + (l - c) * (l - o)                         # Rogers-Satchell 일별 분산
    rs = np.sqrt(rs_d.rolling(20).mean())

    ovn, oc = o - prev_c, c - o                                          # Yang-Zhang: 갭까지 포함
    k = 0.34 / (1.34 + 21 / 19)
    yz = np.sqrt(ovn.rolling(20).var() + k * oc.rolling(20).var()
                 + (1 - k) * rs_d.rolling(20).mean())
    return {"CC(현행)": cc, "RS": rs, "YZ": yz}


def build(vol):
    """sentiment.py 의 KR 계산을 그대로 재현하되 공포 성분만 주어진 vol 로 바꾼다."""
    cfg = S.MARKETS["KR"]
    df = pd.DataFrame(S.fetch_raw("KR"))
    df["dt"] = pd.to_datetime(df["dt"])
    w = df.pivot(index="dt", columns="code", values="value").sort_index()
    need = [cfg["index"], cfg["bond"], cfg["ew"], cfg["cw"]]
    w = w[list(dict.fromkeys(need))].dropna()

    idx = w[cfg["index"]]
    mom = idx / idx.rolling(125).mean() - 1
    shv = idx.pct_change(20) - w[cfg["bond"]].pct_change(20)
    brd = w[cfg["ew"]].pct_change(20) - w[cfg["cw"]].pct_change(20)

    c_vix = 100 - S.pct_rank(vol.reindex(idx.index))
    s_raw = pd.concat([c_vix, S.pct_rank(mom), S.pct_rank(shv), S.pct_rank(brd)],
                      axis=1).mean(axis=1)
    s = s_raw.ewm(span=10).mean()
    return pd.DataFrame({"s": s, "c_vix": c_vix}).dropna()


def episodes(mask):
    """붙어있는 날들은 한 사건 — 일수가 아니라 이걸 센다."""
    if not len(mask) or not mask.any():
        return 0
    return int((mask.astype(int).diff() == 1).sum() + (1 if bool(mask.iloc[0]) else 0))


def contrarian(s, close):
    """극단공포(S<20) 뒤 반등이 극단탐욕(S>=80) 뒤보다 큰가 — 이 지표의 존재 이유."""
    fwd = close.reindex(s.index).ffill()
    fwd = fwd.shift(-FWD) / fwd - 1
    d = pd.concat([s.rename("s"), fwd.rename("f")], axis=1).dropna()
    lo, hi = d["s"] < 20, d["s"] >= 80
    return {"fear": d[lo]["f"].mean() * 100 if lo.any() else None,
            "greed": d[hi]["f"].mean() * 100 if hi.any() else None,
            "e_fear": episodes(lo), "e_greed": episodes(hi),
            "n_fear": int(lo.sum()), "n_greed": int(hi.sum())}


def main():
    px = kospi_ohlc()
    print(f"코스피 OHLC(FDR): {px.index[0]:%Y-%m-%d} ~ {px.index[-1]:%Y-%m-%d} ({len(px):,}일)")

    built = {}
    for name, vol in vol_variants(px).items():
        built[name] = build(vol)
        b = built[name]
        print(f"  {name:<9} S(t) {len(b):,}일  {b.index[0]:%Y-%m-%d} ~ {b.index[-1]:%Y-%m-%d}")

    # ── ① 체크포인트: 알려진 국면에서 상식과 맞나 ──
    print("\n① 체크포인트 — 괄호는 밴드. 폭락/약세장은 공포, 사상최고는 탐욕이어야 한다")
    print(f"  {'국면':<20} " + "".join(f"{n:>18}" for n in built))
    ok = {n: 0 for n in built}
    for label, day, want_fear in [("코로나 폭락 2020-03", "2020-03-19", True),
                                  ("사상최고 2021-06", "2021-06-25", False),
                                  ("약세장 2022-09", "2022-09-30", True)]:
        cells = ""
        for n, b in built.items():
            near = b[b.index <= day]
            if not len(near):
                cells += f"{'— 범위 밖':>18}"
                continue
            v = near.iloc[-1]["s"]
            hit = (v < 40) if want_fear else (v >= 60)
            ok[n] += hit
            cells += f"{f'{v:.0f} {S.band(v)}':>17}{'✓' if hit else '✗'}"
        print(f"  {label:<20} {cells}")
    print(f"  {'통과':<20} " + "".join(f"{f'{ok[n]}/3':>18}" for n in built))

    # ── ② 역발상: 극단공포 뒤 반등이 극단탐욕 뒤보다 큰가 ──
    print(f"\n② 역발상 — 이후 {FWD}거래일 코스피 수익률 (사건 수가 근거의 크기)")
    print(f"  {'추정량':<9} {'극단공포':>18} {'극단탐욕':>18} {'차이':>9}")
    for n, b in built.items():
        r = contrarian(b["s"], px["close"])
        if r["fear"] is None or r["greed"] is None:
            print(f"  {n:<9} {'— 극단 구간 없음':>18}")
            continue
        f = f"{r['fear']:+.2f}% (사건 {r['e_fear']}·{r['n_fear']}일)"
        g = f"{r['greed']:+.2f}% (사건 {r['e_greed']}·{r['n_greed']}일)"
        print(f"  {n:<9} {f:>18} {g:>18} {r['fear'] - r['greed']:>+8.2f}%p")

    print("\n판정: ①에서 통과 수가 줄지 않고 ②에서 차이가 커져야 교체 후보.")
    print("      사건 수가 한 자릿수면 차이가 커도 근거로 삼지 않는다.")
    print("\n(적재 없음 — DB 용량 영향 0)")


if __name__ == "__main__":
    main()
