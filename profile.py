# profile.py — 지수 매물대(Volume Profile) 추론: 일봉 OHLCV로 가격대별 '미소화 물량' 추정
#   1) 하루 거래량을 그날 고가~저가 구간에 길이 비례로 배분(표준 볼륨 프로파일).
#   2) Grinblatt & Han(2005) 참조가격 모델식 회전율 감쇠: 과거에 쌓인 물량이 매일
#      그날 회전율 V(t)만큼 비례 소진된다 — w(t-n) = V(t-n) × Π (1 - V(t-n+τ)).
#      급등락이 몇 달 반복되면 회전율 폭증 → 옛 물량이 빠르게 손바뀜된다는 직관의 정량화.
#      유통주식수를 못 구하므로 V(t) = 당일 거래량 ÷ 직전 250거래일 거래량 합
#      ('시장 전체가 1년에 약 1회전'이라는 자기보정 프록시)로 근사한다.
#   집계 구간을 5년~1개월 7개로 잘라 각각 계산 — '언제 쌓인 매물인지'를 분리해 본다.
#   한계: 지수는 합성물이라 개별 종목 매물대보다 느슨한 근사 / 야후 ^KS11 거래량은 KRX 기준
#   (NXT 미포함, 15%± 누락 가능) / 일봉이라 장중 배분은 균등 가정 / 파생·ETF 간접 노출 안 잡힘.
#   (pykrx 거래대금·시가총액은 KRX 로그인 필요라 보류 — KRX_ID/PW 확보 시 실제 회전율로 교체 가능)
#   사용: python profile.py kospi kosdaq          → 콘솔 요약 + PNG
#         python profile.py --push                → 전 지수 계산 → Supabase volume_profile (크론용)
#         python profile.py --stocks              → 워치리스트 개별종목 → volume_profile (크론용)
#         python profile.py --stocks 005930       → 특정 종목만
import sys
import numpy as np
import pandas as pd
import yfinance as yf

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

PRESETS = {"kospi": ("^KS11", "코스피"), "kosdaq": ("^KQ11", "코스닥"),
           "spx": ("^GSPC", "S&P500"), "nasdaq": ("^IXIC", "나스닥"), "dow": ("^DJI", "다우")}
WINDOWS = [("5년", 1825), ("3년", 1095), ("2년", 730), ("1년", 365),
           ("6개월", 182), ("3개월", 91), ("1개월", 30)]
# 한국은 krx.py가 진짜 회전율(거래대금÷시가총액)을 indicator_raw에 적재 — 있으면 그걸 쓴다.
REAL_TURN = {"kospi": "kr_turn_kospi", "kosdaq": "kr_turn_kosdaq"}


def turnover(df):
    """일별 회전율 프록시 V(t) — G&H의 (거래량÷유통주식수) 대용. 초기 구간은 중앙값으로 메움."""
    denom = df["Volume"].rolling(250, min_periods=60).sum().shift(1)
    v = (df["Volume"] / denom).clip(0, 0.2)          # 이상치(반감기 3일 미만급) 방어
    return v.fillna(v.median()).to_numpy()


_SB = None


def client():
    """Supabase 클라이언트(지연 생성) — 로컬 PNG 용도로는 안 쓰이므로 임포트도 미룬다."""
    global _SB
    if _SB is None:
        import os
        from dotenv import load_dotenv
        from supabase import create_client
        load_dotenv()
        _SB = create_client(os.environ["SUPABASE_URL"], os.environ["SUPABASE_SERVICE_KEY"])
    return _SB


def page(table, sel, **eq):
    """Supabase는 요청당 1000행 상한 — dt 순으로 이어 받는다."""
    rows, start = [], 0
    while True:
        q = client().table(table).select(sel)
        for k, v in eq.items():
            q = q.eq(k, v)
        r = q.order("dt").range(start, start + 999).execute().data
        rows += r
        if len(r) < 1000:
            break
        start += 1000
    return rows


def real_turnover(df, code):
    """KRX 실제 회전율을 날짜로 맞춰 얹는다. 없는 날(수집 전 구간·최신일)은 프록시로 메움.
    Supabase 접근 불가(키 없음 등)면 조용히 프록시 전체를 반환 — 로컬 PNG 용도 대비."""
    proxy = turnover(df)
    try:
        got = {x["dt"]: float(x["value"])
               for x in page("indicator_raw", "dt,value", market="KR", code=code)}
    except Exception as e:
        print(f"  (실제 회전율 조회 실패 — 프록시 사용: {e})")
        return proxy
    if not got:
        return proxy
    dts = df.index.strftime("%Y-%m-%d")
    v = np.array([got.get(d, np.nan) for d in dts])
    n_real = int((~np.isnan(v)).sum())
    v = np.where(np.isnan(v), proxy, np.clip(v, 0, 0.2))
    print(f"  (회전율: KRX 실제값 {n_real}일 + 프록시 {len(v) - n_real}일)")
    return v


def qty(df):
    """가격대에 뿌릴 가중치 = 거래'수량'. 매물대는 '몇 주가 물려 있나'라 수량이 맞다.
    거래대금을 그대로 쓰면 같은 돈도 주가가 낮을 땐 주식 수가 많다는 걸 놓쳐 고가 구간이
    부풀고, 거래량을 그대로 쓰면(지수) 저가주가 왜곡한다 → 거래대금÷당일 대표가로 통일한다.
    (KRX가 종목별 거래량을 주긴 하지만 지수엔 그 개념이 없어 이쪽이 두 경우에 다 맞는다)"""
    return df["tval"] / ((df["High"] + df["Low"] + df["Close"]) / 3)


def build(df, nbins, V, w):
    """일봉 + 회전율 + 가중치 배열 → (구간 경계, 미소화 추정 프로파일, 일별 '두께' 지표)."""
    lo, hi = df["Low"].min(), df["High"].max()
    edges = np.linspace(lo, hi, nbins + 1)
    bin_lo, bin_hi = edges[:-1], edges[1:]

    vb_days = []                             # 하루 거래수량을 고가~저가와 겹치는 구간에 배분
    for l, h, v in zip(df["Low"], df["High"], np.asarray(w)):
        if v <= 0:
            vb_days.append(None)
            continue
        span = max(h - l, 1e-9)
        frac = np.clip(np.minimum(h, bin_hi) - np.maximum(l, bin_lo), 0, None) / span
        vb_days.append(v * frac / max(frac.sum(), 1e-9))

    rem = np.zeros(nbins)                    # 미소화 추정(G&H 잔존 물량)
    thin = np.full(len(df), np.nan)          # 그날 지나간 구간의 '기존 물량 두께' (평균 대비 배율)
    for i, vb in enumerate(vb_days):
        rem *= 1 - V[i]                      # 모든 과거 코호트가 그날 회전율만큼 비례 소진
        if vb is None:
            continue
        touched = vb > 0
        base = rem[rem > 0].mean() if (rem > 0).any() else np.nan
        if base and touched.any():
            thin[i] = (vb[touched] * rem[touched]).sum() / vb[touched].sum() / base
        rem += vb
    return edges, rem, thin


def window_summary(label, edges, rem, px):
    """한 구간 요약 한 줄: 위/아래 물량 비율 + 최대 저항 매물대."""
    mid = (edges[:-1] + edges[1:]) / 2
    pct = rem / max(rem.sum(), 1e-9) * 100
    above = np.where(mid > px)[0]
    up = pct[above].sum()
    line = f"  {label:>4}: 위 {up:4.0f}% / 아래 {100-up:4.0f}%"
    if len(above) and pct[above].max() > 0:
        b = above[np.argmax(pct[above])]
        line += f" | 최대 저항 {edges[b]:,.0f}~{edges[b+1]:,.0f} (+{mid[b]/px*100-100:.1f}%, 잔존 {pct[b]:.1f}%)"
    else:
        line += " | 위쪽 매물 없음(신고가 영역)"
    print(line)


def hypothesis_check(df, thin):
    """가설 검증: 그날 지나간 구간이 얇을수록 |일간 수익률|이 큰가 (최근 250일)."""
    ret = df["Close"].pct_change().abs().to_numpy()
    m = ~np.isnan(thin) & ~np.isnan(ret)
    m[:-250] = False
    if m.sum() > 60:
        corr = np.corrcoef(thin[m], ret[m])[0, 1]
        r_thin = ret[m][np.argsort(thin[m])[:m.sum() // 5]].mean()
        r_thick = ret[m][np.argsort(thin[m])[-m.sum() // 5:]].mean()
        print(f"  [가설 검증·최근 250일] 두께↔|변동| 상관 {corr:+.2f} — "
              f"얇은 날 평균 |변동| {r_thin*100:.2f}% vs 두꺼운 날 {r_thick*100:.2f}%")


def draw(key, name, df, px, results):
    """왼쪽 5년 종가 차트 + 구간별 프로파일 (matplotlib은 로컬 전용이라 지연 임포트)."""
    import matplotlib.pyplot as plt
    plt.rcParams["font.family"] = "Malgun Gothic"
    plt.rcParams["axes.unicode_minus"] = False
    fig, axes = plt.subplots(1, 1 + len(results), figsize=(17, 6), sharey=True,
                             gridspec_kw={"width_ratios": [3] + [1] * len(results)})
    ax1 = axes[0]
    ax1.plot(df.index, df["Close"], color="#222", lw=.9)
    ax1.axhline(px, color="#d97706", lw=.8, ls="--")
    ax1.set_title(f"{name} 종가 (최근 5년)")
    for ax, (label, _days, edges, rem) in zip(axes[1:], results):
        mid = (edges[:-1] + edges[1:]) / 2
        color = np.where(mid > px, "#c0392b", "#2471a3")   # 위=잠재 저항 / 아래=지지
        ax.barh(mid, rem / rem.max(), height=np.diff(edges), color=color, alpha=.8)
        ax.axhline(px, color="#d97706", lw=.8, ls="--")
        ax.set_title(label, fontsize=10)
        ax.set_xticks([])
    fig.suptitle("매물대(미소화 추정) — 집계 구간별, 각 패널 max=1", y=1.0, fontsize=11)
    fig.tight_layout()
    fig.savefig(f"profile_{key}.png", dpi=110)
    plt.close(fig)
    print(f"  저장: profile_{key}.png")


def analyze(df, V, px, w):
    """구간별로 프로파일을 계산하고 콘솔 요약까지. → [(label, days, edges, rem)]"""
    results, thin5, df5 = [], None, None
    w = np.asarray(w)
    for label, days in WINDOWS:
        mask = np.asarray(df.index >= df.index[-1] - pd.Timedelta(days=days))
        sub = df[mask]
        if len(sub) < 15:
            continue
        nbins = min(90, max(15, len(sub) // 3))   # 짧은 구간은 구간 수도 줄여 과분해 방지
        edges, rem, thin = build(sub, nbins, V[mask], w[mask])
        window_summary(label, edges, rem, px)
        results.append((label, days, edges, rem))
        if label == "5년":
            thin5, df5 = thin, sub
    if df5 is not None:
        hypothesis_check(df5, thin5)
    return results


def to_rows(code, results, px, last_dt):
    out = []
    for _label, days, edges, rem in results:
        pct = rem / max(rem.sum(), 1e-9) * 100
        out += [{"code": code, "win_days": days,
                 "bin_lo": round(float(edges[b]), 4), "bin_hi": round(float(edges[b + 1]), 4),
                 "share": round(float(pct[b]), 4), "px": px, "dt": last_dt}
                for b in range(len(rem))]
    return out


def krx_index(key):
    """KRX 지수 일별시세(krx.py가 stock_daily에 code=kospi/kosdaq로 적재). 부족하면 None.
    야후보다 하루 최신이고 거래'대금'이 있어 저가주 왜곡 없는 가중치를 쓸 수 있다."""
    try:
        rows = page("stock_daily", "dt,high,low,close,tval,mktcap", code=key)
    except Exception:
        return None
    if len(rows) < 200:
        return None
    df = pd.DataFrame(rows)
    df["dt"] = pd.to_datetime(df["dt"])
    df = df.set_index("dt").astype(float).dropna(subset=["high", "low", "close", "tval", "mktcap"])
    df = df[(df["close"] > 0) & (df["high"] > 0) & (df["mktcap"] > 0)]
    return df.rename(columns={"high": "High", "low": "Low", "close": "Close"})


def run(key, push_rows=None):
    sym, name = PRESETS[key]
    df = krx_index(key) if key in REAL_TURN else None
    if df is not None:                       # KRX 직통(한국) — 가격·거래대금·시총이 한 소스
        w = qty(df)
        V = np.clip(df["tval"] / df["mktcap"], 0, 0.2).to_numpy()
        src = f"KRX 지수 일별시세 {len(df)}일 · 실제 회전율"
    else:                                    # 야후(미국, 또는 KRX 적재 전)
        src = None
        df = yf.Ticker(sym).history(period="5y", auto_adjust=True)
        df = df[["Open", "High", "Low", "Close", "Volume"]].dropna()
        zero = (df["Volume"] <= 0).mean()
        if zero > .2:
            print(f"[경고] {name}: 거래량 0인 날이 {zero*100:.0f}% — 프로파일 신뢰도 낮음")
        w = df["Volume"]                     # 야후는 거래량이 이미 수량 단위
        V = real_turnover(df, REAL_TURN[key]) if key in REAL_TURN else turnover(df)
    px = float(df["Close"].iloc[-1])
    last_dt = df.index[-1].strftime("%Y-%m-%d")
    print(f"\n=== {name} — 현재가 {px:,.0f} ({last_dt}) ===")
    if src:
        print(f"  (소스: {src})")
    results = analyze(df, V, px, w)
    if push_rows is None:
        draw(key, name, df, px, results)
    else:
        push_rows += to_rows(key, results, px, last_dt)


# ── 개별종목 ──────────────────────────────────────────────────────────────
# 지수와 달리 종목은 '거래대금 ÷ 시가총액'이 G&H의 진짜 회전율(거래량÷유통주식수)과 같아
# 모델이 근사가 아니라 정의대로 돌아간다. 원자료는 krx.py가 stock_daily에 적재.

def split_adjust(df):
    """주식수 변경(액면분할·병합·인적분할) 보정. 상장주식수가 급변한 날 주가가 그 역수만큼
    움직였으면(=시총 연속) 분할류로 보고 이전 구간 가격에 배율을 적용한다.
    유상증자는 시총이 함께 늘어 주가가 안 꺾이므로 걸리지 않는다. → (배율, 이벤트 목록)"""
    sh, px = df["shares"].to_numpy(), df["close"].to_numpy()
    factor, events = np.ones(len(df)), []
    for i in range(1, len(df)):
        if sh[i - 1] <= 0 or sh[i] <= 0 or px[i - 1] <= 0:
            continue
        r = sh[i] / sh[i - 1]
        if (r > 1.5 or r < 0.67) and abs(px[i] / px[i - 1] * r - 1) < 0.25:
            factor[:i] /= r
            events.append(f"{df.index[i].date()} 주식수 ×{r:.3g} "
                          f"({'분할' if r > 1 else '병합·인적분할'}) → 이전 가격 ×{1 / r:.3g}")
    return factor, events


def run_stock(code, name, push_rows):
    rows = page("stock_daily", "dt,high,low,close,tval,shares,mktcap", code=code)
    if len(rows) < 60:
        print(f"\n=== {name}({code}) — 데이터 {len(rows)}행뿐, 건너뜀 ===")
        return
    df = pd.DataFrame(rows)
    df["dt"] = pd.to_datetime(df["dt"])
    df = df.set_index("dt").astype(float)
    df = df[(df["close"] > 0) & (df["high"] > 0) & (df["mktcap"] > 0)]
    f, events = split_adjust(df)
    for c in ("high", "low", "close"):        # 분할 보정된 가격으로 프로파일을 그린다
        df[c] = df[c] * f
    df = df.rename(columns={"high": "High", "low": "Low", "close": "Close"})
    V = np.clip(df["tval"] / df["mktcap"], 0, 0.5).to_numpy()   # 진짜 회전율
    px = float(df["Close"].iloc[-1])
    last_dt = df.index[-1].strftime("%Y-%m-%d")
    print(f"\n=== {name}({code}) — 현재가 {px:,.0f} ({last_dt}) · 회전율 중앙값 {np.median(V)*100:.2f}%/일 ===")
    for e in events:                          # 헤더 뒤에 찍어야 어느 종목 것인지 헷갈리지 않는다
        print(f"  (주가 보정: {e})")
    results = analyze(df, V, px, qty(df))
    push_rows += to_rows(code, results, px, last_dt)


def stock_list():
    """워치리스트 — krx.py와 같은 기준(stock_meta 시총 상위 N + 지정 종목)."""
    import os
    n = int(os.environ.get("VP_STOCK_N", "30"))
    always = [c.strip() for c in os.environ.get("SCREENER_ALWAYS", "").split(",") if c.strip()]
    rows = client().table("stock_meta").select("code,name,marcap") \
                   .order("marcap", desc=True).limit(n).execute().data or []
    have = {r["code"] for r in rows}
    if [c for c in always if c not in have]:
        rows += client().table("stock_meta").select("code,name") \
                        .in_("code", [c for c in always if c not in have]).execute().data or []
    return [(r["code"], r["name"]) for r in rows]


def push(rows, codes):
    sb = client()
    for c in codes:                          # 전량 교체(구간 경계가 매일 달라져 upsert로는 잔재가 남음)
        sb.table("volume_profile").delete().eq("code", c).execute()
    for i in range(0, len(rows), 1000):
        sb.table("volume_profile").insert(rows[i:i + 1000]).execute()
    print(f"\nvolume_profile 적재 완료: {len(rows)}행 / {len(codes)}종목")


if __name__ == "__main__":
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    if "--stocks" in sys.argv:                # 개별종목 (항상 Supabase 적재 — 로컬 PNG 없음)
        if args:                              # 지정 실행도 이름은 stock_meta에서 찾아 표시
            got = {r["code"]: r["name"] for r in client().table("stock_meta")
                   .select("code,name").in_("code", args).execute().data or []}
            targets = [(c, got.get(c, c)) for c in args]
        else:
            targets = stock_list()
        rows = []
        for code, name in targets:
            run_stock(code, name, rows)
        push(rows, [c for c, _ in targets])
        sys.exit()
    do_push = "--push" in sys.argv
    keys = [a.lower() for a in args] or (list(PRESETS) if do_push else ["kospi"])
    rows = [] if do_push else None
    for k in keys:
        run(k, rows)
    if do_push:
        push(rows, keys)
