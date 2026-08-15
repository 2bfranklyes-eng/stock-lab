# volatility.py — 코스피·코스닥 OHLC로 변동성을 재고 예측한다. 방향이 아니라 '폭'.
#
# 왜 이걸 하나: 시계열 국면 연구는 극단 사건이 5~10개뿐이라 검정력이 없다(marketmode.py 참조).
#   변동성은 다르다 — 매일 하나씩 관측이 쌓이므로 표본이 '사건 수'가 아니라 '일수'다.
#   수익률은 자기상관이 없지만 변동성은 강하게 지속되어, 여기선 실제로 예측이 된다.
#
# 두 가지를 따로 잰다. 섞으면 안 된다:
#   ① 추정 — 오늘의 변동성을 얼마나 정확히 재나. 종가만 쓰는 것보다 고저가를 쓰면 훨씬 효율적.
#   ② 예측 — 내일의 변동성을 얼마나 맞히나. HAR(일/주/월 3성분)을 단순 기준선과 붙인다.
#
# ⚠️ 겹치는 창 금지: 20일 변동성을 매일 겹쳐 쓰면 관측이 사실상 20배 부풀려진다.
#    여기서는 1일 앞 예측만 본다 — 겹치지 않아 ~1,200개가 그대로 독립 관측이다.
#
# ⚠️ 장중 추정량(Parkinson·GK·RS)은 '동시간 거래'를 가정해 밤 사이 갭을 못 잡는다.
#    한국장은 하루 17.5시간이 닫혀 있어 이들은 총변동성을 체계적으로 과소평가한다.
#    갭까지 포함하는 건 종가대종가(CC)와 Yang-Zhang(YZ)뿐 — 수준 비교는 이 둘끼리만.
import os
import sys
from dotenv import load_dotenv
import numpy as np
import pandas as pd
from supabase import create_client

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

load_dotenv()
sb = create_client(os.environ["SUPABASE_URL"], os.environ["SUPABASE_SERVICE_KEY"])

ANN = 252          # 연율화 계수
BURN = 252         # 예측 평가 전 학습에 쓸 최소 일수(확장창 시작점)
FLOOR = 1e-10      # 로그·QLIKE에서 0 분산 방지


def fetch_ohlc(code):
    rows, step, start = [], 1000, 0
    while True:
        r = sb.table("stock_daily").select("dt,open,high,low,close") \
              .eq("code", code).order("dt").range(start, start + step - 1).execute().data
        rows += r
        if len(r) < step:
            break
        start += step
    df = pd.DataFrame(rows)
    df["dt"] = pd.to_datetime(df["dt"])
    return df.set_index("dt").astype(float).sort_index()


def estimators(df):
    """일별 분산 추정량들. 단위는 '하루치 분산'(연율화 전)."""
    o, h, l, c = np.log(df["open"]), np.log(df["high"]), np.log(df["low"]), np.log(df["close"])
    prev_c = c.shift(1)

    out = pd.DataFrame(index=df.index)
    out["cc"] = (c - prev_c) ** 2                              # 종가대종가 — 갭 포함, 하지만 잡음 큼
    out["park"] = (h - l) ** 2 / (4 * np.log(2))               # Parkinson(1980) — 장중만
    out["gk"] = (0.5 * (h - l) ** 2                            # Garman-Klass(1980) — 장중만
                 - (2 * np.log(2) - 1) * (c - o) ** 2)
    out["rs"] = ((h - c) * (h - o) + (l - c) * (l - o))        # Rogers-Satchell(1991) — 추세에 강건
    out["ovn"] = (o - prev_c) ** 2                             # 밤 사이 갭 성분
    return out.dropna()


def yang_zhang(df, n=20):
    """Yang-Zhang(2000) n일 분산 — 갭과 추세를 모두 처리하는 유일한 조합.
    σ²_YZ = σ²_밤 + k·σ²_장중 + (1-k)·σ²_RS"""
    o, h, l, c = np.log(df["open"]), np.log(df["high"]), np.log(df["low"]), np.log(df["close"])
    ovn, oc = o - c.shift(1), c - o
    rs = (h - c) * (h - o) + (l - c) * (l - o)
    k = 0.34 / (1.34 + (n + 1) / (n - 1))
    return (ovn.rolling(n).var() + k * oc.rolling(n).var()
            + (1 - k) * rs.rolling(n).mean()).dropna()


# ── ① 추정 효율: 잡음이 적은 추정량일수록 '앞으로의 변동성'을 잘 설명한다 ──
def efficiency(est, fwd_days=20):
    """각 추정량의 n일 평균을 이후 fwd_days의 실현분산(CC)에 회귀 → R².
    측정오차가 크면 감쇠편향으로 R²가 떨어지므로, R²가 곧 효율의 대리지표다."""
    # 뒤집어 rolling → 되돌리면 t 시점에 t..t+19 평균. shift(-1)로 t+1..t+20 으로 민다.
    target = est["cc"][::-1].rolling(fwd_days).mean()[::-1].shift(-1)
    rows = []
    for name in ["cc", "park", "gk", "rs"]:
        x = est[name].rolling(fwd_days).mean()
        d = pd.concat([np.log(x.clip(lower=FLOOR)).rename("x"),
                       np.log(target.clip(lower=FLOOR)).rename("y")], axis=1).dropna()
        r = np.corrcoef(d["x"], d["y"])[0, 1]
        rows.append((name, r ** 2, len(d)))
    return rows


# ── ② 예측: HAR(일/주/월) vs 단순 기준선, 확장창 out-of-sample ──
def har_features(rv):
    """Corsi(2009) HAR — 서로 다른 시간대의 참여자가 만드는 3성분."""
    x = pd.DataFrame({
        "d": rv,
        "w": rv.rolling(5).mean(),
        "m": rv.rolling(22).mean(),
    })
    return x


def oos_forecast(rv):
    """확장창으로 매일 재적합해 1일 앞 로그분산을 예측. 겹치지 않으므로 관측이 독립."""
    lrv = np.log(rv.clip(lower=FLOOR))
    X, y = har_features(lrv), lrv.shift(-1)
    d = pd.concat([X, y.rename("y")], axis=1).dropna()
    if len(d) < BURN + 50:
        return None

    preds = {"HAR": [], "RW": [], "MA20": [], "actual": [], "dt": []}
    Xv, yv = d[["d", "w", "m"]].values, d["y"].values
    for i in range(BURN, len(d)):
        Xtr = np.column_stack([np.ones(i), Xv[:i]])
        beta, *_ = np.linalg.lstsq(Xtr, yv[:i], rcond=None)
        preds["HAR"].append(float(np.r_[1.0, Xv[i]] @ beta))
        preds["RW"].append(float(Xv[i, 0]))          # 오늘 값 그대로 = 임의보행
        preds["MA20"].append(float(Xv[i, 2]))        # 22일 평균
        preds["actual"].append(float(yv[i]))
        preds["dt"].append(d.index[i])
    return pd.DataFrame(preds).set_index("dt")


def qlike(actual_var, pred_var):
    """분산 예측의 적정 손실함수(비대칭). 낮을수록 좋다."""
    a = np.clip(actual_var, FLOOR, None)
    p = np.clip(pred_var, FLOOR, None)
    return float(np.mean(a / p - np.log(a / p) - 1))


def report(name, df):
    print(f"\n{'=' * 62}\n[{name}]  {df.index[0]:%Y-%m-%d} ~ {df.index[-1]:%Y-%m-%d}  ({len(df):,}일)")
    est = estimators(df)

    # 수준 비교 — 갭을 포함하는 CC/YZ 와 장중 전용 추정량을 갈라서 본다
    ann = lambda v: np.sqrt(v.mean() * ANN) * 100
    yz = yang_zhang(df)
    print(f"\n연율 변동성 평균 — 갭 포함: CC {ann(est['cc']):.1f}%  YZ {np.sqrt(yz.mean()*ANN)*100:.1f}%")
    print(f"                   장중만: Parkinson {ann(est['park']):.1f}%  "
          f"GK {ann(est['gk']):.1f}%  RS {ann(est['rs']):.1f}%")
    print(f"                   밤 갭 성분이 전체 분산의 {est['ovn'].mean()/est['cc'].mean():.0%}")

    print("\n① 추정 효율 — 이후 20일 실현분산에 대한 R² (높을수록 잡음이 적은 추정량)")
    for nm, r2, n in efficiency(est):
        print(f"   {nm:<6} R²={r2:.3f}  (n={n:,})")

    print("\n② 1일 앞 예측 — 확장창 out-of-sample, 목표=Rogers-Satchell 분산")
    fc = oos_forecast(est["rs"])
    if fc is None:
        print("   표본 부족")
        return
    base_mse = np.mean((fc["actual"] - fc["RW"]) ** 2)
    print(f"   {'모형':<6} {'로그 R²':>8} {'RW대비 개선':>11} {'QLIKE':>9}")
    for m in ["RW", "MA20", "HAR"]:
        mse = np.mean((fc["actual"] - fc[m]) ** 2)
        r2 = 1 - mse / np.var(fc["actual"])
        imp = 1 - mse / base_mse
        ql = qlike(np.exp(fc["actual"]), np.exp(fc[m]))
        print(f"   {m:<6} {r2:>8.3f} {imp:>10.1%} {ql:>9.3f}")
    print(f"   평가 표본 {len(fc):,}일 (겹치지 않음 → 독립 관측 {len(fc):,}개)")


if __name__ == "__main__":
    for code, label in [("kospi", "코스피"), ("kosdaq", "코스닥")]:
        report(label, fetch_ohlc(code))
    print("\n(적재 없음 — 추정량 교체는 sentiment.py 의 ①체크포인트·②역발상 기준을 통과해야 한다)")
