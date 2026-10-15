# fin_archive.py — 점수 검증용 과거 분기 재무(2015~) → .cache/fin_archive.jsonl (끝나면 Storage 보관)
#
# 왜 따로 받나: 라이브 fin_q(DB)는 '지금 유니버스 · 2023 이후'뿐이다. 점수를 과거로 검증하려면 매 시점의
# 유니버스 — 그때 크기 기준을 통과했고 나중에 상장폐지된 종목까지 — 의 재무가 필요하다(생존편향 차단).
# 크기 기준을 통과한 적 있는 2,856종목 전부(폐지 281 포함)가 DART 고유번호로 찾아진다(2026-10-15 확인).
#
# DB 에는 넣지 않는다 — 8만 행이면 무료 한도를 먹는다. 로컬 jsonl 에 한 줄씩 이어 붙이고(중간에 끊겨도
# 그대로 남는다) 끝나면 csv.gz 로 묶어 Storage 에 둔다(archive.py 와 같은 방식).
# 해석은 fin_hist.report 를 그대로 쓴다 — 라이브 점수와 검증 점수의 정의가 한 글자라도 다르면 검증이 아니다.
#
# 받는 범위: 크기 기준(시총 500억·거래대금 5억)을 통과한 분기의 7분기 전부터 마지막 통과 분기까지.
#   점수 첫 분기에 '최근 4분기 합의 전년 대비'를 계산하려면 그 앞 8분기가 있어야 한다.
# DART 하루 2만 건 한도 — 걸리면 멈추고, 다음 날 다시 돌리면 이어서 받는다. 최근 분기부터 거꾸로 받아서
#   하루치만으로도 최근 몇 년은 먼저 검증해 볼 수 있다.
#
# 실행:  python fin_archive.py          → 이어받기
#        python fin_archive.py --pack   → jsonl → csv.gz 묶어 Storage 업로드
import argparse
import json
import os
import sys
import time
from datetime import datetime, timezone

import archive
import fin_hist
from dart import sb, corp_map, DartBlocked
from fin_hist import DailyLimit, report, HOLDING
from fin_score import load

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

ROOT = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(ROOT, ".cache", "fin_archive.jsonl")
MISS = os.path.join(ROOT, ".cache", "fin_archive_miss.jsonl")   # 보고서가 없던 종목-분기 — 다시 묻지 않게
Q_REPRT = {0: "11013", 1: "11012", 2: "11014", 3: "11011"}     # 분기 번호 % 4 → 보고서 코드
Q_END = {0: "03-31", 1: "06-30", 2: "09-30", 3: "12-31"}
FIRST_Q, LAST_Q = 2015 * 4, 2026 * 4 + 1                      # 2015 1분기 ~ 2026 2분기


def qi_of(fq):
    return int(fq[:4]) * 4 + (int(fq[5:7]) - 1) // 3


def needed():
    """(종목, 분기번호) 집합 + 종목 이름. pit_monthly 보관 파일이 그 시점 유니버스의 출처."""
    df = archive.load_pit_archive()
    df = df[df["code"].str.endswith("0") & df["market"].isin(["KOSPI", "KOSDAQ"])].copy()
    df["qi"] = df["ym"].str[:4].astype(int) * 4 + (df["ym"].str[5:7].astype(int) - 1) // 3
    big = df[(df["mktcap"] >= fin_hist.MIN_CAP) & (df["tval_avg"] >= fin_hist.MIN_TVAL)]
    listed = df.groupby("code")["qi"].agg(["min", "max"])
    names = df.sort_values("ym").groupby("code")["name"].last().to_dict()
    need = set()
    for c, r in big.groupby("code")["qi"].agg(["min", "max"]).iterrows():
        lo = max(FIRST_Q, r["min"] - 7, listed.loc[c, "min"])
        need |= {(c, q) for q in range(lo, min(LAST_Q, r["max"]) + 1)}
    return need, names


def done_set():
    have = {(x["code"], qi_of(x["fiscal_q"])) for x in load("fin_q", "code,fiscal_q")}
    for p in (OUT, MISS):
        if os.path.exists(p):
            with open(p, encoding="utf-8") as f:
                for ln in f:
                    j = json.loads(ln)
                    have.add((j["code"], qi_of(j["fiscal_q"])))
    return have


def collect():
    need, names = needed()
    todo = sorted(need - done_set(), key=lambda x: (-x[1], x[0]))      # 최근 분기부터
    codes = sorted({c for c, _ in todo})
    cmap = corp_map()
    info = fin_hist.corp_info([{"code": c, "name": names.get(c, c)} for c in codes], cmap)
    skip = {c for c in codes if (info.get(c) or {}).get("fin_kind") in ("financial", "non_dec_fy", "fin_holding")}
    todo = [(c, q) for c, q in todo if c not in skip and cmap.get(c)]
    print(f"받을 종목-분기 {len(todo):,} (금융·12월결산아님 {len(skip)}종목 제외) · 최근 분기부터")
    t0, n_ok, n_miss, fin_hold = time.time(), 0, 0, set()
    with open(OUT, "a", encoding="utf-8") as fo, open(MISS, "a", encoding="utf-8") as fm:
        try:
            for i, (c, q) in enumerate(todo, 1):
                cc = cmap[c]
                if cc in fin_hold:
                    continue
                y, k = divmod(q, 4)
                fq = f"{y}-{Q_END[k]}"
                div, v, rno = report(cc, y, Q_REPRT[k])
                if div is None:
                    fm.write(json.dumps({"code": c, "fiscal_q": fq}) + "\n")
                    n_miss += 1
                    continue
                if (info.get(c) or {}).get("induty_code") == HOLDING and v["cur_assets"] is None:
                    fin_hold.add(cc)                   # 금융지주 — fin_hist 와 같은 판정
                    sb.table("dart_corp").update({"fin_kind": "fin_holding"}).eq("corp_code", cc).execute()
                    continue
                row = {"code": c, "fiscal_q": fq, "bsns_year": y, "reprt": Q_REPRT[k], "corp_code": cc,
                       "fs_div": div, "rcept_no": rno,
                       "rcept_dt": f"{rno[:4]}-{rno[4:6]}-{rno[6:8]}" if rno else None, **v}
                fo.write(json.dumps(row, ensure_ascii=False) + "\n")
                n_ok += 1
                if i % 500 == 0:
                    fo.flush(); fm.flush()
                    el = time.time() - t0
                    print(f"  {i:,}/{len(todo):,} · 받음 {n_ok:,} · 없음 {n_miss:,} · {fq} · {el / 60:.0f}분 "
                          f"(오늘 한도까지 남은 ~{(19000 - i) / (i / el) / 60:.0f}분)", flush=True)
        except DailyLimit as e:
            print(f"⚠️ DART 하루 한도 — 내일 다시 돌리면 이어받습니다 ({e})")
        except DartBlocked as e:
            print(f"⚠️ DART 연결 끊김 — 30분 뒤 다시 돌리면 이어받습니다 ({e})")
    print(f"이번 실행: 받음 {n_ok:,} · 보고서 없음 {n_miss:,} · {(time.time() - t0) / 60:.0f}분")


def pack():
    """jsonl → csv.gz → Storage. 다 받은 뒤 한 번."""
    import pandas as pd
    rows = [json.loads(l) for l in open(OUT, encoding="utf-8")]
    df = pd.DataFrame(rows).drop_duplicates(["code", "fiscal_q"], keep="last")
    p = os.path.join(ROOT, "archive", "fin_archive.csv.gz")
    os.makedirs(os.path.dirname(p), exist_ok=True)
    df.to_csv(p, index=False, compression="gzip")
    raw = open(p, "rb").read()
    sb.storage.from_(archive.BUCKET).upload("fin_archive.csv.gz", raw, {"content-type": "application/gzip", "upsert": "true"})
    print(f"보관: {len(df):,}행 · {len(raw) / 1e6:.1f}MB → Storage archive/fin_archive.csv.gz")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--pack", action="store_true")
    a = ap.parse_args()
    pack() if a.pack else collect()
