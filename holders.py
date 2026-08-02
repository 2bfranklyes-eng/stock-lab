# holders.py — 주체별(개인·외국인·기관·기타법인) 순매수 누적 매물대 → Supabase holder_profile
#   volume_profile이 '전체 거래량 + 감쇠 모델'의 추정이라면, 이건 KRX가 집계한 주체별
#   순매수(실측)를 누적한다. 순매수일엔 그날 고가~저가에 길이 비례로 쌓는다.
#
#   ⚠️ 다만 순매도일 배분에는 가정이 남는다 — '그 주체 보유분 전체에서 비례로 판다'
#   (G&H 비례 소진과 같은 형태를 주체별로 적용한 것). 그리고 판 게 산 것보다 많아지면
#   0에서 다시 센다(창 이전 보유를 모르므로 음수 포지션을 둘 수 없다). 그래서:
#     · pos_qty(잔량) = 창 안에서 사서 아직 안 판 추정치 — 보유 지분이 아니다.
#       0 리셋 정도가 주체마다 달라 주체 간 크기 비교로도 못 쓴다.
#     · net_qty(창 전체 단순 순매수 합) = 리셋 없는 값 — '기간에 실제로 늘었나 줄었나'는 이걸 본다.
#       (외국인이 1년 내내 판 종목은 잔량만 보면 '물량 적음'으로 오독된다 — 실사용에서 나온 사례)
#
#   데이터 흐름: pykrx(정보데이터시스템, KRX_ID/PW 로그인) → investor_flow(일별 순매수 캐시,
#   증분 수집) → 창(91/182/365/730일)별 보유분포 계산 → holder_profile (웹이 읽음).
#   pykrx는 '임포트 시점에' KRX 로그인을 시도하므로 지연 임포트한다 — 로그인이 차단돼도
#   빠진 거래일이 없는 종목(주말 재계산 등)은 캐시만으로 끝까지 돈다.
#
#   ⚡ 수집 경로가 둘이다 — 싼 쪽을 골라 쓴다:
#     · 일일 증분 = 벌크([12010] 투자자별 순매수상위종목). 한 번 호출에 그 시장 '전 종목'
#       하루치가 온다. 시장2 × 투자자5 = 10회면 코스피+코스닥 전부 — 비용이 종목수와 무관.
#       (종목별로 받으면 200종목 × 2회 = 400회/일. 이게 예전에 로그인 차단을 부른 부하다.)
#     · 신규 종목 백필 = 종목별([12009]). 한 종목 745일치가 6회면 끝나는데, 같은 걸 벌크로
#       하면 494거래일 × 10회 = 4,940회다. 날짜수가 많고 종목수가 적을 땐 종목별이 싸다.
#   두 경로 값이 같음은 확인했다(코스피·코스닥, 4주체, 과거일 포함 전부 일치).
#   단 벌크엔 '외국인합계'가 없어 외국인 + 기타외국인을 더해야 종목별과 같아진다.
#
#   분할 보정: 가격은 stock_daily 기준 split_adjust로 낮추므로, 순매수 '수량'은 그 역수로
#   늘려야 같은 단위가 된다(대금은 불변). 이걸 빼먹으면 분할 종목의 평단·분포가 어긋난다.
#
#   사용: python holders.py                → 시총 상위 200 + SCREENER_ALWAYS, 증분 수집+적재 (크론용)
#         python holders.py 005930        → 특정 종목만 (벌크 생략, 종목별 경로만)
#         python holders.py 005930 --dry  → 적재 없이 콘솔 요약만 (검증용)
import os
import sys
import time
import numpy as np
import pandas as pd
from dotenv import load_dotenv

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

load_dotenv()
import profile as vp             # noqa: E402  Supabase 클라이언트·페이저·split_adjust 재사용

WINDOWS = [91, 182, 365, 730]    # 실측은 창 이전 보유를 모르므로 짧은 창이 본질에 더 맞다
NBINS = 60                       # volume_profile 종목과 같은 해상도
BACKFILL_DAYS = 745              # 최장 창(730) + 여유 — 첫 실행 때 이만큼 pykrx에서 백필
# 상한을 정하는 건 이제 KRX 부하가 아니라 Supabase 무료 티어다 — 벌크 전환으로 호출은
# 종목수와 무관해졌지만, 저장은 종목당 약 440KB(holder_profile 960행 + investor_flow 1,976행)
# 씩 늘고 크론이 매일 그만큼 읽는다. 200종목 ≈ 저장 88MB · egress 0.8GB/월로 500MB·5GB 안에 든다.
TOP_N = 200
NEW_PER_RUN = 40                 # 한 실행에서 새로 백필할 종목 수 상한 — 나머지는 다음 크론이 이어받는다.
                                 # 162종목을 한 번에 훑다 차단당하느니 나흘에 나눠 받는다.

# ── 주체별 보유분포 코어 (crossval.py에서 이관 — 연구 스크립트가 여기서 임포트한다) ──
# production(이 파일)이 본체인 이유: crossval은 pykrx를 모듈 임포트 시점에 불러 로그인이
# 막히면 통째로 죽는다. 코어가 여기 있으면 캐시 재계산 경로는 pykrx 없이도 돈다.
TYPES = ["기관합계", "기타법인", "개인", "외국인합계"]


def day_spread(v, l, h, edges):
    """하루치 수량을 고가~저가에 길이 비례로 배분."""
    bin_lo, bin_hi = edges[:-1], edges[1:]
    frac = np.clip(np.minimum(h, bin_hi) - np.maximum(l, bin_lo), 0, None) / max(h - l, 1e-9)
    s = frac.sum()
    return v * frac / s if s > 0 else np.zeros(len(bin_lo))


def holdings_profile(vol, lows, highs, edges):
    """주체별로 '지금 들고 있는 물량이 어느 가격대에서 샀는가'를 만든다.
    순매수일엔 그날 가격대에 쌓고, 순매도일엔 그 주체가 이미 가진 물량에서 비례로 뺀다.
    (누적 순매수를 그냥 더하면 샀다 판 물량이 남아 실제 보유보다 부풀려진다)
    포지션이 음수로 가면 0에서 끊는다 — 창 이전 보유를 모르니 빌려줄 재고가 없다."""
    inv = {t: np.zeros(len(edges) - 1) for t in TYPES}
    for i in range(len(lows)):
        for t in TYPES:
            nv = vol[t].iloc[i]
            if nv > 0:
                inv[t] += day_spread(nv, lows[i], highs[i], edges)
            elif nv < 0:
                held = inv[t].sum()
                if held > 0:
                    inv[t] *= max(0.0, 1 + nv / held)
    return sum(inv.values()), inv


def avg_cost(vol, val):
    """주체별 이동평균 매입단가 — 순매수일엔 평단을 갱신하고, 순매도일엔 수량만 줄인다.
    (매도는 평단을 바꾸지 않는 평균원가법. 포지션이 음수로 가면 그 주체는 순매도자다.)
    수량은 +인데 대금이 −인 날(장중 싸게 사고 비싸게 판 날)은 단가를 알 수 없으므로
    수량만 더하고 평단은 안 건드린다 — 음수 단가가 평균에 섞이는 오염 방지."""
    out = {}
    for t in TYPES:
        pos = cost = 0.0
        for nv, nval in zip(vol[t], val[t]):
            if nv > 0 and nval > 0:
                px = nval / nv                       # 그날 그 주체의 실제 순매수 평균가
                cost = (pos * cost + nv * px) / (pos + nv)
                pos += nv
            elif nv > 0:
                pos += nv                            # 단가 불명 — 평단 유지
            else:
                pos += nv                            # 음수 더하기 = 감소
                if pos <= 0:
                    pos, cost = 0.0, 0.0             # 다 팔았으면 평단 리셋
        out[t] = (pos, cost)
    return out


# ── 데이터 적재 ──────────────────────────────────────────────────────────
_PYKRX = None                    # 로그인 실패를 기억해 같은 실행에서 재시도로 차단을 키우지 않는다


def krx():
    """pykrx 지연 임포트. 임포트 = 로그인 시도라서, 실제로 받아올 게 있을 때만 부른다."""
    global _PYKRX
    if _PYKRX == "blocked":
        raise RuntimeError("KRX 로그인 차단 상태 — 이번 실행에선 재시도 안 함")
    if _PYKRX is None:
        try:
            from pykrx import stock
        except Exception as e:
            _PYKRX = "blocked"
            raise RuntimeError(f"pykrx 로그인 실패({type(e).__name__}) — 잠시 후 다시") from e
        _PYKRX = stock
    return _PYKRX


def load_price(code, win_days):
    """crossval.load_price와 같되 일별 분할배율(fadj)을 남긴다 — 수량 보정에 필요해서."""
    rows = vp.page("stock_daily", "dt,high,low,close,tval,shares,mktcap", code=code)
    df = pd.DataFrame(rows)
    if df.empty:
        return df, []
    df["dt"] = pd.to_datetime(df["dt"])
    df = df.set_index("dt").astype(float)
    df = df[(df["close"] > 0) & (df["high"] > 0) & (df["mktcap"] > 0)]
    if df.empty:
        return df, []
    f, events = vp.split_adjust(df)
    for c in ("high", "low", "close"):
        df[c] = df[c] * f
    df["fadj"] = f
    df = df.rename(columns={"high": "High", "low": "Low", "close": "Close"})
    return df[df.index >= df.index[-1] - pd.Timedelta(days=win_days)], events


def cached_flows(code):
    """investor_flow에 이미 쌓인 순매수. 테이블이 없거나 비어 있으면 빈 프레임."""
    out, start = [], 0
    try:
        while True:
            r = (vp.client().table("investor_flow").select("dt,inv,vol,val")
                 .eq("code", code).order("dt").order("inv")
                 .range(start, start + 999).execute().data) or []
            out += r
            if len(r) < 1000:
                break
            start += 1000
    except Exception as e:
        print(f"  (investor_flow 조회 실패 — 캐시 없이 진행: {e})")
        return pd.DataFrame()
    if not out:
        return pd.DataFrame()
    df = pd.DataFrame(out)
    df["dt"] = pd.to_datetime(df["dt"])
    return df


def fetch_krx(code, frm, to, trading_days):
    """pykrx 투자자별 순매수 수량+대금. 창이 길면 응답이 잘릴 수 있어 1년 단위로 나눠 받는다.
    ⚠️ pykrx는 KRX가 HTML 에러페이지를 주면 예외를 삼키고 '빈 DataFrame'을 돌려준다 —
    그대로 두면 '수집 실패'가 '순매수 없음'으로 둔갑해 반쪽 데이터가 조용히 적재된다.
    그래서 빈 청크는 재시도하고, 그 구간에 실제 거래일이 있었는데도 계속 비면 예외를 던져
    이 종목을 통째로 건너뛰게 한다(부분 적재 금지). 거래일이 없으면(상장 전) 빈 게 정상."""
    vs, ws = [], []
    f, end = pd.Timestamp(frm), pd.Timestamp(to)
    while f <= end:
        t = min(f + pd.Timedelta(days=364), end)
        expected = ((trading_days >= f) & (trading_days <= t)).sum()
        if not expected:                          # 거래일 없는 청크(주말·상장 전) — pykrx 안 부름
            f = t + pd.Timedelta(days=1)
            continue
        a, b = f.strftime("%Y%m%d"), t.strftime("%Y%m%d")
        vol = val = None
        for attempt in range(4):
            if attempt:
                time.sleep(2 * attempt ** 2)      # 2·8·18초 — 레이트리밋은 잠깐 쉬면 풀린다
            vol = krx().get_market_trading_volume_by_date(a, b, code)
            val = krx().get_market_trading_value_by_date(a, b, code)
            if len(vol) and len(val):
                break
        if not (len(vol) and len(val)):
            raise RuntimeError(f"{a}~{b} 수집 실패 (거래일 {expected}일인데 빈 응답)")
        vs.append(vol)
        ws.append(val)
        f = t + pd.Timedelta(days=1)
        time.sleep(0.6)                           # 정보데이터시스템 예의 — 연속 타격 방지
    if not vs:
        return None, None
    vol, val = pd.concat(vs), pd.concat(ws)
    return vol[~vol.index.duplicated()], val[~val.index.duplicated()]


# ── 벌크 경로: 하루 10회 호출로 전 종목 ──────────────────────────────────
# 벌크엔 '외국인합계' 항목이 없다 — 외국인(9000) + 기타외국인(9001)을 더해야 종목별과 일치한다.
BULK_INV = {"기관합계": ("기관합계",), "기타법인": ("기타법인",),
            "개인": ("개인",), "외국인합계": ("외국인", "기타외국인")}
MARKETS = ("KOSPI", "KOSDAQ")
BULK_MAX_DAYS = 20               # 오래 멈춘 뒤 재개하면 날짜×10회가 커진다 — 그쯤부턴 종목별이 싸다
MIN_CODES = 1000                 # 거래일이면 코스피+코스닥 2,600여 종목이 온다 — 이보다 적으면 반쪽 응답


def bulk_day(d):
    """하루치 전 종목 주체별 순매수 → {code: {inv: [vol, val]}}. 시장2 × 투자자5 = 10회.
    fetch_krx와 같은 이유로 빈 응답을 재시도한다 — pykrx는 KRX가 에러페이지를 주면 예외를
    삼키고 빈 DataFrame을 돌려주므로, 그냥 두면 '수집 실패'가 '순매수 0'으로 둔갑해 조용히
    적재된다. 여기선 종목이 한꺼번에 걸려 있어 피해가 더 크다."""
    out = {}
    for market in MARKETS:
        for t, parts in BULK_INV.items():
            for p in parts:
                df = None
                for attempt in range(4):
                    if attempt:
                        time.sleep(2 * attempt ** 2)     # 2·8·18초 — 레이트리밋은 잠깐 쉬면 풀린다
                    df = krx().get_market_net_purchases_of_equities(d, d, market, p)
                    if len(df):
                        break
                if not len(df):
                    raise RuntimeError(f"{d} {market}/{p} 빈 응답 — 이 날은 건너뜁니다")
                time.sleep(0.3)                   # 정보데이터시스템 예의 — 연속 타격 방지
                for code, r in df.iterrows():
                    cell = out.setdefault(code, {}).setdefault(t, [0.0, 0.0])
                    cell[0] += float(r["순매수거래량"])
                    cell[1] += float(r["순매수거래대금"])
    if len(out) < MIN_CODES:
        raise RuntimeError(f"{d} 응답 {len(out)}종목뿐 — 반쪽 데이터로 보고 적재하지 않습니다")
    return out


def market_calendar():
    """시장 거래일 달력 — 삼성전자 일봉을 쓴다(거래정지가 없어 빠진 날이 곧 휴장일)."""
    rows = vp.page("stock_daily", "dt", code="005930")
    return pd.DatetimeIndex(sorted(pd.to_datetime([r["dt"] for r in rows])))


def bulk_fill(codes, dry):
    """캐시가 끝난 날 다음부터 오늘까지를 벌크로 채운다. 대상 종목이 한꺼번에 채워지므로
    이 뒤의 종목별 루프는 대부분 pykrx를 아예 안 부른다.
    ⚠️ 응답엔 코스피+코스닥 2,600여 종목이 다 오지만 대상(codes)만 저장한다 — 전부 넣으면
    하루 1만 행씩 쌓여 무료 티어가 금방 찬다. 커버리지를 정하는 건 TOP_N이지 응답 크기가 아니다.
    investor_flow의 전역 max(dt)를 기준으로 삼는 게 성립하는 이유: 벌크는 항상 '그날 대상 전부'를
    쓰므로, 마지막 적재일 = 마지막으로 벌크가 훑은 날이다."""
    r = (vp.client().table("investor_flow").select("dt")
         .order("dt", desc=True).limit(1).execute().data) or []
    if not r:
        print("investor_flow가 비어 있음 — 벌크 생략, 종목별 백필로 채웁니다")
        return 0
    last = pd.Timestamp(r[0]["dt"])
    today = pd.Timestamp.today().normalize()
    days = [d for d in market_calendar() if last < d <= today]
    if not days:
        print(f"벌크 증분 없음 (캐시 최신일 {last:%Y-%m-%d})")
        return 0
    if len(days) > BULK_MAX_DAYS:
        print(f"⚠️ 빠진 거래일 {len(days)}일 — 최근 {BULK_MAX_DAYS}일만 벌크로. "
              "나머지는 종목별 백필이 메웁니다")
        days = days[-BULK_MAX_DAYS:]
    want, rows, ok = set(codes), [], 0
    for d in days:
        # 한 날이 실패하면 거기서 멈춘다 — 건너뛰고 뒷날을 쓰면 max(dt)가 그 날을 지나쳐
        # 구멍이 영구히 남는다. 여기서 끊으면 다음 실행이 실패한 날부터 다시 받는다.
        try:
            got = bulk_day(d.strftime("%Y%m%d"))
        except Exception as e:
            print(f"  벌크 {d:%Y-%m-%d} 중단: {e}")
            break
        hit = want & got.keys()
        for code in hit:
            for t, (v, w) in got[code].items():
                rows.append({"code": code, "dt": d.strftime("%Y-%m-%d"),
                             "inv": t, "vol": v, "val": w})
        ok += 1
        print(f"  벌크 {d:%Y-%m-%d}: 응답 {len(got)}종목 중 대상 {len(hit)}종목")
    if rows and not dry:
        for i in range(0, len(rows), 1000):
            vp.client().table("investor_flow").upsert(rows[i:i + 1000]).execute()
    print(f"벌크 수집: {ok}/{len(days)}거래일 · {ok * 10}회 호출 · {len(rows):,}행"
          + ("" if ok == len(days) else " (나머지는 다음 실행에서)"))
    return len(rows)


def sync_flows(code, dry, trading_days, allow_fetch=True):
    """캐시 + 빠진 구간만 pykrx로 증분 수집 → (수량 wide, 대금 wide). 새 행은 DB에 upsert.
    allow_fetch=False면 종목별 호출이 필요한 시점에 멈춘다 — 한 실행의 백필량을 묶는 손잡이."""
    cache = cached_flows(code)
    today = pd.Timestamp.today().normalize()
    start = today - pd.Timedelta(days=BACKFILL_DAYS)
    # max(dt)만 보고 '최신'이라 판단하면 안 된다 — 벌크는 최근 며칠만 쓰므로, 신규 종목은
    # 캐시 뒤쪽만 차고 앞이 텅 빈 채로 '오늘까지 있음'처럼 보인다. 앞도 덮였는지 같이 본다.
    # (기준은 그 종목 자신의 첫 거래일 — 최근 상장주는 앞이 비는 게 정상이라 오판하면 안 된다)
    if not cache.empty and cache["dt"].min() <= trading_days[0] + pd.Timedelta(days=15):
        start = max(start, cache["dt"].max() + pd.Timedelta(days=1))
    new_rows = []
    # 빠진 '거래일'이 실제로 있을 때만 pykrx를 부른다 — 주말·휴일 재실행은 캐시만으로 돈다
    if len(trading_days[(trading_days >= start) & (trading_days <= today)]):
        if not allow_fetch:
            return None, None, -1                 # 이번 실행 백필 정원 초과 — 다음 크론에 넘긴다
        vol, val = fetch_krx(code, start, today, trading_days)
        if vol is not None:
            for dt, r in vol.iterrows():
                for t in TYPES:
                    if t not in vol.columns:
                        continue
                    v = float(r[t])
                    w = float(val.at[dt, t]) if (dt in val.index and t in val.columns) else 0.0
                    new_rows.append({"code": code, "dt": dt.strftime("%Y-%m-%d"),
                                     "inv": t, "vol": v, "val": w})
    if new_rows and not dry:
        for i in range(0, len(new_rows), 1000):
            vp.client().table("investor_flow").upsert(new_rows[i:i + 1000]).execute()
    add = pd.DataFrame(new_rows)
    if not add.empty:
        add["dt"] = pd.to_datetime(add["dt"])
    allf = pd.concat([f for f in (cache, add) if not f.empty], ignore_index=True) \
        if (not cache.empty or not add.empty) else pd.DataFrame()
    if allf.empty:
        return None, None, 0
    allf = allf.drop_duplicates(["dt", "inv"], keep="last")
    volw = allf.pivot(index="dt", columns="inv", values="vol").reindex(columns=TYPES).fillna(0)
    valw = allf.pivot(index="dt", columns="inv", values="val").reindex(columns=TYPES).fillna(0)
    return volw, valw, len(new_rows)


def compute(code, df, volw, valw):
    """창별 주체별 보유분포 → holder_profile 행 목록. 0인 구간도 넣는다 —
    프론트가 빈 구간을 메워 그리지 않아도 가격축이 균일해지도록(volume_profile과 같은 방식)."""
    px = float(df["Close"].iloc[-1])
    last_dt = df.index[-1].strftime("%Y-%m-%d")
    out = []
    for win in WINDOWS:
        dfw = df[df.index >= df.index[-1] - pd.Timedelta(days=win)]
        if len(dfw) < 20:
            continue
        vol = volw.reindex(dfw.index).fillna(0).div(dfw["fadj"], axis=0)   # 수량을 분할 보정 단위로
        val = valw.reindex(dfw.index).fillna(0)                            # 대금은 분할과 무관
        lo, hi = dfw["Low"].min(), dfw["High"].max()
        edges = np.linspace(lo, hi, NBINS + 1)
        _tot, inv = holdings_profile(vol, dfw["Low"].to_numpy(), dfw["High"].to_numpy(), edges)
        tsum = sum(a.sum() for a in inv.values())
        if tsum <= 0:
            continue
        costs = avg_cost(vol, val)
        for t in TYPES:
            arr, (pos_c, cost) = inv[t], costs[t]
            pos = float(arr.sum())
            net = float(vol[t].sum())            # 리셋 없는 창 전체 순매수 — 잔량과 다른 정보다
            ac = round(float(cost), 2) if (pos_c > 0 and cost > 0) else None
            for b in range(NBINS):
                out.append({"code": code, "win_days": win, "inv": t,
                            "bin_lo": round(float(edges[b]), 4),
                            "bin_hi": round(float(edges[b + 1]), 4),
                            "qty": round(float(arr[b]), 2),
                            "share": round(float(arr[b] / tsum * 100), 4),
                            "pos_qty": round(pos, 2), "net_qty": round(net, 2),
                            "avg_cost": ac, "px": px, "dt": last_dt})
    return out, px


def has_net_col():
    """net_qty 컬럼 존재 확인 — 마이그레이션 전이면 빼고 적재해 전체가 죽지 않게(크론 방어)."""
    try:
        vp.client().table("holder_profile").select("net_qty").limit(1).execute()
        return True
    except Exception:
        return False


def push(rows, codes):
    """구간 경계가 매일 달라져 upsert로는 잔재가 남는다 — 코드 단위로 지우고 새로 넣는다."""
    sb = vp.client()
    for i in range(0, len(codes), 100):
        sb.table("holder_profile").delete().in_("code", codes[i:i + 100]).execute()
    for i in range(0, len(rows), 1000):
        sb.table("holder_profile").insert(rows[i:i + 1000]).execute()


def targets():
    rows = (vp.client().table("vp_stocks").select("code,name")
            .order("marcap", desc=True).limit(TOP_N).execute().data) or []
    got = {r["code"]: r["name"] for r in rows}
    for c in (x.strip() for x in os.environ.get("SCREENER_ALWAYS", "").split(",")):
        if c and c not in got:
            got[c] = c                       # 관심종목 — 이름은 몰라도 수집은 한다
    return list(got.items())


def summarize(name, code, rows, px):
    """--dry 검증용 콘솔 요약: 창별 주체 잔량·기간순매수·평단."""
    print(f"\n=== {name}({code}) — 현재가 {px:,.0f} ===")
    for win in WINDOWS:
        rs = [r for r in rows if r["win_days"] == win]
        if not rs:
            continue
        parts = []
        for t in TYPES:
            tr = next((r for r in rs if r["inv"] == t), None)
            if not tr:
                continue
            short = t.replace("합계", "")
            net = f"{tr['net_qty'] / 1e6:+.1f}백만"
            if tr["pos_qty"] <= 0:
                parts.append(f"{short} 잔량0 (기간 {net})")
                continue
            pl = f" ({px / tr['avg_cost'] * 100 - 100:+.1f}%)" if tr["avg_cost"] else ""
            parts.append(f"{short} 잔량 {tr['pos_qty'] / 1e6:.1f}백만 (기간 {net})"
                         + (f" 평단 {tr['avg_cost']:,.0f}{pl}" if tr["avg_cost"] else ""))
        print(f"  [{win:>3}일] " + " · ".join(parts))


if __name__ == "__main__":
    # 크론에 KRX_ID/PW 시크릿이 없으면 조용히 통과 — 다른 갱신 스텝을 막지 않는다(krx.py 프록시 패턴).
    # (모듈 임포트 때가 아니라 여기서 검사한다 — crossval이 이 파일을 임포트하기 때문)
    if not (os.environ.get("KRX_ID") and os.environ.get("KRX_PW")):
        print("KRX_ID/KRX_PW 없음 — 주체별 순매수(holder_profile) 수집 건너뜀")
        sys.exit(0)
    dry = "--dry" in sys.argv
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    tg = [(c, c) for c in args] if args else targets()
    keep_net = dry or has_net_col()
    if not keep_net:
        print("⚠️ holder_profile에 net_qty 컬럼이 없음 — sql/holder_profile_add_net.sql 실행 필요. "
              "이번엔 net_qty 빼고 적재합니다.")
    # 전 종목 증분을 먼저 벌크로 끝낸다 — 종목별 루프가 pykrx를 부를 일이 신규 종목만 남는다.
    # 종목을 지정한 실행은 그 종목만 보므로 벌크(전 종목)를 돌릴 이유가 없다.
    if not args:
        try:
            bulk_fill([c for c, _ in tg], dry)
        except Exception as e:
            print(f"벌크 증분 실패 — 종목별 경로로 진행합니다: {e}")
    batch_rows, batch_codes, done, failed = [], [], 0, []
    budget, deferred = NEW_PER_RUN, []
    for code, name in tg:
        try:
            # 가격을 먼저 받는다 — 거래일 목록이 있어야 '빈 응답'이 수집 실패인지 상장 전인지 가른다
            df, events = load_price(code, max(WINDOWS) + 20)
            if len(df) < 60:
                print(f"{name}({code}): 가격 데이터 부족({len(df)}일) — 건너뜀")
                continue
            volw, valw, n_new = sync_flows(code, dry, df.index, allow_fetch=budget > 0)
            if n_new == -1:
                deferred.append(code)
                continue
            if n_new:
                budget -= 1                       # 종목별 호출을 쓴 종목만 정원에서 깐다
            if volw is None:
                print(f"{name}({code}): 순매수 데이터 없음 — 건너뜀")
                continue
            rows, px = compute(code, df, volw, valw)
            if not rows:
                print(f"{name}({code}): 보유 물량 0 — 건너뜀")
                continue
            if not keep_net:
                for r in rows:
                    r.pop("net_qty", None)
            for e in events:
                print(f"  ({name} 주가 보정: {e})")
            if dry:
                summarize(name, code, rows, px)
            else:
                batch_rows += rows
                batch_codes.append(code)
                if len(batch_codes) >= 25:   # 중간에 죽어도 그날 작업이 통째로 날아가지 않게
                    push(batch_rows, batch_codes)
                    done += len(batch_codes)
                    print(f"→ 적재 {done}종목 ({len(batch_rows)}행) — 마지막 {name}, 신규 순매수 {n_new}행")
                    batch_rows, batch_codes = [], []
        except Exception as e:
            failed.append(code)
            print(f"{name}({code}) 실패: {e}")
        time.sleep(1.0)
    if not dry and batch_codes:
        push(batch_rows, batch_codes)
        done += len(batch_codes)
    if not dry:
        print(f"\n완료: {done}종목 적재" + (f" · 실패 {len(failed)}: {','.join(failed)}" if failed else ""))
    if deferred:
        print(f"백필 대기 {len(deferred)}종목 (실행당 {NEW_PER_RUN}종목 상한) — 다음 크론이 이어받습니다: "
              + ",".join(deferred[:10]) + (" …" if len(deferred) > 10 else ""))
