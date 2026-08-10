# dart.py — 금융감독원 DART 전자공시에서 한국 종목 재무제표 수집 → dart_fin
#
# 왜 야후를 안 쓰고 이걸 따로 받나: 야후의 한국 재무는 결측이 크다(실측 PER 31% ·
# 이익성장 40% · ROA 20%). 그 종목들은 '기준 미달'이 아니라 '판정 불가'로 스크리너에서
# 조용히 빠지는데, 화면만 봐선 둘을 구분할 수 없다. DART 는 원문이라 결측이 없다
# (샘플 60종목에서 1분기·사업보고서 59/59 확보 — 연결 55 · 별도 4).
#
# ⚠️ 다만 DART 가 야후보다 '빠르지는' 않다. 이 API 는 정기보고서(사업·반기·분기)만 담고,
#    7월에 나오는 잠정실적 공시는 안 들어온다. 그래서 분기 전환기 2~3주 동안은 야후가
#    앞선다(실측: 2026-08-10 기준 야후는 삼성전자 2026-06-30, DART 는 아직 2026-03-31).
#    바꾼 이유는 속도가 아니라 커버리지와 정확도다.
#
# 실행:  python dart.py           → 수집 + 적재
#        python dart.py --dry     → 적재 없이 출력만
#        python dart.py 005930 …  → 지정 종목만 (디버깅)
import argparse
import concurrent.futures as cf
import io
import json
import os
import sys
import threading
import time
import urllib.error
import urllib.request
import xml.etree.ElementTree as ET
import zipfile
from datetime import date, datetime, timezone

from dotenv import load_dotenv
from supabase import create_client

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

load_dotenv()
sb = create_client(os.environ["SUPABASE_URL"], os.environ["SUPABASE_SERVICE_KEY"])
KEY = os.environ.get("DART_API_KEY", "").strip()
BASE = "https://opendart.fss.or.kr/api"
# DART 는 동시 요청에 아주 민감하다. 6으로 돌렸더니 486종목 중 257이 끊겼고, 3으로 낮춰
# 재시도해도 IP 자체가 막혀 작은 요청 하나도 못 나갔다(HTTP 에러가 아니라 TCP reset).
# 그래서 기본을 순차(1) + 요청 간 간격으로 잡는다. 500종목 ≈ 8분이면 주 1회 작업엔 충분하다.
WORKERS = int(os.environ.get("DART_WORKERS", "1"))
GAP = float(os.environ.get("DART_GAP", "0.25"))      # 요청 사이 최소 간격(초)
CACHE = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".cache")
_last_call = [0.0]
_gap_lock = threading.Lock()

# 정기보고서 코드. 최신부터 훑어 처음 잡히는 걸 쓴다.
REPRT = {"11011": "사업보고서", "11013": "1분기", "11012": "반기", "11014": "3분기"}
# 보고서 → 그 보고서가 다루는 분기말 월·일. fiscal_q(=재무 기준일) 계산에 쓴다.
QEND = {"11013": (3, 31), "11012": (6, 30), "11014": (9, 30), "11011": (12, 31)}

# 계정과목은 IFRS 표준 account_id 로 잡는다 — 회사마다 이름(account_nm)은 달라도
# 코드는 같다. 다만 영업이익은 회사에 따라 두 코드를 섞어 써서 후보를 여러 개 둔다.
ACC = {
    "revenue": ["ifrs-full_Revenue", "ifrs-full_RevenueFromContractsWithCustomers"],
    "op_income": ["dart_OperatingIncomeLoss", "ifrs-full_ProfitLossFromOperatingActivities"],
    "net_income": ["ifrs-full_ProfitLoss"],
    "assets": ["ifrs-full_Assets"],
    "liabilities": ["ifrs-full_Liabilities"],
    "equity": ["ifrs-full_Equity"],
    "cur_assets": ["ifrs-full_CurrentAssets"],
    "cur_liabilities": ["ifrs-full_CurrentLiabilities"],
    "ppe": ["ifrs-full_PropertyPlantAndEquipment"],
}
BS_KEYS = {"assets", "liabilities", "equity", "cur_assets", "cur_liabilities", "ppe"}


class DartBlocked(Exception):
    """DART 가 TCP 연결 자체를 끊는 상태. 한 종목의 문제가 아니라 IP가 막힌 것이라,
    남은 종목을 계속 시도해봐야 전부 실패한다 — 위로 올려 수집을 접고 다음 실행에 넘긴다."""


def _pace():
    """요청 사이 최소 간격. DART 는 HTTP 429 대신 연결을 끊어서, 몰아치면 복구가 오래 걸린다."""
    with _gap_lock:
        wait = GAP - (time.monotonic() - _last_call[0])
        if wait > 0:
            time.sleep(wait)
        _last_call[0] = time.monotonic()


def fetch(path, **params):
    _pace()
    q = "&".join(f"{k}={v}" for k, v in {"crtfc_key": KEY, **params}.items())
    url = f"{BASE}/{path}?{q}"
    # DART 는 동시 요청이 많으면 HTTP 에러 대신 연결을 그냥 끊는다(WinError 10054).
    # 그건 URLError 가 아니라 ConnectionResetError 로 올라와서, 좁게 잡으면 재시도가 통째로
    # 안 걸린다 — 실측으로 486종목 중 257종목이 이 한 줄 때문에 실패했다. OSError 로 넓게 잡는다
    # (URLError·ConnectionResetError·TimeoutError 가 전부 OSError 하위다).
    for k in range(4):
        try:
            with urllib.request.urlopen(url, timeout=60) as r:
                return r.read()
        except OSError as e:
            if k == 3:
                raise DartBlocked(f"{type(e).__name__}: {str(e)[:60]}") from e
            time.sleep(2 * 2 ** k)


def corp_map(max_age_days=7):
    """종목코드 → DART 고유번호. 118,681건 중 상장 3,981건만 남는다.
    3.5MB zip 이라 디스크에 캐시한다 — 실행마다 다시 받으면 그 자체로 IP 차단을 부르고,
    차단됐을 때 첫 줄에서 죽어 나머지 작업이 통째로 못 돈다. 상장사 목록은 하루 단위로만
    바뀌므로 일주일 캐시면 충분하다."""
    os.makedirs(CACHE, exist_ok=True)
    p = os.path.join(CACHE, "corpcode.json")
    if os.path.exists(p) and time.time() - os.path.getmtime(p) < max_age_days * 86400:
        with open(p, encoding="utf-8") as f:
            out = json.load(f)
        print(f"corp_code 매핑: 캐시 {len(out):,}건 "
              f"({(time.time() - os.path.getmtime(p)) / 3600:.0f}시간 전)")
        return out
    raw = fetch("corpCode.xml")
    root = ET.fromstring(zipfile.ZipFile(io.BytesIO(raw)).read("CORPCODE.xml").decode("utf-8"))
    out = {}
    for x in root.findall("list"):
        sc = (x.findtext("stock_code") or "").strip()
        if sc:
            out[sc] = x.findtext("corp_code").strip()
    with open(p, "w", encoding="utf-8") as f:
        json.dump(out, f)
    print(f"corp_code 매핑: 새로 받음 상장 {len(out):,}건 → {p}")
    return out


def num(v):
    """DART 금액 문자열 → float. 빈값·'-'는 None. 음수는 그냥 '-123' 으로 온다."""
    v = (v or "").strip().replace(",", "")
    if not v or v == "-":
        return None
    try:
        return float(v)
    except ValueError:
        return None


def statements(cc, year, reprt):
    """(fs_div, {개념: row}) — 연결(CFS) 우선, 없으면 별도(OFS).
    지주회사·일부 중소형은 연결을 안 내서, 이 폴백이 없으면 통째로 빠진다(실측 60종목 중 4)."""
    for div in ("CFS", "OFS"):
        # 요청 실패를 여기서 삼키면 '보고서가 없는 회사'와 구분이 안 된다 — 예외를 올려
        # main 이 실패로 세게 한다. (그 구분을 놓쳐서 야후 수집이 반쪽 난 적이 있다.)
        j = json.loads(fetch("fnlttSinglAcntAll.json", corp_code=cc, bsns_year=str(year),
                             reprt_code=reprt, fs_div=div))
        if j.get("status") != "000":
            continue
        picked = {}
        for key, ids in ACC.items():
            # 같은 account_id 가 BS/IS/CIS/CF/SCE 에 흩어져 있다. SCE(자본변동표)는 자본 항목이
            # 여러 줄로 쪼개져 나와서 그대로 집으면 자본총계가 엉뚱한 값이 된다 — 표를 못박는다.
            # 손익은 IS 를 먼저 보되 CIS 로 폴백한다. 손익계산서를 따로 내지 않고 '단일 포괄
            # 손익계산서'만 내는 회사가 꽤 있어서(SK하이닉스·KB금융·HD현대일렉트릭 등), IS 만
            # 보면 그 회사들이 통째로 '보고서 없음'으로 빠진다.
            want_sj = ("BS",) if key in BS_KEYS else ("IS", "CIS")
            for sj in want_sj:
                for aid in ids:
                    hit = [r for r in j["list"]
                           if r.get("account_id") == aid and r.get("sj_div") == sj]
                    if hit:
                        picked[key] = hit[0]
                        break
                if key in picked:
                    break
        return div, picked
    return None, None


def latest_report(cc, today):
    """가장 최근에 '실제로 올라와 있는' 정기보고서. 분기말이 지났어도 법정 기한(+45일)
    전이면 아직 없으므로, 최신부터 내려오며 처음 잡히는 걸 쓴다."""
    cands = []
    for y in (today.year, today.year - 1):
        for rc in ("11014", "11012", "11013", "11011"):
            m, d = QEND[rc]
            qend = date(y, m, d)
            if qend < today:
                cands.append((qend, y, rc))
    cands.sort(reverse=True)                 # 분기말이 늦은 것부터
    for qend, y, rc in cands[:5]:            # 5개까지만 — 그보다 오래됐으면 폐업 수준
        div, picked = statements(cc, y, rc)
        if div and picked.get("net_income") is not None:
            return qend, y, rc, div, picked
    return None, None, None, None, None


def ttm(cur_add, prev_add, annual):
    """최근 12개월 = 직전 연간 + 당기 누적 − 전년 동기 누적.
    누적치를 그대로 쓰면 1분기 보고서일 때 연간의 1/4이라 PER 이 4배로 부풀고, 4를 곱하면
    계절성이 큰 업종(조선·유통)이 통째로 왜곡된다. 사업보고서면 누적이 곧 연간이라 그대로."""
    if annual is None:
        return cur_add
    if cur_add is None or prev_add is None:
        return annual
    return annual + cur_add - prev_add


def snapshot(code, name, market, cc, today):
    qend, year, rc, div, cur = latest_report(cc, today)
    if not div:
        return None
    # 손익은 '당기 누적'(thstrm_add_amount)이 기준. 사업보고서는 그 칸이 비어 있어 thstrm_amount 로.
    def add(key):
        r = cur.get(key)
        if not r:
            return None
        return num(r.get("thstrm_add_amount")) if num(r.get("thstrm_add_amount")) is not None \
            else num(r.get("thstrm_amount"))

    def prev_add(key):
        r = cur.get(key)
        if not r:
            return None
        return num(r.get("frmtrm_add_amount")) if num(r.get("frmtrm_add_amount")) is not None \
            else num(r.get("frmtrm_q_amount"))

    def bs(key):
        r = cur.get(key)
        return num(r.get("thstrm_amount")) if r else None

    # TTM 을 만들려면 직전 사업보고서가 필요하다(분기보고서일 때만).
    annual = {}
    if rc != "11011":
        _d, prev = statements(cc, year - 1 if qend.month <= 3 else year, "11011")
        if not prev:                                  # 아직 안 나왔으면 그 전 해로
            _d, prev = statements(cc, year - 1, "11011")
        if prev:
            for k in ("revenue", "op_income", "net_income"):
                r = prev.get(k)
                annual[k] = num(r.get("thstrm_amount")) if r else None

    rev = ttm(add("revenue"), prev_add("revenue"), annual.get("revenue"))
    opi = ttm(add("op_income"), prev_add("op_income"), annual.get("op_income"))
    net = ttm(add("net_income"), prev_add("net_income"), annual.get("net_income"))
    assets, liab, eq = bs("assets"), bs("liabilities"), bs("equity")
    ca, cl, ppe = bs("cur_assets"), bs("cur_liabilities"), bs("ppe")

    def growth(key):
        """전년 '동기' 누적 대비. 야후 earningsGrowth 는 기저가 작으면 320배 같은 값이 나오는데,
        여기선 원본 두 숫자를 직접 나눈다. 기저가 적자면 성장률이 무의미해 None."""
        c, p = add(key), prev_add(key)
        if c is None or p is None or p <= 0:
            return None
        return c / p - 1

    # 그린블랫 원본: ROIC = EBIT ÷ (순운전자본 + 순고정자산). 한국 손익계산서의 영업이익이 곧 EBIT
    # 이고 재무상태표에 유동자산·유동부채·유형자산이 다 있어서, 미국처럼 근사할 필요가 없다.
    ic = None
    if None not in (ca, cl, ppe):
        ic = max(ca - cl, 0) + ppe                    # 순운전자본이 음수면 0 — 분모가 뒤집히면 순위가 거짓말이 된다
        # 투하자본이 자산 대비 지나치게 작으면 ROIC 이 폭발한다. 지주회사가 그렇다 —
        # 자회사 지분(투자자산)만 있고 영업용 자산이 없어서 분모가 잡음이 된다
        # (실측: SK스퀘어 984.8%). 미국판에서 ROE 를 버린 것과 같은 이유로, 여기선 값을 안 준다.
        if assets and ic < assets * 0.05:
            ic = None
    return {
        "code": code, "name": name, "market": market, "corp_code": cc,
        "fs_div": div, "reprt": rc, "bsns_year": year,
        "fiscal_q": qend.isoformat(), "rcept_no": cur.get("net_income", {}).get("rcept_no"),
        "revenue": rev, "op_income": opi, "net_income": net,
        "assets": assets, "liabilities": liab, "equity": eq,
        "cur_assets": ca, "cur_liabilities": cl, "ppe": ppe,
        "rev_growth": growth("revenue"), "earn_growth": growth("net_income"),
        "roe": (net / eq) if net is not None and eq else None,
        "roa": (net / assets) if net is not None and assets else None,
        "op_margin": (opi / rev) if opi is not None and rev else None,
        "profit_margin": (net / rev) if net is not None and rev else None,
        # 한국식 부채비율(총부채÷자본, %). 야후 debtToEquity 는 '총차입금' 기준이라 값이 다르다.
        "debt_ratio": (liab / eq * 100) if liab is not None and eq else None,
        "ebit": opi,
        "invested_capital": ic,
        "roic": (opi / ic) if opi is not None and ic else None,
    }


def rnd(v, n=6):
    if v is None:
        return None
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return round(f, n) if abs(f) < 1e15 else f


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry", action="store_true")
    ap.add_argument("--force", action="store_true",
                    help="오늘 이미 받은 종목도 다시 받는다 (기본은 건너뛰고 이어받기)")
    ap.add_argument("codes", nargs="*", help="지정 종목만 (디버깅)")
    a = ap.parse_args()
    if not KEY:
        print("DART_API_KEY 없음 — .env 에 넣어주세요 (opendart.fss.or.kr → 인증키 신청)")
        return

    rows, frm = [], 0
    while True:
        d = sb.table("stock_meta").select("code,name,market").range(frm, frm + 999).execute().data
        rows += d
        if len(d) < 1000:
            break
        frm += 1000
    uni = [r for r in rows if r["market"] in ("KOSPI", "KOSDAQ", "KONEX")]
    if a.codes:
        uni = [r for r in uni if r["code"] in a.codes]
    cmap = corp_map()

    def dart_code(code):
        """우선주는 DART 고유번호가 따로 없다 — 보통주와 같은 법인이 한 번만 공시하기 때문이다.
        한국 우선주 코드는 보통주 끝자리를 5/7/9 또는 K/L/M 으로 바꾼 것이라, 끝자리를 0으로
        되돌리면 보통주가 된다(005935→005930 삼성전자우, 00680K→006800 미래에셋증권우).
        이걸 안 하면 시총 상위 우선주 14종목이 통째로 빠진다."""
        return cmap.get(code) or cmap.get(code[:5] + "0")

    pref = [r["code"] for r in uni if r["code"] not in cmap and dart_code(r["code"])]
    miss = [r["code"] for r in uni if not dart_code(r["code"])]
    uni = [r for r in uni if dart_code(r["code"])]
    print(f"대상 {len(uni)}종목"
          + (f" · 우선주→보통주 매핑 {len(pref)}건" if pref else "")
          + (f" · corp_code 없음 {len(miss)}건 {miss[:5]}" if miss else ""))

    today = date.today()
    # 이어받기: 오늘 이미 채운 종목은 건너뛴다. DART 가 중간에 IP를 끊어도 다시 실행하면
    # 남은 것부터 이어가라는 뜻이다 — 500종목을 처음부터 다시 받으면 또 끊긴다.
    done = set()
    if not a.dry and not a.force:
        frm = 0
        while True:
            d = (sb.table("dart_fin").select("code,updated_at")
                 .gte("updated_at", today.isoformat()).range(frm, frm + 999).execute().data)
            done |= {x["code"] for x in d}
            if len(d) < 1000:
                break
            frm += 1000
        if done:
            uni = [r for r in uni if r["code"] not in done]
            print(f"  오늘 이미 받은 {len(done)}종목 건너뜀 → 남은 {len(uni)}종목")

    def flush(buf):
        if not buf:
            return
        now = datetime.now(timezone.utc).isoformat()
        payload = [{**{k: (rnd(v) if isinstance(v, float) else v) for k, v in s.items()},
                    "updated_at": now} for s in buf]
        sb.table("dart_fin").upsert(payload, on_conflict="code").execute()

    out, fail, buf, blocked = [], [], [], None
    t0 = time.time()
    try:
        with cf.ThreadPoolExecutor(max_workers=WORKERS) as ex:
            futs = {ex.submit(snapshot, r["code"], r["name"], r["market"],
                              dart_code(r["code"]), today): r for r in uni}
            for i, f in enumerate(cf.as_completed(futs), 1):
                r = futs[f]
                try:
                    s = f.result()
                except DartBlocked as e:
                    blocked = str(e)
                    for g in futs:                    # 막힌 뒤 남은 건 전부 실패할 뿐이다
                        g.cancel()
                    break
                except Exception as e:
                    fail.append(f"{r['code']}({str(e)[:30]})")
                    continue
                if s is None:
                    fail.append(f"{r['code']}(보고서없음)")
                    continue
                out.append(s)
                buf.append(s)
                # 50종목마다 바로 저장 — 중간에 끊겨도 거기까지는 남는다(krx.py 와 같은 방식)
                if not a.dry and len(buf) >= 50:
                    flush(buf)
                    buf = []
                    print(f"  {i}/{len(uni)} 적재 누적 {len(out)}  ({time.time() - t0:.0f}초)")
                elif i % 100 == 0:
                    print(f"  {i}/{len(uni)}  ({time.time() - t0:.0f}초)")
    finally:
        if not a.dry:
            flush(buf)
    print(f"수집 {len(out)}/{len(uni)}종목 · 실패 {len(fail)} ({time.time() - t0:.0f}초)")
    if fail:
        print("  실패:", ", ".join(fail[:10]) + (" …" if len(fail) > 10 else ""))
    if blocked:
        print(f"\n⚠️ DART 가 연결을 끊었습니다 ({blocked})")
        print("   IP 단위 차단이라 남은 종목도 전부 실패합니다. 여기까지는 저장됐으니,")
        print("   30분쯤 뒤 `python dart.py` 를 다시 돌리면 남은 종목부터 이어받습니다.")

    # 결측률 — 야후를 버린 이유가 결측이었으니, 여기서도 같은 잣대로 감시한다
    keys = ("roe", "roa", "op_margin", "profit_margin", "debt_ratio",
            "rev_growth", "earn_growth", "roic", "ebit")
    n = len(out) or 1
    print("  결측:", ", ".join(
        f"{k} {sum(1 for s in out if s[k] is None)}({sum(1 for s in out if s[k] is None) / n * 100:.0f}%)"
        for k in keys))
    fq = {}
    for s in out:
        fq[s["fiscal_q"]] = fq.get(s["fiscal_q"], 0) + 1
    print("  재무 기준 분기:", ", ".join(f"{k} {v}" for k, v in sorted(fq.items(), reverse=True)[:5]))
    print("  연결/별도:", {d: sum(1 for s in out if s["fs_div"] == d) for d in ("CFS", "OFS")})

    if a.dry:
        for s in sorted(out, key=lambda x: -(x["net_income"] or 0))[:10]:
            print(f"    {s['name'][:14]:<16} {REPRT[s['reprt']]:<6} {s['fiscal_q']} "
                  f"ROE {(s['roe'] or 0) * 100:5.1f}% · ROIC {(s['roic'] or 0) * 100:6.1f}% · "
                  f"부채비율 {(s['debt_ratio'] or 0):5.0f}%")
        print(f"\n[dry] 적재 건너뜀 ({len(out)}행)")
        return
    # 적재는 위 루프의 flush() 가 50종목마다 이미 끝냈다 — 여기서 다시 쓰지 않는다
    tot = sb.table("dart_fin").select("code", count="exact").limit(1).execute().count
    print(f"dart_fin: 이번 실행 {len(out)}행 적재 · 테이블 총 {tot}행")


if __name__ == "__main__":
    main()
