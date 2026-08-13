# marketmode.py — 코스피/코스닥 개별종목 횡단면에서 '시장 모드' 강도를 잰다 (한국 전용).
#
# 아이디어: 상관행렬의 최대고유값 λ₁이 전체 분산에서 차지하는 비중 = 다 같이 움직이는 정도.
#   낮으면 종목마다 따로 논다(골고루·탐욕 쪽), 높으면 한 방향으로 쏠린다(위기·공포 쪽).
#   sentiment.py 의 c_breadth(코스닥-코스피 20일 수익률차)가 재려던 것과 같은 대상을,
#   지수 두 개가 아니라 500종목 횡단면에서 직접 재는 정공법이다.
#
# ⚠️ 이 스크립트는 기본적으로 '적재하지 않는다'. sentiment.py 상단 경고대로 성분 교체는
#    동시점 상관이 아니라 ①체크포인트 ②역발상으로 판정해야 하므로, 먼저 비교표만 찍는다.
#    두 기준을 통과한 뒤에야 --write 로 sentiment_daily 에 컬럼을 추가한다.
#
# ⚠️ PIT 한계: stock_daily 워치리스트는 '현재' 시총 상위 N이다. 과거 구간에 지금의 승자를
#    소급 적용하는 유니버스 look-ahead가 남아있다. 백분위 정규화로 상당 부분 상쇄되지만
#    제거된 건 아니다 — 수준값이 아니라 '시간에 따른 변화'로만 읽을 것.
#
# ⚠️ 미국은 계산 불가. indicator_raw 에 미국 개별종목 횡단면이 없다(지수·VIX뿐).
import os
import sys
import pickle
from dotenv import load_dotenv
import numpy as np
import pandas as pd
from supabase import create_client

try:  # 윈도우 콘솔(cp949)에서도 한글·기호 출력이 깨지지 않게
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

load_dotenv()
sb = create_client(os.environ["SUPABASE_URL"], os.environ["SUPABASE_SERVICE_KEY"])

CACHE = "marketmode_cache.pkl"
WIN = 120          # 상관 추정 창(거래일). 짧으면 시끄럽고 길면 둔하다.
MIN_STOCK = 100    # 창 안에서 결측 없는 종목이 이보다 적은 날은 건너뜀
PCT_WIN = 252      # 백분위 정규화 창 — sentiment.py 와 동일하게 1년

INDEX_CODES = {"kospi", "kosdaq"}   # stock_daily 에 지수도 같은 테이블로 들어있다


def fetch_closes():
    """stock_daily 전체 종가를 페이지네이션으로 가져온다 (API 1000행 제한 우회).
    ~95만 행 = egress 약 40MB라 캐시를 남긴다."""
    if os.path.exists(CACHE):
        with open(CACHE, "rb") as f:
            df = pickle.load(f)
        print(f"캐시 사용: {CACHE} ({len(df):,}행)  — 새로 받으려면 이 파일을 지우세요")
        return df

    # 월 단위로 끊어 받는다 — 전체를 offset 페이지네이션하면 뒤로 갈수록 O(offset)이라 급격히 느려진다.
    span = sb.table("stock_daily").select("dt").order("dt").limit(1).execute().data
    if not span:
        raise SystemExit("stock_daily 가 비어있음 — krx.py 를 먼저 실행하세요")
    months = pd.date_range(span[0]["dt"], pd.Timestamp.today(), freq="MS")

    rows, step = [], 1000
    for m0 in months:
        m1 = m0 + pd.offsets.MonthBegin(1)
        start = 0
        while True:
            r = sb.table("stock_daily").select("dt,code,close") \
                  .gte("dt", m0.strftime("%Y-%m-%d")).lt("dt", m1.strftime("%Y-%m-%d")) \
                  .order("dt").order("code").range(start, start + step - 1).execute().data
            rows += r
            if len(r) < step:
                break
            start += step
        print(f"  {m0:%Y-%m} … 누적 {len(rows):,}행", end="\r")
    print()
    df = pd.DataFrame(rows)
    with open(CACHE, "wb") as f:
        pickle.dump(df, f)
    print(f"수집 완료: {len(df):,}행 → {CACHE} 에 캐시")
    return df


def market_mode(px, win=WIN, min_stock=MIN_STOCK):
    """날짜별 λ₁/N (최대고유값의 분산 점유율)과 유효 종목수를 돌려준다."""
    ret = np.log(px).diff()
    dates, shares, counts = [], [], []

    for i in range(win, len(ret)):
        blk = ret.iloc[i - win + 1:i + 1]
        blk = blk.dropna(axis=1)                      # 창 안에서 완전한 종목만
        blk = blk.loc[:, blk.std() > 0]               # 무변동(거래정지 등) 제거
        n = blk.shape[1]
        if n < min_stock:
            continue
        # 상관행렬의 고유값 합 = N 이므로 λ₁/N 이 곧 '설명 분산 비중'
        c = np.corrcoef(blk.values, rowvar=False)
        lam1 = np.linalg.eigvalsh(c)[-1]              # eigvalsh = 대칭행렬, 오름차순
        dates.append(ret.index[i])
        shares.append(lam1 / n)
        counts.append(n)

    return pd.DataFrame({"mode_share": shares, "n_stock": counts}, index=pd.DatetimeIndex(dates))


def pct_rank(s, win=PCT_WIN):
    """sentiment.py 와 동일한 정규화 — 지난 win일 분포에서의 위치(0~100)."""
    return s.rolling(win).apply(lambda x: (x.iloc[-1] > x.iloc[:-1]).mean() * 100, raw=False)


def main(write=False):
    df = fetch_closes()
    df["dt"] = pd.to_datetime(df["dt"])
    kospi = px_index(df)                              # ⚠️ 지수 제외 '전에' 뽑아야 한다
    df = df[~df["code"].isin(INDEX_CODES)]            # 지수 제외, 개별종목만
    px = df.pivot(index="dt", columns="code", values="close").sort_index().astype(float)
    print(f"횡단면: {px.shape[1]}종목 × {px.shape[0]:,}일 "
          f"({px.index[0]:%Y-%m-%d} ~ {px.index[-1]:%Y-%m-%d})")

    mm = market_mode(px)
    if mm.empty:
        print("계산 결과 없음 — 창 길이나 MIN_STOCK 을 확인하세요")
        return
    q = px.shape[1] / WIN
    print(f"시장모드 산출: {len(mm):,}일  ·  창 {WIN}일  ·  q=N/T≈{q:.1f}  "
          f"(유효종목 중앙값 {mm['n_stock'].median():.0f})")

    # 쏠림↑ = 공포 쪽이므로, sentiment.py 의 '높을수록 탐욕' 방향에 맞추려면 뒤집는다.
    c_mode = 100 - pct_rank(mm["mode_share"])

    # 유니버스가 시간에 따라 얼마나 흔들리는지 — λ₁/N 은 N에 민감하므로 먼저 확인한다
    print("\n유효종목수 추이(연말 기준)")
    for y, g in mm.groupby(mm.index.year):
        print(f"  {y}  중앙값 {g['n_stock'].median():>5.0f}  "
              f"최소 {g['n_stock'].min():>5.0f}  최대 {g['n_stock'].max():>5.0f}")

    # ── 기존 c_breadth 와 비교 (PostgREST 기본 1000행 제한 → 페이지네이션 필수) ──
    srows, step, start = [], 1000, 0
    while True:
        r = sb.table("sentiment_daily").select("dt,s_score,c_breadth,band") \
              .eq("market", "KR").order("dt").range(start, start + step - 1).execute().data
        srows += r
        if len(r) < step:
            break
        start += step
    sent = pd.DataFrame(srows)
    sent["dt"] = pd.to_datetime(sent["dt"])
    sent = sent.set_index("dt")
    print(f"\nsentiment_daily(KR): {len(sent):,}일 "
          f"({sent.index[0]:%Y-%m-%d} ~ {sent.index[-1]:%Y-%m-%d})")

    both = pd.concat([c_mode.rename("c_mode"), sent["c_breadth"], sent["s_score"]],
                     axis=1).dropna()
    if both.empty:
        print("겹치는 구간 없음 — c_mode 가 시작되는 시점보다 sentiment_daily 가 먼저 끝남")
        return
    print(f"겹치는 구간: {len(both):,}일 "
          f"({both.index[0]:%Y-%m-%d} ~ {both.index[-1]:%Y-%m-%d})")
    print(f"c_mode vs c_breadth 상관: {both['c_mode'].corr(both['c_breadth']):+.3f}")
    print(f"c_mode vs s_score  상관: {both['c_mode'].corr(both['s_score']):+.3f}")

    # ── ① 체크포인트: 알려진 국면에서 상식과 맞나 (sentiment.py 의 KR 기준일) ──
    print("\n① 체크포인트 — 위기에 쏠림(낮은 c_mode)이 나오나")
    print(f"  {'국면':<22} {'c_mode':>7} {'c_breadth':>10} {'λ₁/N':>7}")
    for label, day in [("코로나 폭락 2020-03", "2020-03-19"),
                       ("사상최고 2021-06", "2021-06-25"),
                       ("약세장 2022-09", "2022-09-30")]:
        near, raw = both[both.index <= day], mm[mm.index <= day]
        if not len(raw):
            print(f"  {label:<22} {'— 데이터 범위 밖':>7}")
            continue
        cm = f"{near.iloc[-1]['c_mode']:>7.0f}" if len(near) else f"{'—':>7}"
        cb = f"{near.iloc[-1]['c_breadth']:>10.0f}" if len(near) else f"{'—':>10}"
        print(f"  {label:<22} {cm} {cb} {raw.iloc[-1]['mode_share']:>7.1%}")

    # ── ② 역발상: 극단 이후 20일 수익률이 갈리나 ──
    print(f"\n② 역발상 — 하위20%(쏠림) vs 상위20%(분산) 이후 20일 코스피 수익률 "
          f"(코스피 {len(kospi):,}일)")
    for name, series in [("c_mode", both["c_mode"]), ("c_breadth", both["c_breadth"])]:
        lo, hi, e_lo, e_hi = contrarian(series, kospi)
        gap = "—" if lo is None or hi is None else f"{lo - hi:+.2f}%p"
        print(f"  {name:<10} 하위20% {fmt(lo)}(사건 {e_lo})  ·  "
              f"상위20% {fmt(hi)}(사건 {e_hi})  ·  차이 {gap}")

    print("\n판정 기준: ①에서 위기 때 c_mode 가 낮게 나오고, ②에서 차이가 c_breadth 보다"
          "\n크면 교체 후보. 아니면 기존 성분을 유지하고 진단용으로만 둘 것.")

    if write:
        rows = [{"market": "KR", "dt": d.strftime("%Y-%m-%d"),
                 "c_mode": round(float(v), 2)}
                for d, v in c_mode.dropna().items()]
        for i in range(0, len(rows), 1000):
            sb.table("sentiment_daily").upsert(rows[i:i + 1000],
                                               on_conflict="market,dt").execute()
        print(f"\n[KR] c_mode 적재 완료: {len(rows)}일 (≈{len(rows) * 8 / 1024:.0f}KB)")
    else:
        print("\n(적재 안 함 — 두 기준 통과 후 `python marketmode.py --write`)")


def px_index(df):
    """코스피 지수 종가 — 역발상 검증의 수익률 기준."""
    k = df[df["code"] == "kospi"].set_index("dt")["close"].astype(float).sort_index()
    return k


def episodes(mask):
    """연속된 True 덩어리 수 — 붙어있는 날들은 사실상 한 사건이므로 일수 대신 이걸 본다."""
    return int((mask.astype(int).diff() == 1).sum() + (1 if bool(mask.iloc[0]) else 0))


def contrarian(score, idx, fwd=20, q=0.2):
    """점수 하위/상위 q 구간에서 이후 fwd거래일 지수 수익률 평균(%)과 사건 수."""
    aligned = idx.reindex(score.index).ffill()
    fut = aligned.shift(-fwd) / aligned - 1
    d = pd.concat([score.rename("s"), fut.rename("f")], axis=1).dropna()
    if len(d) < 50:
        return None, None, 0, 0
    m_lo, m_hi = d["s"] <= d["s"].quantile(q), d["s"] >= d["s"].quantile(1 - q)
    return (d[m_lo]["f"].mean() * 100, d[m_hi]["f"].mean() * 100,
            episodes(m_lo), episodes(m_hi))


def fmt(v):
    return "—" if v is None else f"{v:+.2f}%"


if __name__ == "__main__":
    main(write="--write" in sys.argv)
