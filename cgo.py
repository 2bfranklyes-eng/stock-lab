# cgo.py — 주체별 미실현손익(CGO) 시계열 → cgo_daily
#
# "지금 누가 얼마나 물려 있나"를 매일 잰다. 처분효과(Shefrin & Statman 1985)와
# Grinblatt & Han(2005)의 Capital Gains Overhang — 사람은 오른 건 빨리 팔고 물린 건
# 붙들고 있어서, 미실현손익 분포가 곧 '앞으로 나올 매도 물량'의 지도가 된다.
#   · 개인이 깊이 물려 있으면 반등마다 본전 매도가 쏟아진다(상승 저항).
#   · 극단까지 가면 팔 사람이 소진된다(캐피추레이션 → 역발상 신호).
#
# holder_profile과의 관계: 저쪽은 '오늘 스냅샷 + 가격대별 분포'(개별종목 매물대 화면용),
# 이쪽은 '시장 전체 요약의 시계열'(게이지·추이용).
#
# ── 평단 계산: 창을 자르지 않고 감쇠 가중한다 ──────────────────────────────
# 📌 먼저 오해 하나를 접어둔다. 이 지표가 2026-03-04에 하루 -10%p 튀는 걸 보고
#    '365일 전 대량 매수가 창 밖으로 빠져서'라고 의심한 적이 있는데, 아니었다.
#    그날은 코스피가 5791.91 → 5093.54(-12.1%), 코스닥 -14%로 빠진 실제 폭락일이다.
#    CGO ≈ 가격/평단이라 지수가 12% 빠지면 CGO도 12%p 빠지는 게 정상 동작이다.
#    (판별 근거: 창이 원인이면 창 길이가 다른 hl=182에는 안 나와야 하는데 똑같이 났고,
#     가격을 걷어내고 평단만 재면 그날 평단 일간 변화율 중앙값이 0.00%였다.)
#    그러니 '하루에 크게 움직인다'는 것만으로 계산을 의심하지 말 것 — 먼저 지수를 보라.
#
# 정의를 감쇠로 바꾼 건 그 오해와 별개로 남는 이점 때문이다. 매수의 무게를 하루마다
# 조금씩 줄인다 — 반감기 hl일이면 hl일 전 매수는 절반의 무게로만 남는다.
#   · 경계가 없다: 언젠가 진짜 경계 효과가 생길 여지 자체를 없앤다.
#   · 원전에 가깝다: G&H(2005)의 참조가격도 과거 매수를 감쇠 가중한 것이다.
#   · 빠르다: 매 시점 창을 처음부터 재생하지 않고 종목당 한 번만 훑는다.
# 실측 차이는 미미하다(평단 일간 변화율 중앙값 0.025% → 0.020%). 안정성을 위해 바꾼 게
# 아니라 정의를 단순하게 만들려고 바꾼 것이다.
#
# ⚠️ 그래서 holders.avg_cost(창 방식)와 계산 규칙이 갈린다. 개별종목 매물대 화면의
#    평단선과 이 게이지의 평단은 다른 값이다 — 의도된 차이다. 저쪽은 '오늘 이 종목의
#    보유 단가', 이쪽은 '시장 전체가 얼마나 물렸나'를 추이로 보는 지표라 목적이 다르다.
#
# ⚠️ 분할 보정은 여기서도 필수다. stock_daily는 수정주가가 아니라서, 가격에 split_adjust
#    배율을 곱하고 순매수 '수량'은 그 역수로 나눠야 평단과 종가가 같은 주수 단위에 놓인다
#    (대금은 분할과 무관). holders.py가 같은 이유로 같은 보정을 한다 — 규칙이 갈리는 건
#    '평균 내는 방식'뿐이고, 단위 정규화는 갈리면 안 되는 부분이다.
#
# ⚠️ 원자료 investor_flow가 2024-07-18부터다. 반감기만큼은 예열해야 무게가 실리므로
#    시계열은 hl=182면 2025-01경, hl=365면 2025-07경부터 시작한다.
#    창과 달리 감쇠는 기억이 무한해서, 자료 시작 이전의 매수가 통째로 빠진 채 계산된다.
#    실측하면 이력 6개월 차이가 cgo_med를 평균 0.54%p·최대 1.84%p 움직인다 — 방향이 일정치
#    않아(초반 +0.85%p / 후반 -0.19%p) 추세를 만들진 않지만, 백분위는 이 정도 폭의 잡음을
#    깔고 있다고 보고 읽을 것. 자료가 길어질수록 줄어든다.
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
import profile as vp             # noqa: E402  split_adjust 재사용 (holders.py와 같은 규칙)

sb = create_client(os.environ["SUPABASE_URL"], os.environ["SUPABASE_SERVICE_KEY"])

TYPES = ["기관합계", "기타법인", "개인", "외국인합계"]
HALFLIVES = [182, 365]   # 매수 무게의 반감기(달력일)
DEEP = -20.0             # '크게 물림' 기준(%)
DAY = np.timedelta64(1, "D")


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


def cost_series(dt_arr, vol, val, days, hl):
    """감쇠 가중 이동평균 매입단가를 요청한 거래일마다 돌려준다(없으면 NaN).

    num = 감쇠 가중 매수대금, den = 감쇠 가중 매수수량 → 평단 = num/den.
    새 매수를 더하기 전에 기존 num·den을 경과일수만큼 감쇠시키므로, 오래된 매수일수록
    새 매수에 밀려난다. 감쇠는 num·den에 똑같이 걸려 비율(평단)은 건드리지 않는다 —
    바뀌는 건 '앞으로 들어올 매수에 얼마나 희석되는가' 뿐이다.

    순매도는 평균원가법대로 단가를 그대로 두고 수량만 덜어낸다. 단 실제 포지션 대비
    '비율'로 덜어낸다(절대 주수로 빼면 감쇠된 den이 실제보다 빨리 말라버린다).
    다 팔면(pos<=0) 리셋 — 이후 첫 매수가 새 평단이 된다.
    수량 +인데 대금 −인 날은 단가 불명이라 현재 평단으로 채워 넣어 평단을 유지한다.
    """
    d1 = 0.5 ** (1.0 / hl)            # 하루치 감쇠 계수
    out = np.full(len(days), np.nan)
    pos = num = den = 0.0             # pos는 감쇠 없는 실제 순포지션(매도 비율·표본 판정용)
    prev = None
    i, n = 0, len(dt_arr)
    for k, d in enumerate(days):
        d64 = np.datetime64(d)
        while i < n and dt_arr[i] <= d64:
            t, nv, nw = dt_arr[i], vol[i], val[i]
            i += 1
            if nv == 0:
                continue
            if prev is not None and den > 0:
                f = d1 ** ((t - prev) / DAY)
                num *= f
                den *= f
            prev = t
            if nv > 0:
                if nw > 0:
                    num += nw
                else:                              # 단가 불명 — 현재 평단으로 채워 유지
                    num += nv * (num / den) if den > 0 else 0.0
                den += nv
                pos += nv
            elif pos > 0:
                sold = min(-nv, pos)
                r = 1.0 - sold / pos
                num *= r
                den *= r
                pos -= sold
                if pos <= 0:
                    pos = num = den = 0.0
        if den > 0 and num > 0:
            out[k] = num / den
    return out


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
    codes = sorted(flow["code"].unique())
    print(f"  수급 {len(flow):,}행 · 종목 {len(codes):,}개")

    px = page_by_month("stock_daily", "code,dt,close,shares", lo, hi)
    px["dt"] = pd.to_datetime(px["dt"])
    px = px[px["code"].isin(set(codes))]      # 수급이 있는 종목만 — 나머지는 어차피 안 쓴다
    for c in ("close", "shares"):
        px[c] = pd.to_numeric(px[c], errors="coerce")
    px = px[px["close"] > 0].sort_values(["code", "dt"])

    # 분할 보정 — stock_daily는 수정주가가 아니다. 가격은 배율 f로 낮추고 순매수 '수량'은
    # 그 역수로 늘려야 같은 단위가 된다(대금은 분할과 무관). holders.py 헤더 27~28행과 같은 규칙.
    # 빼먹으면 den에 분할 전 주수와 분할 후 주수가 섞여 더해져 평단이 분할비만큼 통째로 어긋난다
    # (실측: LS ELECTRIC 5:1 분할 후 기타법인 CGO -17.4% ← 실제 +22.6%).
    fadj, events = {}, []
    for c, g in px.groupby("code", sort=False):
        d = g[g["shares"] > 0].set_index("dt")[["close", "shares"]]
        if len(d) < 2:
            continue
        f, ev = vp.split_adjust(d)
        if (f != 1.0).any():
            fadj[c] = pd.Series(f, index=d.index)
            events += [f"{c} {e}" for e in ev]
    px["f"] = 1.0
    for c, s in fadj.items():
        m = px["code"] == c
        px.loc[m, "f"] = s.reindex(px.loc[m, "dt"]).ffill().bfill().fillna(1.0).to_numpy()
    px["close"] = px["close"] * px["f"]
    close = px.pivot_table(index="dt", columns="code", values="close")
    print(f"  시세 {len(px):,}행 · 거래일 {len(close):,}일 · 분할 보정 {len(fadj)}종목")
    for e in events:
        print(f"    {e}")

    # (code, inv)별 날짜순 vol/val 배열 — cost_series가 한 번에 훑는다
    flow = flow.sort_values("dt")
    flow["vol"] = pd.to_numeric(flow["vol"], errors="coerce").astype(float)
    flow["val"] = pd.to_numeric(flow["val"], errors="coerce").astype(float)
    for c, s in fadj.items():                      # 수량만 같은 단위로 (대금은 그대로)
        m = flow["code"] == c
        if m.any():
            f = s.reindex(flow.loc[m, "dt"]).ffill().bfill().fillna(1.0).to_numpy()
            flow.loc[m, "vol"] = flow.loc[m, "vol"].to_numpy() / f
    grp = {k: (g["dt"].to_numpy(), g["vol"].to_numpy(dtype=float), g["val"].to_numpy(dtype=float))
           for k, g in flow.groupby(["code", "inv"])}

    recs = []
    for hl in HALFLIVES:
        # 반감기만큼은 예열해야 무게가 실린다 — 그 전 구간은 평단이 얕아 값이 튄다
        first = pd.Timestamp(lo) + pd.Timedelta(days=hl)
        days = pd.DatetimeIndex([d for d in close.index if d >= first])
        if len(days) == 0:
            print(f"  [반감기 {hl}일] 예열 구간을 못 넘김 — 건너뜀")
            continue
        print(f"  [반감기 {hl}일] {days[0].date()} ~ {days[-1].date()} ({len(days)}일) 계산 중...", flush=True)

        for t in TYPES:
            cols = {}
            for c in codes:
                g = grp.get((c, t))
                if g is None:
                    continue
                s = cost_series(g[0], g[1], g[2], days, hl)
                if np.isfinite(s).any():
                    cols[c] = s
            if not cols:
                continue
            cost = pd.DataFrame(cols, index=days)
            p = close.reindex(index=days, columns=cost.columns)
            cgo = (p / cost * 100 - 100).where(p > 0).replace([np.inf, -np.inf], np.nan)

            # ⚠️ 그날그날 있는 종목만 모아 중앙값을 내면 안 된다. 주체의 포지션이 0이 되면
            #    그 종목이 표본에서 빠지는데, 매일 20~30개가 들락거려 중앙값이 '가격'이 아니라
            #    '표본 구성'으로 움직인다(실측: 5거래일에 18%p 점프).
            #    → ① 고정 유니버스(관측률 70%↑)로 묶고 ② 일시 이탈은 직전값으로 이어 붙인다.
            keep = cgo.columns[cgo.notna().mean() >= 0.70]
            cgo = cgo[keep].ffill(limit=20)
            for d, row in cgo.iterrows():
                a = row.to_numpy(dtype=float)
                a = a[np.isfinite(a)]
                if len(a) < 30:          # 종목 30개 미만이면 시장 요약으로 못 쓴다
                    continue
                recs.append({"dt": d.strftime("%Y-%m-%d"), "hl_days": hl, "inv": t,
                             "n_stocks": int(len(a)),
                             "cgo_med": round(float(np.median(a)), 2),
                             "cgo_avg": round(float(a.mean()), 2),
                             "under_pct": round(float((a < 0).mean() * 100), 1),
                             "deep_pct": round(float((a < DEEP).mean() * 100), 1)})

    if not recs:
        print("계산 결과 없음 — 원자료 기간이 예열 구간보다 짧습니다.")
        return
    out = pd.DataFrame(recs)
    print(f"\n계산 완료: {len(out):,}행")
    last = out[out["dt"] == out["dt"].max()].sort_values("cgo_med")
    print(f"\n최신 {out['dt'].max()} — 주체별 미실현손익")
    print(last[["hl_days", "inv", "n_stocks", "cgo_med", "under_pct", "deep_pct"]].to_string(index=False))

    # 일간 변동 점검. 큰 값이 곧 버그는 아니다 — 이 폭은 대부분 그날 지수 등락이 만든다.
    # (평단은 하루 0.02% 수준으로만 움직인다. 이상하면 평단이 아니라 지수부터 확인할 것.)
    print("\n일간 변동 — 반감기별·주체별 (대부분 지수 등락분이다)")
    for hl in sorted(out["hl_days"].unique()):
        for t in TYPES:
            s = out[(out["hl_days"] == hl) & (out["inv"] == t)].sort_values("dt")
            if len(s) < 3:
                continue
            j = s["cgo_med"].diff().abs()
            k = j.idxmax()
            print(f"  hl={hl:3d} {t:6s} 최대 {j.max():5.1f}%p ({s.loc[k, 'dt']}) · "
                  f"평균 {j.mean():4.2f}%p · 1%p 초과 {int((j > 1).sum())}일/{len(s)}일")

    ind = out[(out["inv"] == "개인") & (out["hl_days"] == 365)].sort_values("dt")
    if len(ind) > 5:
        cur = ind["cgo_med"].iloc[-1]
        print(f"\n개인(반감기 365일) 추이: 최저 {ind['cgo_med'].min():+.1f}% "
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
        sb.table("cgo_daily").upsert(rows[i:i + 1000], on_conflict="dt,hl_days,inv").execute()
    print(f"cgo_daily 적재 완료: {len(rows):,}행")


if __name__ == "__main__":
    main()
