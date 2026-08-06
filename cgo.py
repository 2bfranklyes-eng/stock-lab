# cgo.py — 주체별 미실현손익(CGO) 시계열 → cgo_daily
#
# "지금 누가 얼마나 물려 있나"를 매일 잰다. 처분효과(Shefrin & Statman 1985)와
# Grinblatt & Han(2005)의 Capital Gains Overhang — 사람은 오른 건 빨리 팔고 물린 건
# 붙들고 있어서, 미실현손익 분포가 곧 '앞으로 나올 매도 물량'의 지도가 된다.
#   · 개인이 깊이 물려 있으면 반등마다 본전 매도가 쏟아진다(상승 저항).
#   · 극단까지 가면 팔 사람이 소진된다(캐피추레이션 → 역발상 신호).
#
# holder_profile과의 관계: 저쪽은 '오늘 스냅샷 + 가격대별 분포'(개별종목 매물대 화면용),
# 이쪽은 '시장 전체 요약의 시계열'(게이지·추이용). 평단 계산 로직은 holders.avg_cost와 동일하다.
#
# ⚠️ 원자료 investor_flow가 2024-07-18부터라, win=365면 시계열은 2025-07경부터 시작한다.
#    창을 채우기 전 구간은 표본이 얕아 아예 내보내지 않는다(백분위가 왜곡되므로).
#
# 🚧 미완성 — 아직 크론에 넣지 말 것. 적재 전에 아래를 먼저 해결해야 한다.
#
# [해결됨] 표본 구성 흔들림: 주체의 창내 포지션이 0이 되면 그 종목이 빠져 매일 20~30개가
#   들락거렸고, 중앙값이 가격이 아니라 구성 변화로 움직였다(5거래일에 18%p 점프).
#   → 고정 유니버스(관측률 70%↑) + ffill(limit=20)로 n_stocks 166~193 → 171~183 안정화.
#
# [미해결] 창 경계 불연속: 그래도 하루 ±10%p가 남는다(2026-03-04 -10.2%p → 03-05 +7.4%p).
#   원인은 '365일 전 대량 매수일이 창 밖으로 빠지는 순간' + avg_cost_run의 pos<=0 리셋 규칙이
#   겹쳐, 여러 종목의 평단이 동시에 불연속 점프하는 것. 정확히 365일 전(2025-03-04)에
#   개인 수급 이벤트가 있으면 그 그림자가 1년 뒤 하루에 몰려 나타난다.
#   후보 해법 3가지 — 어느 쪽을 택할지는 지표 정의의 문제라 상의 필요:
#     ① 고정 앵커의 확장창(창 경계 자체를 없앰. 대신 '최근 1년'이라는 뜻은 사라짐)
#     ② pos<=0에서 평단을 리셋하지 않고 유지(불연속은 줄지만 '다 팔았는데 평단이 남음')
#     ③ 원인은 두고 EWM 평활(증상만 가림 — 다른 지수들과 달리 여기선 원인이 진짜 왜곡이라 비추천)
#
# 사용: python cgo.py           → 계산 + 적재 (크론용)
#       python cgo.py --dry     → 적재 없이 콘솔 요약만 + cgo_dry.csv
import os
import sys
from dotenv import load_dotenv
import pandas as pd
import numpy as np
from supabase import create_client

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

load_dotenv()
sb = create_client(os.environ["SUPABASE_URL"], os.environ["SUPABASE_SERVICE_KEY"])

TYPES = ["기관합계", "기타법인", "개인", "외국인합계"]
WINDOWS = [182, 365]
DEEP = -20.0          # '크게 물림' 기준(%)


def page_by_month(table, sel, lo, hi, extra=None):
    """깊은 offset은 서버 타임아웃(57014) → 월 단위로 잘라 각 구간에서만 얕게 페이지네이션."""
    out = []
    for m in pd.date_range(pd.Timestamp(lo).replace(day=1), hi, freq="MS"):
        a = m.strftime("%Y-%m-%d")
        b = (m + pd.offsets.MonthEnd(1)).strftime("%Y-%m-%d")
        start = 0
        while True:
            q = sb.table(table).select(sel).gte("dt", a).lte("dt", b)
            if extra:
                q = extra(q)
            r = q.order("dt").order("code").range(start, start + 999).execute().data
            out += r
            if len(r) < 1000:
                break
            start += 1000
    return pd.DataFrame(out)


def avg_cost_run(vol, val):
    """holders.avg_cost와 같은 규칙의 이동평균 매입단가.
    순매수일엔 평단 갱신, 순매도일엔 수량만 감소(평균원가법), 다 팔면 리셋.
    수량 +인데 대금 −인 날은 단가 불명이라 평단을 건드리지 않는다."""
    pos = cost = 0.0
    for nv, nval in zip(vol, val):
        if nv > 0 and nval > 0:
            px = nval / nv
            cost = (pos * cost + nv * px) / (pos + nv)
            pos += nv
        elif nv > 0:
            pos += nv
        else:
            pos += nv
            if pos <= 0:
                pos = cost = 0.0
    return pos, cost


def main():
    dry = "--dry" in sys.argv
    lo = sb.table("investor_flow").select("dt").order("dt").limit(1).execute().data
    hi = sb.table("investor_flow").select("dt").order("dt", desc=True).limit(1).execute().data
    if not lo:
        print("investor_flow 가 비어있음 — holders.py 를 먼저 실행하세요.")
        return
    lo, hi = lo[0]["dt"], hi[0]["dt"]
    print(f"investor_flow 구간: {lo} ~ {hi}")

    flow = page_by_month("investor_flow", "code,dt,inv,vol,val", lo, hi)
    flow["dt"] = pd.to_datetime(flow["dt"])
    print(f"  수급 {len(flow):,}행 · 종목 {flow['code'].nunique():,}개")

    px = page_by_month("stock_daily", "code,dt,close", lo, hi)
    px["dt"] = pd.to_datetime(px["dt"])
    px = px[~px["code"].isin(["kospi", "kosdaq"])]
    close = px.pivot_table(index="dt", columns="code", values="close")
    print(f"  시세 {len(px):,}행 · 거래일 {len(close):,}일")

    # (code, inv)별로 날짜 정렬된 vol/val 배열을 미리 만들어 둔다 — 매 시점 재계산의 재료
    flow = flow.sort_values("dt")
    grp = {k: (g["dt"].to_numpy(), g["vol"].to_numpy(dtype=float), g["val"].to_numpy(dtype=float))
           for k, g in flow.groupby(["code", "inv"])}
    codes = sorted(flow["code"].unique())

    dates = close.index
    recs = []
    for win in WINDOWS:
        # 창을 다 채운 날부터만 — 덜 찬 창은 평단이 얕아 값이 튄다
        first = pd.Timestamp(lo) + pd.Timedelta(days=win)
        days = [d for d in dates if d >= first]
        if not days:
            print(f"  [win={win}] 창을 채운 날이 없음 — 건너뜀")
            continue
        print(f"  [win={win}] {days[0].date()} ~ {days[-1].date()} ({len(days)}일) 계산 중...", flush=True)
        mat = {t: {} for t in TYPES}          # {주체: {날짜: {종목: CGO%}}}
        for d in days:
            start = d - pd.Timedelta(days=win)
            for t in TYPES:
                mat[t][d] = {}
            for c in codes:
                p = close.at[d, c] if c in close.columns else np.nan
                if not np.isfinite(p) or p <= 0:
                    continue
                for t in TYPES:
                    g = grp.get((c, t))
                    if g is None:
                        continue
                    dt_arr, v, w = g
                    m = (dt_arr > np.datetime64(start)) & (dt_arr <= np.datetime64(d))
                    if not m.any():
                        continue
                    pos, cost = avg_cost_run(v[m], w[m])
                    if pos > 0 and cost > 0:
                        mat[t][d][c] = p / cost * 100 - 100

        # ⚠️ 여기서 그날그날 있는 종목만 모아 중앙값을 내면 안 된다.
        #    주체의 창내 포지션이 0이 되면 그 종목이 표본에서 빠지는데, 매일 20~30개가
        #    들락거려 중앙값이 '가격'이 아니라 '표본 구성'으로 움직인다(실측: 5거래일에 18%p 점프).
        #    → ① 고정 유니버스(관측률 70%↑)로 묶고 ② 일시 이탈은 직전값으로 이어 붙인다.
        for t in TYPES:
            wide = pd.DataFrame(mat[t]).T.sort_index()      # 행=날짜, 열=종목
            if wide.empty:
                continue
            keep = wide.columns[wide.notna().mean() >= 0.70]
            wide = wide[keep].ffill(limit=20)
            for d, row in wide.iterrows():
                a = row.to_numpy(dtype=float)
                a = a[np.isfinite(a)]
                if len(a) < 30:          # 종목 30개 미만이면 시장 요약으로 못 쓴다
                    continue
                recs.append({"dt": d.strftime("%Y-%m-%d"), "win_days": win, "inv": t,
                             "n_stocks": int(len(a)),
                             "cgo_med": round(float(np.median(a)), 2),
                             "cgo_avg": round(float(a.mean()), 2),
                             "under_pct": round(float((a < 0).mean() * 100), 1),
                             "deep_pct": round(float((a < DEEP).mean() * 100), 1)})

    if not recs:
        print("계산 결과 없음 — 원자료 기간이 창보다 짧습니다.")
        return
    out = pd.DataFrame(recs)
    print(f"\n계산 완료: {len(out):,}행")
    last = out[out["dt"] == out["dt"].max()].sort_values("cgo_med")
    print(f"\n최신 {out['dt'].max()} — 주체별 미실현손익")
    print(last[["win_days", "inv", "n_stocks", "cgo_med", "under_pct", "deep_pct"]].to_string(index=False))

    ind = out[(out["inv"] == "개인") & (out["win_days"] == 365)].sort_values("dt")
    if len(ind) > 5:
        cur = ind["cgo_med"].iloc[-1]
        print(f"\n개인(365일) 추이: 최저 {ind['cgo_med'].min():+.1f}% "
              f"({ind.loc[ind['cgo_med'].idxmin(), 'dt']}) / 최고 {ind['cgo_med'].max():+.1f}% "
              f"({ind.loc[ind['cgo_med'].idxmax(), 'dt']}) / 현재 {cur:+.1f}% "
              f"· 백분위 {(cur > ind['cgo_med']).mean() * 100:.0f}%ile")

    if dry:
        p = os.path.join(os.path.dirname(os.path.abspath(__file__)), "cgo_dry.csv")
        out.to_csv(p, index=False, encoding="utf-8-sig")
        print(f"\n--dry: 적재 생략 (검토용 {p})")
        return
    rows = out.to_dict("records")
    for i in range(0, len(rows), 1000):
        sb.table("cgo_daily").upsert(rows[i:i + 1000], on_conflict="dt,win_days,inv").execute()
    print(f"cgo_daily 적재 완료: {len(rows):,}행")


if __name__ == "__main__":
    main()
