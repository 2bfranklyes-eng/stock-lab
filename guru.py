# guru.py — 세계적 투자 구루 5인의 기준으로 미국·한국 종목을 걸러 guru_picks 에 적재
#
# 구루 5인은 "정량화가 가능하고 서로 겹치지 않는" 기준을 고른 것이다.
#   가치(그레이엄) → 우량(버핏) → 성장 대비 가격(린치) → 계량 랭킹(그린블랫) → 모멘텀(오닐)
# 같은 종목이 여러 구루에 동시에 뜨면 그건 우연이 아니라 기준이 겹친 지점이다.
#
# ⚠️ 이건 '검증된 전략'이 아니다(sql/stocks.sql·screener.py 주석과 같은 한계).
#    생존편향(현재 상장 종목만) · 시점데이터 부재(재무가 최신 수정본) · 결측 30~40%.
#    화면에서도 "지금 이 기준에 걸리는 종목은 이것"까지만 말한다. 매수 추천이 아니다.
#
# 데이터 출처
#   · 미국 — S&P500 (위키백과 구성종목) 을 yfinance 로 직접 수집
#   · 한국 — screener.py 가 이미 채워둔 stock_meta 재사용 (시총 상위 500)
#   · 주가 모멘텀 — 두 시장 모두 yf.download 1년 일봉 (52주 신고가·12개월 수익률)
#
# 실행:  python guru.py            → 수집 + Supabase 적재
#        python guru.py --dry      → 적재 없이 결과만 출력 + guru_dry.csv
#        python guru.py --kr-only  → 한국만 (미국 수집 5분을 건너뛴다)
import argparse
import concurrent.futures as cf
import datetime as dt
import io
import os
import random
import sys
import time

import pandas as pd
import requests
import yfinance as yf
from dotenv import load_dotenv

try:  # 윈도우 콘솔(cp949)에서도 한글·기호 출력이 깨지지 않게
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

load_dotenv()

UA = {"User-Agent": "Mozilla/5.0"}
# 야후 동시 요청 수. 8로 올리면 빠르지만 1,000요청쯤에서 rate limit 에 걸린다 — 미국 503 +
# 한국 500을 한 번에 돌리면 정확히 그 구간이라, 속도보다 완주를 택했다.
WORKERS = int(os.environ.get("GURU_WORKERS", "4"))
TOP_PER_GURU = 40      # 구루·시장별 상위 몇 종목까지 저장할지
KR_MIN_CAP = 3e11      # 3,000억원 — '충분한 규모'(그레이엄·버핏 공통 조건)
US_MIN_CAP = 2e9       # $20억


# ─────────────────────────── 유니버스 ───────────────────────────

def us_universe():
    """S&P500 구성종목. 미국 대형주는 사실상 전부 여기 들어 있어 이거 하나면 충분하다.
    (나스닥100 중 S&P500 밖 종목은 대부분 외국 국적 ADR이라 재무 비교가 오히려 지저분해진다.)"""
    r = requests.get("https://en.wikipedia.org/wiki/List_of_S%26P_500_companies",
                     headers=UA, timeout=30)
    t = pd.read_html(io.StringIO(r.text))[0]
    # 위키는 'BRK.B' 표기, 야후는 'BRK-B' — 이걸 안 바꾸면 그 종목만 조용히 빠진다
    out = [{"sym": s.replace(".", "-"), "name": n, "market": "US"}
           for s, n in zip(t["Symbol"], t["Security"])]
    print(f"미국 유니버스: S&P500 {len(out)}종목")
    return out


def page(sb, table, cols="*"):
    rows, frm = [], 0
    while True:
        d = sb.table(table).select(cols).range(frm, frm + 999).execute().data
        rows += d
        if len(d) < 1000:
            break
        frm += 1000
    return rows


def kr_universe(sb):
    """한국은 두 소스를 합친다.
      · dart.py → dart_fin : 재무 원문(금감원 전자공시). 결측이 없다.
      · screener.py → stock_meta : 시세·시총·섹터, 그리고 차입금(debt_to_equity).
    재무를 DART 로 옮긴 이유는 야후 한국 재무의 결측이 커서다 — PER 31% · 이익성장 40%가 비어
    '기준 미달'이 아니라 '판정 불가'로 탈락하는 종목이 섞여 있었다.
    차입금만 야후를 계속 쓰는 건 정의를 미국과 맞추기 위해서다. DART 의 debt_ratio 는
    '총부채÷자본'(기아 71%)이고 야후 debtToEquity 는 '총차입금÷자본'(기아 4.3%)이라 뜻이
    아예 다르다 — 섞으면 같은 기준선(100% 이하)이 두 시장에서 다른 의미가 된다."""
    meta = [r for r in page(sb, "stock_meta")
            if r.get("market") in ("KOSPI", "KOSDAQ", "KONEX")]
    try:
        dart = {r["code"]: r for r in page(sb, "dart_fin")}
    except Exception as e:
        dart = {}
        print(f"  ⚠️ dart_fin 을 못 읽었습니다({str(e)[:50]}) — 한국 재무는 야후로 대체합니다")
    hit = sum(1 for r in meta if r["code"] in dart)
    print(f"한국 유니버스: stock_meta {len(meta)}종목 · DART 재무 {hit}종목"
          f"({hit / max(len(meta), 1) * 100:.0f}%)")
    return meta, dart


# ─────────────────────────── 스냅샷 ───────────────────────────

def epoch_date(ts):
    if not ts:
        return None
    try:
        return dt.datetime.fromtimestamp(int(ts), dt.timezone.utc).strftime("%Y-%m-%d")
    except (TypeError, ValueError, OSError, OverflowError):
        return None


def info_of(sym, tries=5):
    """야후는 요청이 몰리면 YFRateLimitError 를 던진다. 이걸 그대로 삼키면 '지표가 없는 종목'과
    구분이 안 돼 결과가 조용히 반쪽이 된다(실측: 한국 500종목 중 135종목만 채워진 적 있다).
    그래서 rate limit 만 골라 물러섰다 다시 시도하고, 끝내 실패하면 예외로 올려 세어 보고한다.
    지터를 섞는 건 스레드가 동시에 깨어나 같은 벽에 다시 부딪히는 걸 막기 위해서다."""
    for k in range(tries):
        try:
            return yf.Ticker(sym).info
        except Exception as e:
            if "rate limit" not in str(e).lower() and "too many" not in str(e).lower():
                raise
            if k == tries - 1:
                raise
            time.sleep(3 * 2 ** k + random.random() * 3)
    return {}


def us_snapshot(u):
    """미국 한 종목의 재무 스냅샷. 필드 이름·스케일을 한국(stock_meta)과 맞춰 담는다 —
    roe/op_margin 은 소수(0.15=15%), debt_to_equity·div_yield 는 퍼센트 숫자(78.4=78.4%).
    이 두 스케일이 시장마다 다르면 같은 기준을 두 시장에 못 쓴다."""
    i = info_of(u["sym"])
    return {
        "code": u["sym"], "name": i.get("shortName") or u["name"], "market": "US",
        "sector": i.get("sector"), "currency": i.get("currency") or "USD",
        "close": i.get("currentPrice") or i.get("regularMarketPrice"),
        "marcap": i.get("marketCap"),
        "per": i.get("trailingPE"),
        "pbr": i.get("priceToBook"),
        "roe": i.get("returnOnEquity"),
        # 마법공식 전용 두 축. ROE 를 쓰면 자사주로 자본이 쪼그라든 회사(Masco ROE 5862%)가
        # 최상위를 먹는다 — 회계 부산물이지 실력이 아니다. ROA·EV/EBITDA 는 그 왜곡이 없다.
        "roa": i.get("returnOnAssets"),
        "ev_ebitda": i.get("enterpriseToEbitda"),
        "debt_to_equity": i.get("debtToEquity"),
        "op_margin": i.get("operatingMargins"),
        "profit_margin": i.get("profitMargins"),
        "rev_growth": i.get("revenueGrowth"),
        "earn_growth": i.get("earningsGrowth"),
        "div_yield": i.get("dividendYield"),
        "fiscal_q": epoch_date(i.get("mostRecentQuarter")),
        # 미국은 EBIT·투하자본을 무료로 못 얻는다 — 한국(DART)만 채워지는 칸
        "roic": None, "ebit": None, "fin_src": "야후",
    }


def collect_us(uni):
    """503종목을 순차로 받으면 5분이 넘는다 — 스레드로 줄인다. 야후는 비공식 스크래퍼라
    일부는 반드시 실패하므로, 실패를 모아 세고 넘어간다(한 종목 때문에 전체가 죽으면 안 된다)."""
    rows, fail = [], []
    t0 = time.time()
    with cf.ThreadPoolExecutor(max_workers=WORKERS) as ex:
        futs = {ex.submit(us_snapshot, u): u for u in uni}
        for n, f in enumerate(cf.as_completed(futs), 1):
            try:
                rows.append(f.result())
            except Exception as e:
                fail.append(f"{futs[f]['sym']}({str(e)[:30]})")
            if n % 100 == 0:
                print(f"  미국 {n}/{len(uni)}  ({time.time() - t0:.0f}초)")
    print(f"미국 수집 완료: {len(rows)}종목 / 실패 {len(fail)} ({time.time() - t0:.0f}초)")
    if fail:
        print("  실패:", ", ".join(fail[:8]) + (" …" if len(fail) > 8 else ""))
    return rows


def kr_rows(uni, dart):
    """stock_meta + dart_fin → 미국과 같은 스키마로. DART 값이 있으면 그걸 쓰고, 없는 종목만
    야후로 떨어진다(폴백). PER·PBR 은 KRX 시총을 DART 의 TTM 순이익·자본으로 나눠 다시 만든다
    — screener.py 가 계산한 것과 정의는 같고 분자만 원문으로 바뀐다."""
    def pick(d, r, key):
        # 0.0 을 '없음'으로 보면 안 되므로 or 가 아니라 is None 으로 판정한다
        v = d.get(key) if d else None
        return v if v is not None else r.get(key)

    # ── 우선주 보정 ──
    # DART 재무는 '회사' 단위인데 stock_meta 의 시총은 '그 주식 클래스' 단위다. 그대로 나누면
    # 우선주가 회사 전체 순이익을 자기 시총으로 나눠 PER 이 터무니없이 낮아진다
    # (실측: 삼성화재우 0.59 · 삼성전자우 1.62 — 그레이엄 한국 상위 10 중 6개가 우선주였다).
    # 그래서 시총이 아니라 '주가 × 회사 전체 주식수'로 나눈다 = 주가÷주당순이익, 즉 진짜 PER.
    # 전체 주식수는 같은 corp_code 를 쓰는 클래스들의 (시총÷주가)를 더해 구한다.
    # 우선주가 없는 회사면 합이 자기 자신뿐이라 결과가 기존과 같다 — 분기 처리가 필요 없다.
    shares = {}
    for r in uni:
        mc, px = r.get("marcap"), r.get("close")
        if mc and px and px > 0:
            shares[r["code"]] = mc / px
    tot_shares = {}
    for r in uni:
        d = dart.get(r["code"])
        cc = d.get("corp_code") if d else None
        key = cc or r["code"]
        tot_shares[key] = tot_shares.get(key, 0) + shares.get(r["code"], 0)

    out = []
    for r in uni:
        d = dart.get(r["code"])
        mc, px = r.get("marcap"), r.get("close")
        ni, eq = (d or {}).get("net_income"), (d or {}).get("equity")
        # 밸류에이션 분자: 주가 × 회사 전체 주식수 (= 이 회사를 통째로 살 때의 값을
        # '이 클래스 주가'로 환산한 것). 규모 판정·화면 표시에 쓰는 marcap 은 그대로 둔다.
        mv = px * tot_shares.get((d or {}).get("corp_code") or r["code"], 0) if px else None
        per = mv / ni if mv and ni and ni > 0 else r.get("per")
        pbr = mv / eq if mv and eq and eq > 0 else r.get("pbr")
        out.append({
            "code": r["code"], "name": r["name"], "market": r["market"],
            "sector": r.get("sector"), "currency": "KRW",
            "close": r.get("close"), "marcap": mc,
            "per": per, "pbr": pbr,
            "roe": pick(d, r, "roe"), "roa": pick(d, r, "roa"),
            "op_margin": pick(d, r, "op_margin"),
            "profit_margin": pick(d, r, "profit_margin"),
            "rev_growth": pick(d, r, "rev_growth"),
            "earn_growth": pick(d, r, "earn_growth"),
            # 차입금·배당은 DART 에 없거나 계정이 회사마다 달라 야후를 그대로 쓴다
            "debt_to_equity": r.get("debt_to_equity"),
            "div_yield": r.get("div_yield"),
            "ev_ebitda": r.get("ev_ebitda"),
            # 마법공식 한국판 전용 — DART 라야 나오는 값들
            "roic": (d or {}).get("roic"), "ebit": (d or {}).get("ebit"),
            "_mv": mv,          # 밸류에이션용 분자(우선주 보정본). 이익수익률도 이걸로 나눈다
            "fiscal_q": (d or {}).get("fiscal_q") or r.get("fiscal_q"),
            "fin_src": "DART" if d else "야후",
        })
    return out


def add_kr_capital(rows):
    """stock_meta 에 ROA·EV/EBITDA 가 비어 있는 한국 종목만 직접 받아 메운다.
    정상 경로는 screener.py 가 채워두는 것이고(= 요청 0건), 여기는 그 전에도 화면이 뜨게 하는
    보조 경로다. 500종목을 전부 받으면 야후 rate limit 에 걸리므로 '비어 있는 것만' 받는다."""
    todo = [r for r in rows if r["market"] != "US" and r.get("roa") is None]
    if not todo:
        return rows
    print(f"한국 ROA·EV/EBITDA 보충 수집 {len(todo)}종목 "
          f"— screener.py 를 다시 돌리면 이 단계는 사라집니다")

    def one(r):
        i = info_of(ysym(r))
        return r, i.get("returnOnAssets"), i.get("enterpriseToEbitda")

    t0, got, fail = time.time(), 0, 0
    with cf.ThreadPoolExecutor(max_workers=WORKERS) as ex:
        for f in cf.as_completed([ex.submit(one, r) for r in todo]):
            try:
                r, roa, ev = f.result()
            except Exception:
                fail += 1
                continue
            r["roa"], r["ev_ebitda"] = roa, ev
            got += roa is not None
    # 실패 수를 반드시 찍는다 — 조용히 넘어가면 '지표 없는 종목'과 구분이 안 된다
    print(f"  채움 {got}/{len(todo)}종목 · 요청실패 {fail} ({time.time() - t0:.0f}초)")
    if fail:
        print("  ⚠️ 실패분은 마법공식 후보에서 빠집니다 — 잠시 뒤 재실행하거나 screener.py 를 돌리세요")
    return rows


def ysym(r):
    if r["market"] == "US":
        return r["code"]
    return f"{r['code']}.{'KS' if r['market'] == 'KOSPI' else 'KQ'}"


def add_price_stats(rows):
    """1년 일봉으로 12개월 수익률과 52주 신고가 대비 위치. 오닐(CAN SLIM)의 N·L 조건에 쓴다.
    재무만으로는 '지금 시장이 이 종목을 어떻게 보는가'가 하나도 안 들어온다."""
    syms = [ysym(r) for r in rows]
    stat = {}
    t0 = time.time()
    for i in range(0, len(syms), 100):    # 한 번에 다 부르면 야후가 막는다
        chunk = syms[i:i + 100]
        try:
            d = yf.download(" ".join(chunk), period="1y", interval="1d",
                            progress=False, auto_adjust=True, group_by="ticker")
        except Exception as e:
            print(f"  주가 배치 실패 {i}: {str(e)[:60]}")
            continue
        for sym in chunk:
            try:
                s = (d[sym]["Close"] if isinstance(d.columns, pd.MultiIndex) else d["Close"]).dropna()
            except (KeyError, TypeError):
                continue
            if len(s) < 120:      # 상장 1년 미만 — 12개월 수익률을 말할 수 없다
                continue
            last, first, hi = float(s.iloc[-1]), float(s.iloc[0]), float(s.max())
            if first <= 0 or hi <= 0:
                continue
            stat[sym] = {"mom_12m": last / first - 1, "off_high": last / hi}
        print(f"  주가 {min(i + 100, len(syms))}/{len(syms)}  ({time.time() - t0:.0f}초)")
    for r in rows:
        s = stat.get(ysym(r), {})
        r["mom_12m"] = s.get("mom_12m")
        r["off_high"] = s.get("off_high")
    got = sum(1 for r in rows if r["mom_12m"] is not None)
    print(f"주가 통계: {got}/{len(rows)}종목")
    return rows


# ─────────────────────────── 파생 지표 ───────────────────────────

def peg_of(s):
    """PEG = PER ÷ 이익성장률(%). 린치의 핵심 잣대 — '성장률만큼의 PER 까지가 제값'."""
    per, g = s.get("per"), s.get("earn_growth")
    if not per or per <= 0 or g is None or g <= 0:
        return None
    return per / (g * 100)


def lynch_ratio(s):
    """린치 비율 = (이익성장률% + 배당수익률%) ÷ PER. 린치 기준 1.5 이상 양호, 2 이상 우수."""
    per, g = s.get("per"), s.get("earn_growth")
    if not per or per <= 0 or g is None:
        return None
    return (g * 100 + (s.get("div_yield") or 0)) / per


def graham_num(s):
    """그레이엄 수 = PER × PBR. 그가 제시한 상한은 22.5 (= 15 × 1.5)."""
    per, pbr = s.get("per"), s.get("pbr")
    if not per or not pbr or per <= 0 or pbr <= 0:
        return None
    return per * pbr


def enrich(rows):
    for s in rows:
        s["peg"] = peg_of(s)
        s["_lynch"] = lynch_ratio(s)
        s["_graham"] = graham_num(s)
        s["_min_cap"] = US_MIN_CAP if s["market"] == "US" else KR_MIN_CAP
        # 마법공식의 두 축. 시장마다 얻을 수 있는 게 달라서 계산식이 다르다 — 순위를 시장별로
        # 따로 매기니 섞이지는 않지만, 화면에는 반드시 밝혀야 한다.
        #   한국(DART): 원본 그대로. ROIC = EBIT ÷ (순운전자본+순고정자산), 이익수익률 = EBIT ÷ 시총
        #   미국(야후) : EBIT·투하자본을 못 얻어 근사. ROA, 그리고 EBITDA ÷ EV
        # EV 를 쓰는 쪽(미국)은 부채까지 값에 넣지만 한국은 시총 기준이다 — 한국은 대신 ROIC 가
        # 자본 효율을 원본대로 잡아준다.
        if s["market"] == "US":
            ev = s.get("ev_ebitda")
            s["_roc"] = s.get("roa")
            s["_ey"] = (1 / ev) if ev and ev > 0 else None
        else:
            # 분모는 우선주 보정을 거친 _mv — marcap 을 쓰면 우선주의 이익수익률이
            # 회사 전체 EBIT ÷ 클래스 시총이 돼 10배 넘게 부풀려진다(PER 과 같은 함정).
            mc, ebit = s.get("_mv") or s.get("marcap"), s.get("ebit")
            s["_roc"] = s.get("roic") if s.get("roic") is not None else s.get("roa")
            s["_ey"] = (ebit / mc) if ebit is not None and mc else None
    # 오닐의 L(상대강도)은 '같은 시장 안에서의 순위'다 — 미국·한국을 섞어 매기면 환율·시장
    # 전체 흐름이 종목 실력으로 둔갑한다. 그래서 시장별로 따로 백분위를 낸다.
    for mk in {r["market"] for r in rows}:
        grp = [r for r in rows if r["market"] == mk and r.get("mom_12m") is not None]
        grp.sort(key=lambda r: r["mom_12m"])
        for i, r in enumerate(grp):
            r["_rs"] = (i + 1) / len(grp) * 100      # 1~100, 높을수록 강세
    for s in rows:
        s.setdefault("_rs", None)
    return rows


# ─────────────────────────── 구루 정의 ───────────────────────────
# 규칙 하나는 (라벨, 판정함수). 판정함수는 True/False 를 주고, 값이 없으면 False —
# '결측이라 모른다'와 '기준 미달'을 구분해 통과시키면 데이터 없는 종목이 전부 통과한다.

def ge(key, v):
    return lambda s: s.get(key) is not None and s[key] >= v


def le(key, v):
    return lambda s: s.get(key) is not None and s[key] <= v


def between(key, lo, hi):
    return lambda s: s.get(key) is not None and lo <= s[key] <= hi


GURUS = [
    {
        "key": "buffett", "name": "워런 버핏", "emoji": "🏰",
        "tagline": "훌륭한 기업을 적당한 가격에",
        "idea": "돈을 잘 벌고(높은 ROE·마진) 빚이 적으며, 가격이 터무니없지 않은 회사. "
                "싼 것보다 좋은 것이 먼저다.",
        "rules": [
            ("ROE 15% 이상", ge("roe", 0.15)),
            ("영업이익률 10% 이상", ge("op_margin", 0.10)),
            ("순이익률 8% 이상", ge("profit_margin", 0.08)),
            ("부채/자본 100% 이하", le("debt_to_equity", 100)),
            ("PER 25배 이하 (흑자)", between("per", 0.1, 25)),
            ("충분한 규모", lambda s: (s.get("marcap") or 0) >= s["_min_cap"]),
        ],
        # 수익성 대비 가격 — 같은 ROE면 싼 쪽, 같은 PER이면 잘 버는 쪽이 위로
        "score": lambda s: s["roe"] / s["per"] * 100,
        "score_label": "ROE÷PER",
        "desc_score": "수익성 대비 가격. 높을수록 '잘 버는데 안 비싼' 쪽",
    },
    {
        "key": "graham", "name": "벤저민 그레이엄", "emoji": "🛡️",
        "tagline": "안전마진 — 가치보다 확실히 싸게",
        "idea": "『현명한 투자자』의 방어적 투자자 조건 중 계량 가능한 것들. "
                "미래를 맞히려 하지 않고, 지금 장부 대비 싼 것만 산다.",
        "rules": [
            ("PER 15배 이하", between("per", 0.1, 15)),
            ("PBR 1.5배 이하", between("pbr", 0.01, 1.5)),
            ("그레이엄 수(PER×PBR) 22.5 이하", le("_graham", 22.5)),
            ("부채/자본 50% 이하", le("debt_to_equity", 50)),
            ("배당 지급", lambda s: (s.get("div_yield") or 0) > 0),
            ("흑자 (ROE·순이익률 > 0)",
             lambda s: (s.get("roe") or 0) > 0 and (s.get("profit_margin") or 0) > 0),
            ("충분한 규모", lambda s: (s.get("marcap") or 0) >= s["_min_cap"]),
        ],
        "score": lambda s: 22.5 / s["_graham"],
        "score_label": "안전마진 배수",
        "desc_score": "22.5 ÷ 그레이엄 수. 2면 상한의 절반 값에 산다는 뜻",
    },
    {
        "key": "lynch", "name": "피터 린치", "emoji": "🎯",
        "tagline": "성장에 비해 싼가 (GARP)",
        "idea": "성장률만큼의 PER 까지가 제값(PEG 1). 성장도 너무 빠르면 오래 못 가므로 "
                "연 15~50% 구간만 본다.",
        "rules": [
            ("PEG 1.0 이하", between("peg", 0.01, 1.0)),
            ("이익성장 15~50%", between("earn_growth", 0.15, 0.50)),
            ("PER 30배 이하 (흑자)", between("per", 0.1, 30)),
            ("부채/자본 80% 이하", le("debt_to_equity", 80)),
            ("충분한 규모", lambda s: (s.get("marcap") or 0) >= s["_min_cap"]),
        ],
        "score": lambda s: s["_lynch"],
        "score_label": "린치 비율",
        "desc_score": "(이익성장% + 배당%) ÷ PER. 린치 기준 1.5 양호 · 2.0 우수",
    },
    {
        "key": "greenblatt", "name": "조엘 그린블랫", "emoji": "🔢",
        "tagline": "마법공식 — 좋은 회사를 싸게, 순위로만",
        "idea": "자본수익률 순위와 이익수익률 순위를 더해 낮은 순으로. 판단을 넣지 않고 "
                "순위만 본다. 사업 구조가 다른 금융·유틸리티는 원래 제외한다.",
        # 랭킹 방식이라 rules 는 '후보 자격'까지만 — 실제 선정은 아래 rank_greenblatt
        "rules": [
            ("자본수익률 > 0", lambda s: (s.get("_roc") or 0) > 0),
            ("이익수익률 > 0", lambda s: (s.get("_ey") or 0) > 0),
            ("금융·유틸리티 제외",
             lambda s: s.get("sector") not in ("Financial Services", "Utilities")),
            ("충분한 규모", lambda s: (s.get("marcap") or 0) >= s["_min_cap"]),
        ],
        "rank": True,
        "score_label": "순위합",
        "desc_score": "ROA 순위 + EBITDA/EV 순위. 낮을수록 상위 (합이 작을수록 두 축 모두 좋다)",
    },
    {
        "key": "oneil", "name": "윌리엄 오닐", "emoji": "🚀",
        "tagline": "CAN SLIM — 이익이 튀고 주가도 강한 것",
        "idea": "실적이 급증하면서 주가가 이미 신고가 부근에 있는 종목. "
                "싼 것을 사는 게 아니라 강한 것을 산다. 7조건 중 계량 가능한 4개.",
        "rules": [
            ("C — 최근 분기 이익성장 20% 이상", ge("earn_growth", 0.20)),
            ("A — 매출성장 10% 이상", ge("rev_growth", 0.10)),
            ("N — 52주 신고가 대비 85% 이상", ge("off_high", 0.85)),
            ("L — 12개월 상대강도 상위 30%", ge("_rs", 70)),
            ("흑자 (순이익률 > 0)", lambda s: (s.get("profit_margin") or 0) > 0),
            ("충분한 규모", lambda s: (s.get("marcap") or 0) >= s["_min_cap"]),
        ],
        "score": lambda s: s["mom_12m"] * 100,
        "score_label": "12개월 수익률",
        "desc_score": "최근 1년 주가 상승률(%). 오닐의 L(상대강도)에 해당",
    },
]


def rank_greenblatt(rows, g):
    """마법공식. 두 축(_roc·_ey)은 enrich() 에서 시장별로 다르게 만들어진다 —
    한국은 DART 원문으로 원본 공식(ROIC·EBIT/시총) 그대로, 미국은 EBIT 를 못 얻어 근사(ROA·EBITDA/EV).
    ROE 로 대체하는 흔한 간이판은 어느 쪽에도 쓰지 않았다 — 자사주로 자본이 거의 없어진 회사가
    ROE 수천 %로 최상위를 먹어(실측: Masco 5862%) 순위가 통째로 망가진다.
    ※ 시장별로 따로 순위를 매긴다 — 미국·한국을 한 줄로 세우면 시장 전체의 밸류에이션 차이가
      종목 실력으로 둔갑하고(한국이 통째로 싸서 상위 독식), 위처럼 계산식까지 달라 애초에
      같은 자로 잰 값이 아니다.
    """
    out = []
    for mk in {r["market"] for r in rows}:
        cand = [s for s in rows if s["market"] == mk and all(f(s) for _, f in g["rules"])]
        if not cand:
            continue
        by_roc = sorted(cand, key=lambda s: -s["_roc"])
        by_ey = sorted(cand, key=lambda s: -s["_ey"])
        rk = {id(s): 0 for s in cand}
        for i, s in enumerate(by_roc):
            rk[id(s)] += i + 1
        for i, s in enumerate(by_ey):
            rk[id(s)] += i + 1
        cand.sort(key=lambda s: rk[id(s)])
        for s in cand[:TOP_PER_GURU]:
            out.append((s, float(rk[id(s)])))
    return out


def apply_gurus(rows):
    """구루별 통과 종목. 시장별로 상위 TOP_PER_GURU 씩 자른다."""
    picks, summary = [], []
    for g in GURUS:
        if g.get("rank"):
            scored = rank_greenblatt(rows, g)
            asc = True                     # 순위합은 낮을수록 좋다
        else:
            scored = [(s, g["score"](s)) for s in rows if all(f(s) for _, f in g["rules"])]
            asc = False
        n_pass = len(scored)
        kept = []
        for mk in {s["market"] for s, _ in scored}:
            grp = [x for x in scored if x[0]["market"] == mk]
            grp.sort(key=lambda x: x[1], reverse=not asc)
            kept += [(s, sc, i + 1) for i, (s, sc) in enumerate(grp[:TOP_PER_GURU])]
        for s, sc, rank in kept:
            picks.append({
                "guru": g["key"], "rank": rank, "score": round(float(sc), 4),
                "code": s["code"], "name": s["name"], "market": s["market"],
                "sector": s.get("sector"), "currency": s["currency"],
                "close": s.get("close"), "marcap": s.get("marcap"),
                "per": s.get("per"), "pbr": s.get("pbr"), "roe": s.get("roe"),
                "roa": s.get("roa"), "ev_ebitda": s.get("ev_ebitda"),
                "roic": s.get("roic"), "ebit": s.get("ebit"),
                "earn_yield": s.get("_ey"), "fin_src": s.get("fin_src"),
                "debt_to_equity": s.get("debt_to_equity"),
                "op_margin": s.get("op_margin"), "profit_margin": s.get("profit_margin"),
                "rev_growth": s.get("rev_growth"), "earn_growth": s.get("earn_growth"),
                "div_yield": s.get("div_yield"), "peg": s.get("peg"),
                "mom_12m": s.get("mom_12m"), "off_high": s.get("off_high"),
                "fiscal_q": s.get("fiscal_q"),
            })
        summary.append((g, n_pass, len(kept)))
    return picks, summary


def rnd(v, n=6):
    if v is None or (isinstance(v, float) and pd.isna(v)):
        return None
    try:
        return round(float(v), n)
    except (TypeError, ValueError):
        return None


def clean(picks):
    num = ("score", "close", "marcap", "per", "pbr", "roe", "roa", "ev_ebitda",
           "roic", "ebit", "earn_yield",
           "debt_to_equity", "op_margin", "profit_margin", "rev_growth", "earn_growth",
           "div_yield", "peg", "mom_12m", "off_high")
    return [{k: (rnd(v) if k in num else v) for k, v in p.items()} for p in picks]


# ─────────────────────────── 출력 ───────────────────────────

def rule_diag(rows, g):
    """조건별 단독 통과 수. 결과가 4종목뿐일 때 '기준이 엄해서'인지 '데이터가 없어서'인지를
    가르는 건 이 표뿐이다 — 통과 수만 보면 둘을 구분할 방법이 없다."""
    out = []
    for lbl, f in g["rules"]:
        out.append((lbl, sum(1 for s in rows if f(s))))
    return out


def report(picks, summary, rows):
    n_us = sum(1 for r in rows if r["market"] == "US")
    print(f"\n{'=' * 78}\n유니버스 {len(rows)}종목 (미국 {n_us} · 한국 {len(rows) - n_us})\n{'=' * 78}")
    for g, n_pass, n_kept in summary:
        print(f"\n{g['emoji']} {g['name']} — {g['tagline']}")
        print("   조건별 단독 통과: " + " · ".join(
            f"{lbl.split(' —')[0]} {n}" for lbl, n in rule_diag(rows, g)))
        print(f"   전조건 통과 {n_pass}종목 → 시장별 상위 {TOP_PER_GURU} 저장({n_kept})  [{g['score_label']}]")
        for mk, flag in (("US", "🇺🇸"), ("KOSPI", "🇰🇷"), ("KOSDAQ", "🇰🇷")):
            sel = sorted([p for p in picks if p["guru"] == g["key"] and p["market"] == mk],
                         key=lambda p: p["rank"])[:10]
            if not sel:
                continue
            print(f"   {flag} {mk} 상위 {len(sel)}:")
            for p in sel:
                per = f"PER {p['per']:.1f}" if p["per"] else "PER —"
                roe = f"ROE {p['roe'] * 100:.0f}%" if p["roe"] is not None else "ROE —"
                print(f"      {p['rank']:>2}. {p['name'][:22]:<22} {p['score']:>9.2f}   {per:<10} {roe}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry", action="store_true", help="적재 없이 결과만 출력 + guru_dry.csv")
    ap.add_argument("--kr-only", action="store_true")
    ap.add_argument("--us-only", action="store_true")
    a = ap.parse_args()

    from supabase import create_client
    sb = create_client(os.environ["SUPABASE_URL"], os.environ["SUPABASE_SERVICE_KEY"])

    rows = []
    if not a.kr_only:
        rows += collect_us(us_universe())
    if not a.us_only:
        meta, dart = kr_universe(sb)
        rows += add_kr_capital(kr_rows(meta, dart))
    rows = enrich(add_price_stats(rows))

    picks, summary = apply_gurus(rows)
    picks = clean(picks)
    report(picks, summary, rows)

    if a.dry:
        pd.DataFrame(picks).to_csv("guru_dry.csv", index=False, encoding="utf-8-sig")
        print(f"\n[dry] guru_dry.csv 에 {len(picks)}행 저장 — Supabase 적재는 건너뜀")
        return

    # 이번 실행에서 빠진 종목이 남아 있으면 화면에선 멀쩡해 보이면서 조용히 낡는다 → 통째로 갈아끼운다
    sb.table("guru_picks").delete().neq("guru", "").execute()
    for i in range(0, len(picks), 500):
        sb.table("guru_picks").upsert(picks[i:i + 500], on_conflict="guru,code").execute()
    print(f"\nguru_picks 적재: {len(picks)}행")


if __name__ == "__main__":
    main()
