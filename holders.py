# holders.py — 주체별(개인·외국인·기관·기타법인) '실측' 매물대 → Supabase holder_profile
#   crossval.py의 B측(투자자 순매수 실측)을 대시보드 기능으로 만든 것. volume_profile이
#   감쇠 '모델'의 추정이라면 이건 KRX 집계 순매수의 누적 실측이라 감쇠 가정이 없다.
#   순매수일엔 그날 고가~저가에 길이 비례로 쌓고, 순매도일엔 그 주체 보유분에서 비례로 뺀다.
#
#   데이터 흐름: pykrx(정보데이터시스템, KRX_ID/PW 로그인) → investor_flow(일별 순매수 캐시,
#   증분 수집) → 창(91/182/365/730일)별 보유분포 계산 → holder_profile (웹이 읽음).
#   캐시 덕에 매일 종목당 pykrx 호출 2번(수량+대금)이면 된다 — 스크래핑 부하 방어.
#
#   분할 보정: 가격은 stock_daily 기준 split_adjust로 낮추므로, 순매수 '수량'은 그 역수로
#   늘려야 같은 단위가 된다(대금은 불변). 이걸 빼먹으면 분할 종목의 평단·분포가 어긋난다.
#
#   한계(화면에도 명시): 창 구간 순매수만 보인다(창 이전 보유 없음) · 같은 주체 안 손바뀜
#   (개인↔개인)은 안 잡힌다 · 창 내내 순매도인 주체는 보유 0 · KRX 정규장 기준.
#
#   사용: python holders.py                → 시총 상위 50 + SCREENER_ALWAYS, 증분 수집+적재 (크론용)
#         python holders.py 005930        → 특정 종목만
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
# 크론에 KRX_ID/PW 시크릿이 없으면 조용히 통과 — 다른 갱신 스텝을 막지 않는다(krx.py 프록시 패턴).
if not (os.environ.get("KRX_ID") and os.environ.get("KRX_PW")):
    print("KRX_ID/KRX_PW 없음 — 주체별 실측(holder_profile) 수집 건너뜀")
    sys.exit(0)

import profile as vp             # noqa: E402  Supabase 클라이언트·페이저·split_adjust 재사용
import crossval as cv            # noqa: E402  holdings_profile·avg_cost 재사용 (B측 로직의 원본)
from pykrx import stock          # noqa: E402

WINDOWS = [91, 182, 365, 730]    # 실측은 창 이전 보유를 모르므로 짧은 창이 본질에 더 맞다
NBINS = 60                       # volume_profile 종목과 같은 해상도
BACKFILL_DAYS = 745              # 최장 창(730) + 여유 — 첫 실행 때 이만큼 pykrx에서 백필
TOP_N = 50                       # 시총 상위 N종목만 — 스크래핑이라 전 종목은 부하·차단 위험


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
        a, b = f.strftime("%Y%m%d"), t.strftime("%Y%m%d")
        expected = ((trading_days >= f) & (trading_days <= t)).sum()
        vol = val = None
        for attempt in range(4):
            if attempt:
                time.sleep(2 * attempt ** 2)      # 2·8·18초 — 레이트리밋은 잠깐 쉬면 풀린다
            vol = stock.get_market_trading_volume_by_date(a, b, code)
            val = stock.get_market_trading_value_by_date(a, b, code)
            if len(vol) and len(val):
                break
        if not (len(vol) and len(val)):
            if expected:
                raise RuntimeError(f"{a}~{b} 수집 실패 (거래일 {expected}일인데 빈 응답)")
            vol = val = None                      # 상장 전 구간 — 비는 게 맞다
        if vol is not None:
            vs.append(vol)
            ws.append(val)
        f = t + pd.Timedelta(days=1)
        time.sleep(0.6)                           # 정보데이터시스템 예의 — 연속 타격 방지
    if not vs:
        raise RuntimeError("전 구간 빈 응답")
    vol, val = pd.concat(vs), pd.concat(ws)
    return vol[~vol.index.duplicated()], val[~val.index.duplicated()]


def sync_flows(code, dry, trading_days):
    """캐시 + 빠진 구간만 pykrx로 증분 수집 → (수량 wide, 대금 wide). 새 행은 DB에 upsert."""
    cache = cached_flows(code)
    today = pd.Timestamp.today().normalize()
    start = today - pd.Timedelta(days=BACKFILL_DAYS)
    if not cache.empty:
        start = max(start, cache["dt"].max() + pd.Timedelta(days=1))
    new_rows = []
    if start <= today:
        vol, val = fetch_krx(code, start, today, trading_days)
        for dt, r in vol.iterrows():
            for t in cv.TYPES:
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
    volw = allf.pivot(index="dt", columns="inv", values="vol").reindex(columns=cv.TYPES).fillna(0)
    valw = allf.pivot(index="dt", columns="inv", values="val").reindex(columns=cv.TYPES).fillna(0)
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
        _tot, inv = cv.holdings_profile(vol, dfw["Low"].to_numpy(), dfw["High"].to_numpy(), edges)
        tsum = sum(a.sum() for a in inv.values())
        if tsum <= 0:
            continue
        costs = cv.avg_cost(vol, val)
        for t in cv.TYPES:
            arr, (pos_c, cost) = inv[t], costs[t]
            pos = float(arr.sum())
            ac = round(float(cost), 2) if (pos_c > 0 and cost > 0) else None
            for b in range(NBINS):
                out.append({"code": code, "win_days": win, "inv": t,
                            "bin_lo": round(float(edges[b]), 4),
                            "bin_hi": round(float(edges[b + 1]), 4),
                            "qty": round(float(arr[b]), 2),
                            "share": round(float(arr[b] / tsum * 100), 4),
                            "pos_qty": round(pos, 2), "avg_cost": ac,
                            "px": px, "dt": last_dt})
    return out, px


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
    """--dry 검증용 콘솔 요약: 창별 주체 보유·평단·평가손익."""
    print(f"\n=== {name}({code}) — 현재가 {px:,.0f} ===")
    for win in WINDOWS:
        rs = [r for r in rows if r["win_days"] == win]
        if not rs:
            continue
        parts = []
        for t in cv.TYPES:
            tr = next((r for r in rs if r["inv"] == t), None)
            if not tr or tr["pos_qty"] <= 0:
                parts.append(f"{t.replace('합계', '')} 순매도")
                continue
            pl = f" ({px / tr['avg_cost'] * 100 - 100:+.1f}%)" if tr["avg_cost"] else ""
            parts.append(f"{t.replace('합계', '')} {tr['pos_qty'] / 1e6:.1f}백만주"
                         f" 평단 {tr['avg_cost']:,.0f}{pl}" if tr["avg_cost"]
                         else f"{t.replace('합계', '')} {tr['pos_qty'] / 1e6:.1f}백만주")
        print(f"  [{win:>3}일] " + " · ".join(parts))


if __name__ == "__main__":
    dry = "--dry" in sys.argv
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    tg = [(c, c) for c in args] if args else targets()
    batch_rows, batch_codes, done, failed = [], [], 0, []
    for code, name in tg:
        try:
            # 가격을 먼저 받는다 — 거래일 목록이 있어야 '빈 응답'이 수집 실패인지 상장 전인지 가른다
            df, events = load_price(code, max(WINDOWS) + 20)
            if len(df) < 60:
                print(f"{name}({code}): 가격 데이터 부족({len(df)}일) — 건너뜀")
                continue
            volw, valw, n_new = sync_flows(code, dry, df.index)
            if volw is None:
                print(f"{name}({code}): 순매수 데이터 없음 — 건너뜀")
                continue
            rows, px = compute(code, df, volw, valw)
            if not rows:
                print(f"{name}({code}): 보유 물량 0 — 건너뜀")
                continue
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
