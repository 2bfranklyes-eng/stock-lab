# crossval_models.py — 매물대 감쇠 모델 게이트: M0(현행 단일속도) vs M2(이중속도)를
#   '투자자 순매수 실측'(crossval.py의 B)과의 분포 일치도로 심판한다.
#
#   배경: M2(An 2016류 — 유입 물량을 단타/장기 코호트로 나눠 다른 속도로 소진)는
#   프로토타입 검증에서 자체 지표(두께↔|변동|)를 20종목 대부분에서 일관 개선했지만
#   폭이 작아(Δ상관 0.01~0.02) 그것만으론 채택 근거가 못 된다. 투자자별 실측 분포와
#   더 잘 맞는지가 결정 기준 — 더 잘 맞으면 채택하고, 가장 잘 맞는 (θ, k_fast)로
#   캘리브레이션까지 이 게이트에서 끝낸다.
#
#   결과(2026-08-02, 시총상위 12종목): 2년 창 — M0 중앙상관 +0.76로 전 변형에 우위, 분리가
#   셀수록 단조 악화(θ0.5k1.8은 +0.70, SK하이닉스는 +0.45→+0.09 붕괴). 5년 창 — 약한 분리
#   (k1.4)가 +0.89 vs +0.87로 근소 우위(7/12)지만, 화면에 쓰는 '현재가 위 매물' 오차는 M0이
#   최소(5.6%p vs 5.8~9.2%p). 내부 두께지표가 가장 선호한 강분리(θ0.5k1.8)가 B와는 가장
#   어긋남 → 두께지표는 모델 판정 기준으로 부적합. 결론: M0(현행 단일속도) 유지.
#
#   구현 주의: 이중속도의 소진 정규화는 '두 풀 합산 예산' 한 번으로 해야 한다.
#   풀별로 따로 정규화하면 속도 배율이 스케일에서 상쇄되어 M0과 완전히 같아진다.
#   (M0은 k_fast=k_slow=1인 특수해 — 종목마다 profile.build와 일치하는지 검산한다)
#
#   사용: python crossval_models.py                       → 시총 상위 12종목, 2년+5년 창
#         python crossval_models.py 005930 000660 --win 730
import re
import sys
import numpy as np
import pandas as pd
from dotenv import load_dotenv

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

load_dotenv()                    # KRX_ID/KRX_PW를 올린 뒤에 pykrx를 임포트해야 로그인이 붙는다
import profile as vp             # noqa: E402  A측(감쇠 모델) 재사용
import crossval as cv            # noqa: E402  B측(투자자 실측)·load_price 재사용
from pykrx import stock          # noqa: E402

# (θ=단타 유입비중, k_fast=단타 소진 배율) — 분리 강도 약→강 순.
# k_slow는 θ·k_fast+(1-θ)·k_slow=1 로 종속(그날 총 소진량은 M0과 동일하게 보존).
GRID = [(0.5, 1.4), (0.7, 1.3), (0.3, 2.5), (0.5, 1.8), (0.2, 4.0)]
WINDOWS = [730, 1825]
NBINS = 60
N_STOCKS = 12


def build_dual(df, nbins, V, w, theta, k_fast, k_slow):
    """profile.build의 이중속도판 — 하루 순서 동일(소진 → 유입). M0은 k=1,1 특수해."""
    lo, hi = df["Low"].min(), df["High"].max()
    edges = np.linspace(lo, hi, nbins + 1)
    bin_lo, bin_hi = edges[:-1], edges[1:]
    fast, slow = np.zeros(nbins), np.zeros(nbins)
    for l, h, v, vt in zip(df["Low"], df["High"], np.asarray(w, float), np.asarray(V, float)):
        tot = fast.sum() + slow.sum()
        if tot > 0 and vt > 0:
            budget = vt * tot                    # 그날 팔린 총량은 M0과 같게 고정하고
            for _ in range(4):                   # '누가 파는지'만 k 배율로 기울인다
                raw = k_fast * fast.sum() + k_slow * slow.sum()
                if raw <= 0 or budget <= 1e-12:
                    break
                sc = budget / raw
                sf = np.minimum(fast, fast * (k_fast * sc))
                ss = np.minimum(slow, slow * (k_slow * sc))
                fast -= sf
                slow -= ss
                spent = sf.sum() + ss.sum()
                budget -= spent
                if spent <= 1e-12:               # 상한(전량)까지 다 팔려 예산이 안 소진되는 극단 방어
                    break
        if v <= 0:
            continue
        span = max(h - l, 1e-9)
        frac = np.clip(np.minimum(h, bin_hi) - np.maximum(l, bin_lo), 0, None) / span
        s = frac.sum()
        if s <= 0:
            continue
        vb = v * frac / s
        fast += vb * theta
        slow += vb * (1 - theta)
    return edges, fast + slow


def fetch_flows(code, frm, to):
    """투자자별 순매수 수량. 창이 길면 KRX가 응답을 자를 수 있어 1년 단위로 나눠 붙인다."""
    parts, f, end = [], pd.Timestamp(frm), pd.Timestamp(to)
    while f <= end:
        t = min(f + pd.Timedelta(days=364), end)
        parts.append(stock.get_market_trading_volume_by_date(
            f.strftime("%Y%m%d"), t.strftime("%Y%m%d"), code))
        f = t + pd.Timedelta(days=1)
    vol = pd.concat(parts)
    return vol[~vol.index.duplicated()]


def targets(n):
    rows = vp.client().table("vp_stocks").select("code,name,hist_days") \
        .order("marcap", desc=True).limit(40).execute().data or []
    out = [(r["code"], r["name"]) for r in rows
           if r["hist_days"] >= 1825 and not re.search(r"우[AB]?$", r["name"])]
    return out[:n]


def run(code, name, win):
    df, _events = cv.load_price(code, win)
    if len(df) < 200:
        raise RuntimeError(f"데이터 {len(df)}일뿐")
    px = float(df["Close"].iloc[-1])
    V = np.clip(df["tval"] / df["mktcap"], 0, 0.5).to_numpy()
    w = vp.qty(df)

    edges, rem0, _ = vp.build(df, NBINS, V, w)
    chk = build_dual(df, NBINS, V, w, 0.5, 1.0, 1.0)[1]      # 이식 검산: k=1이면 M0과 동일해야
    if not np.allclose(chk, rem0, rtol=1e-6, atol=1e-6):
        print(f"  [경고] {code}: 이중속도(k=1) ≠ profile.build — 이식 불일치")
    models = [("M0", rem0)]
    for th, kf in GRID:
        ks = (1 - th * kf) / (1 - th)
        models.append((f"θ{th}k{kf}", build_dual(df, NBINS, V, w, th, kf, ks)[1]))

    vol = fetch_flows(code, df.index[0], df.index[-1]).reindex(df.index).fillna(0)
    remB, _ = cv.holdings_profile(vol, df["Low"].to_numpy(), df["High"].to_numpy(), edges)
    if remB.sum() <= 0:
        raise RuntimeError("B 실측 물량 합 0")
    b = remB / remB.sum() * 100
    mid = (edges[:-1] + edges[1:]) / 2
    upB = float(b[mid > px].sum())

    out = []
    for nm, rem in models:
        a = rem / max(rem.sum(), 1e-9) * 100
        out.append({"nm": nm, "corr": float(np.corrcoef(a, b)[0, 1]),
                    "l1": float(np.abs(a - b).sum() / 2),
                    "dup": float(a[mid > px].sum() - upB)})
    return out, px, upB


if __name__ == "__main__":
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    wins = WINDOWS
    if "--win" in sys.argv:
        w = int(sys.argv[sys.argv.index("--win") + 1])
        wins, args = [w], [a for a in args if a != str(w)]
    tg = [(c, stock.get_market_ticker_name(c)) for c in args] if args else targets(N_STOCKS)

    for win in wins:
        print(f"\n{'#' * 74}\n# 창 {win}일 — 모델별 B 실측(투자자 순매수 보유분포)과의 상관\n{'#' * 74}")
        agg = {}
        for code, name in tg:
            try:
                res, px, upB = run(code, name, win)
            except Exception as e:
                print(f"  {name}({code}) 실패: {e}")
                continue
            best = max(res[1:], key=lambda r: r["corr"])
            cells = " | ".join(f"{r['nm']} {r['corr']:+.2f}" for r in res)
            mark = best["nm"] if best["corr"] > res[0]["corr"] else "M0"
            print(f"  {name}({code}) · B위쪽 {upB:.0f}%  {cells}  ← 최고 {mark}")
            for r in res:
                agg.setdefault(r["nm"], []).append({**r, "code": code})

        base = {r["code"]: r["corr"] for r in agg.get("M0", [])}
        n = len(base)
        if not n:
            continue
        print(f"\n  [요약 — {n}종목 · 창 {win}일]")
        print("   모델          중앙 상관   M0 대비 우위   중앙 L1   중앙 |위쪽 차|")
        for nm in ["M0"] + [f"θ{th}k{kf}" for th, kf in GRID]:
            rs = agg.get(nm, [])
            if not rs:
                continue
            wins_ = sum(1 for r in rs if r["corr"] > base.get(r["code"], np.nan))
            print(f"   {nm:12} {np.median([r['corr'] for r in rs]):+.3f}"
                  f"       {'—' if nm == 'M0' else f'{wins_}/{len(rs)}'}"
                  f"         {np.median([r['l1'] for r in rs]):5.1f}%"
                  f"     {np.median([abs(r['dup']) for r in rs]):4.1f}%p")
