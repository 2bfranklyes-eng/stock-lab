# archive.py — 화면에서 안 쓰는 큰 테이블을 DB 밖(파일)으로 옮겨 보관한다
#
# 왜: Supabase 무료 DB 한도는 500MB인데 2026-10-14 실측이 476MB였다(연 ~70MB씩 는다).
# pit_monthly(54MB, 2015-01~)는 factor.py 로 연구할 때만 읽고 화면은 안 쓴다 — DB에 둘 이유가 없다.
# 보관처는 두 곳이다: 이 PC의 archive/ (gitignore) + Supabase Storage 'archive' 버킷(비공개).
# Storage 는 DB 한도와 별개인 1GB 무료 공간이라, PC 를 잃어도 여기서 다시 받는다.
#
# ⚠️ 행을 DELETE 해서는 DB 크기가 줄지 않는다 — 빈자리가 그 테이블의 재사용분으로 남을 뿐이다.
#    보관을 검증한 뒤 SQL Editor 에서 TRUNCATE 해야 실제로 비워진다.
#    그 뒤로 krx.py 는 매달 새 달만 pit_monthly 에 쌓고, 읽는 쪽(factor.py)이 파일 + DB 를 합친다.
#
# 형식이 parquet 가 아니라 csv.gz 인 이유: pyarrow 의존성을 늘리지 않으려는 것뿐이다(33만 행 ≈ 10MB).
#
# 실행:  python archive.py pit_monthly   → 내보내기 + 검증 + Storage 업로드 (DB 는 안 건드린다)
import csv
import gzip
import hashlib
import os
import sys

from dotenv import load_dotenv
from supabase import create_client

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

ROOT = os.path.dirname(os.path.abspath(__file__))
load_dotenv(os.path.join(ROOT, ".env"))
sb = create_client(os.environ["SUPABASE_URL"], os.environ["SUPABASE_SERVICE_KEY"])

BUCKET = "archive"
DIR = os.path.join(ROOT, "archive")
PIT_FILE = "pit_monthly.csv.gz"
PIT_COLS = ["code", "ym", "name", "market", "close", "mktcap", "shares", "tval_avg", "vol", "n_days"]
# read_csv 가 종목코드 '095570' 을 숫자 95570 으로 읽으면 앞자리 0이 사라진다 — 글자 열은 못박는다
PIT_STR = {"code": str, "ym": str, "name": str, "market": str}


def _local(name):
    return os.path.join(DIR, name)


def _ensure_local(name):
    """PC에 없으면 Storage 에서 받아 둔다. 새 PC·CI 에서도 같은 코드로 읽히게."""
    path = _local(name)
    if not os.path.exists(path):
        os.makedirs(DIR, exist_ok=True)
        with open(path, "wb") as f:
            f.write(sb.storage.from_(BUCKET).download(name))
    return path


def load_pit_archive():
    """보관된 pit_monthly (DataFrame). ym 은 'YYYY-MM' 문자열 그대로 둔다 — 형 변환은 쓰는 쪽 몫."""
    import pandas as pd
    return pd.read_csv(_ensure_local(PIT_FILE), dtype=PIT_STR)


def pit_archived_months():
    """보관 파일에 든 달 목록 {'2015-01', …}. krx.py 가 pandas 없이 쓰도록 csv 로 읽는다."""
    with gzip.open(_ensure_local(PIT_FILE), "rt", encoding="utf-8", newline="") as f:
        return {r["ym"] for r in csv.DictReader(f)}


def _fetch_all(table, cols, order):
    rows, off = [], 0
    while True:
        q = sb.table(table).select(",".join(cols))
        for c in order:
            q = q.order(c)
        d = q.range(off, off + 999).execute().data
        rows += d
        off += 1000
        if len(rows) % 50000 < 1000:
            print(f"  {len(rows):,}행", flush=True)
        if len(d) < 1000:
            return rows


def _same(a, b):
    """두 DataFrame 이 값까지 같은가. 실수는 csv 왕복 반올림만 허용(상대 1e-12)."""
    import numpy as np
    if a.shape != b.shape or list(a.columns) != list(b.columns):
        return False
    for c in a.columns:
        x, y = a[c].to_numpy(), b[c].to_numpy()
        if a[c].dtype.kind in "fi":
            if not np.allclose(x.astype(float), y.astype(float), rtol=1e-12, atol=0, equal_nan=True):
                return False
        elif not (a[c].fillna("").astype(str).to_numpy() == b[c].fillna("").astype(str).to_numpy()).all():
            return False
    return True


def archive_pit():
    import pandas as pd
    n_db = sb.table("pit_monthly").select("code", count="exact", head=True).execute().count
    print(f"pit_monthly 내보내기 — DB {n_db:,}행")
    df = pd.DataFrame(_fetch_all("pit_monthly", PIT_COLS, ["code", "ym"]), columns=PIT_COLS)

    # ① 빠짐없이 받았나 — 페이지를 넘기다 한 장이라도 놓치면 개수가 어긋난다
    assert len(df) == n_db, f"행 수 불일치: 받은 {len(df):,} vs DB {n_db:,}"
    assert not df.duplicated(["code", "ym"]).any(), "(code, ym) 중복"

    os.makedirs(DIR, exist_ok=True)
    path = _local(PIT_FILE)
    df.to_csv(path, index=False, compression="gzip")

    # ② 파일로 쓴 게 그대로 읽히나 — 종목코드 앞자리 0, NaN, 실수 자릿수
    back = pd.read_csv(path, dtype=PIT_STR)
    assert _same(df, back), "csv.gz 왕복 후 값이 달라짐"

    # ③ 예전에 따로 받아 둔 factor.py 캐시와 겹치는 구간이 같은가 — 독립된 두 번의 다운로드 대조
    cache = os.path.join(ROOT, "factor_cache.pkl")
    if os.path.exists(cache):
        old = pd.read_pickle(cache)
        old["ym"] = old["ym"].astype(str)
        cur = back[back["ym"] <= old["ym"].max()].sort_values(["code", "ym"]).reset_index(drop=True)
        old = old[PIT_COLS].sort_values(["code", "ym"]).reset_index(drop=True)
        print(f"  factor_cache.pkl 대조(~{old['ym'].max()}): "
              f"{'일치' if _same(cur, old) else '불일치 — 확인 필요'} ({len(old):,}행)")

    # ④ Storage 에 올리고 도로 받아 바이트 단위로 같은지
    raw = open(path, "rb").read()
    if BUCKET not in {b.name for b in sb.storage.list_buckets()}:
        sb.storage.create_bucket(BUCKET, options={"public": False})
    sb.storage.from_(BUCKET).upload(PIT_FILE, raw, {"content-type": "application/gzip", "upsert": "true"})
    got = sb.storage.from_(BUCKET).download(PIT_FILE)
    assert hashlib.sha256(got).hexdigest() == hashlib.sha256(raw).hexdigest(), "Storage 왕복 불일치"

    print(f"보관 완료: {len(df):,}행 {df['ym'].min()}~{df['ym'].max()} · {len(raw)/1e6:.1f}MB")
    print(f"  PC      {path}")
    print(f"  Storage {BUCKET}/{PIT_FILE}")
    print("이제 SQL Editor 에서:  truncate table public.pit_monthly;")


if __name__ == "__main__":
    if sys.argv[1:] == ["pit_monthly"]:
        archive_pit()
    else:
        print("사용법: python archive.py pit_monthly")
