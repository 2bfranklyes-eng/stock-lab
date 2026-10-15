# report_text.py — 정기보고서 본문 → 'AI가 읽을 묶음'(packet) (사업보고서 점검 2단계)
#
# 원칙: 숫자는 코드, 해석은 AI. 그런데 보고서 본문은 한 건에 6MB(텍스트 36만 자)라 통째로 읽히면
# 200종목 × 분기마다 비용과 시간이 감당이 안 된다. 그래서 코드가 먼저 줄인다:
#   · II. 사업의 내용 1~7절, IV. 경영진단, XI-4. 작성기준일 이후 주요사항만 자른다(절 식별자 AASSOCNOTE 로)
#   · 전 분기 보고서의 같은 절과 비교해 '새로 생긴 문장'만 남긴다 — 숫자를 # 로 가리고 비교하므로
#     숫자만 바뀐 상투 문장은 빠지고 표현이 바뀐 문장만 남는다
#   · 다만 4절(매출 및 수주상황)은 숫자 자체가 핵심이라 두 분기 모두 통째로 싣는다
# 원문은 DB 에 넣지 않는다(.cache/docs 에만). 묶음은 .cache/packets/<분기>/<종목>.md.
#
# 실행:  python report_text.py --fq 2026-06-30 005930 329180 …
import argparse
import html
import io
import os
import re
import sys
import zipfile
from collections import Counter

import dart
from dart import sb

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

ROOT = os.path.dirname(os.path.abspath(__file__))
DOCS = os.path.join(ROOT, ".cache", "docs")
PACK = os.path.join(ROOT, ".cache", "packets")
FULL_MAX = 9000          # 4절 통째 싣기 상한(자) — 거대 기업은 표가 수만 자라 앞부분만
DIFF_MAX = 5000          # 절마다 '새 문장' 상한(자)
SECTS = [                # (키, 식별자 정규식, 제목) — 식별자가 없는 옛 서식은 제목으로 폴백
    ("II.1", r"L-0-2-1-", "1. 사업의 개요"), ("II.2", r"L-0-2-2-", "2. 주요 제품 및 서비스"),
    ("II.3", r"L-0-2-3-", "3. 원재료 및 생산설비"), ("II.4", r"L-0-2-4-", "4. 매출 및 수주상황"),
    ("II.5", r"L-0-2-5-", "5. 위험관리 및 파생거래"), ("II.6", r"L-0-2-6-", "6. 주요계약 및 연구개발활동"),
    ("II.7", r"L-0-2-7-", "7. 기타 참고사항"), ("IV", r"D-0-4-0-0", "IV. 이사의 경영진단 및 분석의견"),
    ("XI.4", r"D-0-11-4-0", "작성기준일 이후 발생한 주요사항"),
]


def doc(rno):
    """원문 XML (캐시). zip 안에 감사보고서 등 첨부가 같이 오므로 가장 큰 파일이 본문이다."""
    os.makedirs(DOCS, exist_ok=True)
    p = os.path.join(DOCS, f"{rno}.xml")
    if not os.path.exists(p):
        z = zipfile.ZipFile(io.BytesIO(dart.fetch("document.xml", rcept_no=rno)))
        main = max(z.namelist(), key=lambda n: z.getinfo(n).file_size)
        with open(p, "wb") as f:
            f.write(z.read(main))
    with open(p, encoding="utf-8", errors="ignore") as f:
        return f.read()


def sections(x):
    """{키: 원문 조각}. SECTION-1/2 시작 위치를 다 찾고, 다음 같은·상위 단계 시작까지를 한 절로 본다."""
    starts = [(m.start(), int(m.group(1)), m.group(2), re.sub(r"<[^>]+>|\s+", " ", m.group(3)).strip())
              for m in re.finditer(r"<SECTION-(\d)[^>]*>\s*<TITLE([^>]*)>(.*?)</TITLE>", x, re.S)]
    out = {}
    for i, (pos, lv, attr, title) in enumerate(starts):
        end = next((p for p, l, _, _ in starts[i + 1:] if l <= lv), len(x))
        for key, aid, ttl in SECTS:
            if key in out:
                continue
            if re.search(r'AASSOCNOTE="' + aid, attr) or (ttl in title and (key.startswith("II.") is False or lv == 2)):
                out[key] = x[pos:end]
    return out


def lines(chunk):
    """원문 조각 → 문장·표 행 목록. 표는 '칸 | 칸 | 칸' 한 줄로."""
    # 원문 줄바꿈은 뜻이 없다 — 칸(<TD>) 사이에도 들어 있어서, 그대로 줄을 나누면 표 한 행이 칸마다
    # 흩어지고 한 글자 칸(한 자리 숫자)은 짧은 줄 필터에 걸려 사라졌다(실측: 지앤비에스 에코 'SEMI','71','108'…).
    # 줄은 아래에서 우리가 정한 경계(</TR>·</P>·<BR>)로만 나눈다. 칸 안의 문단은 한 칸으로 붙인다.
    t = re.sub(r"\s*\n\s*", " ", chunk)
    t = re.sub(r"<TR[^>]*>.*?</TR>", lambda m: re.sub(r"</P>|<BR\s*/?>", " ", m.group(0)), t, flags=re.S)
    t = re.sub(r"</T[DHEU]>", " | ", t)
    t = re.sub(r"</TR>|</P>|<BR\s*/?>|</TITLE>", "\n", t)
    # 태그만 지운다 — 보고서는 제품·게임명을 꺾쇠로 감싸 쓴다(<서브노티카2>). 그것까지 태그로 보고 지우면
    # 이름이 통째로 사라진다(실측: 크래프톤 "2026년 5월 는 Early Access"). 진짜 태그는 영문자로 시작한다.
    t = html.unescape(re.sub(r"</?[A-Za-z!?][^>]*>", " ", t))
    out = []
    for ln in t.split("\n"):
        ln = re.sub(r"[ \t　]+", " ", ln).strip(" |")
        if len(ln) < 2:
            continue
        # 문단은 문장으로 쪼갠다(표 행은 그대로). 문단 단위로 비교하면 한 문장만 바뀌어도 문단 전체가
        # '새 문장'으로 나와서, 읽는 쪽이 무엇이 새것인지 가릴 수 없다 — 실측: HD현대중공업 반기 문단에서
        # 회사명 표기(MAN ES→Everllence)와 새로 생긴 '데이터센터 전력용 문의 증가'가 한 덩어리로 섞여
        # 요약이 새 사실을 빼먹었다.
        parts = [ln] if " | " in ln else re.split(r"(?<=다\.)\s*|(?<=[.!?])\s+(?=[가-힣A-Z<(\[])", ln)
        out += [p.strip() for p in parts if len(p.strip()) >= 2]
    return out


def mask(s):
    return re.sub(r"\d[\d,.]*", "#", s)


def new_lines(cur, prev):
    """전 분기에 없던 문장(숫자를 가리고 비교). 같은 문장이 여러 번 나오면 개수까지 맞춘다."""
    seen = Counter(mask(l) for l in prev)
    out = []
    for l in cur:
        k = mask(l)
        if seen[k] > 0:
            seen[k] -= 1
        elif re.sub(r"[#|\s\-.,()%]", "", k):    # 숫자·기호만 남는 표 행은 빼고
            out.append(l)
    return out


def clip(ls, limit):
    s, n = [], 0
    for l in ls:
        if n + len(l) > limit:
            s.append(f"… (이하 {len(ls) - len(s)}줄 생략)")
            break
        s.append(l)
        n += len(l) + 1
    return "\n".join(s)


def packet(code, fq):
    """한 종목·한 분기 묶음을 만든다. 직전 분기 보고서와 비교 — 1분기는 직전 사업보고서와."""
    rows = sb.table("fin_q").select("fiscal_q,rcept_no,rcept_dt,reprt").eq("code", code).order("fiscal_q").execute().data
    idx = next((i for i, r in enumerate(rows) if r["fiscal_q"] == fq), None)
    if idx is None or idx == 0:
        return None, "비교할 직전 보고서 없음"
    cur, prev = rows[idx], rows[idx - 1]
    name = (sb.table("dart_corp").select("name").eq("code", code).execute().data or [{"name": code}])[0]["name"]
    cs, ps = sections(doc(cur["rcept_no"])), sections(doc(prev["rcept_no"]))
    rv = (sb.table("review").select("checks").eq("code", code).eq("fiscal_q", fq).execute().data or [{}])[0]
    out = [f"# {name} ({code}) — {fq} 보고서 점검 묶음",
           f"- 이번: {cur['fiscal_q']} 보고서 (공시 {cur['rcept_dt']}, rcept_no {cur['rcept_no']})",
           f"- 비교: {prev['fiscal_q']} 보고서 (공시 {prev['rcept_dt']}, rcept_no {prev['rcept_no']})"]
    if rv.get("checks"):
        out.append("\n## 숫자 자동 체크 (코드가 계산함)")
        out += [f"- [{c['result']}] {c['rule']}: {c['value']} {c.get('note') or ''}".rstrip() for c in rv["checks"]]
    for key, _, ttl in SECTS:
        c, p = lines(cs.get(key, "")), lines(ps.get(key, ""))
        if not c:
            out.append(f"\n## {key} {ttl}\n(이번 보고서에 이 절이 없거나 비어 있음)")
            continue
        if key == "II.4":
            out.append(f"\n## {key} {ttl} — 이번 분기 전문")
            out.append(clip(c, FULL_MAX))
            out.append(f"\n## {key} {ttl} — 직전 분기 전문 (숫자 비교용)")
            out.append(clip(p, FULL_MAX) if p else "(직전 보고서에 없음)")
            continue
        nl = new_lines(c, p)
        if p and not nl:
            continue                            # 바뀐 문장이 없으면 절을 통째로 생략
        out.append(f"\n## {key} {ttl} — {'전 분기 대비 새로 생기거나 바뀐 문장' if p else '이번 분기 전문(직전에 없던 절)'}")
        out.append(clip(nl if p else c, DIFF_MAX))
    return "\n".join(out), None


def todo(fq, n, redo=False):
    """아직 AI 요약이 없는 관심종목(제외 빼고)을 점수 순위대로 n개. 그 분기 보고서가 있는 종목만.
    redo=True 면 DB 대신 이번에 새로 쓴 요약 파일(.cache/summaries/<분기>/)로 '끝남'을 센다 — 추출기를 고친 뒤
    전부 다시 만들 때 쓴다(DB 의 옛 요약은 새 것이 덮어쓸 때까지 화면에 남아 있게)."""
    from fin_score import load
    rank = {r["code"]: r["rank"] or 9999 for r in load("fin_score", "code,rank")}
    if redo:
        d = os.path.join(ROOT, ".cache", "summaries", fq)
        done = {f[:6] for f in os.listdir(d) if f.endswith(".json")} if os.path.isdir(d) else set()
    else:
        done = {r["code"] for r in load("review", "code,summary", fiscal_q=fq) if r.get("summary")}
    has = {r["code"] for r in load("fin_q", "code", fiscal_q=fq)}
    w = [x["code"] for x in load("watch", "code,status") if x["status"] != "drop"]
    return sorted([c for c in w if c not in done and c in has], key=lambda c: rank.get(c, 9999))[:n]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--fq", required=True)
    ap.add_argument("--todo", type=int, default=0, help="요약이 아직 없는 관심종목을 순위대로 n개")
    ap.add_argument("--redo", action="store_true", help="--todo 를 요약 파일 기준으로 센다(전부 다시 만들 때)")
    ap.add_argument("codes", nargs="*")
    a = ap.parse_args()
    if a.todo:
        a.codes = todo(a.fq, a.todo, a.redo)
        print("대상:", " ".join(a.codes))
    d = os.path.join(PACK, a.fq)
    os.makedirs(d, exist_ok=True)
    for code in a.codes:
        try:
            txt, why = packet(code, a.fq)
        except dart.DartBlocked as e:
            print(f"⚠️ DART 차단 — 중단: {e}")
            break
        if not txt:
            print(f"  {code}: 건너뜀 ({why})")
            continue
        with open(os.path.join(d, f"{code}.md"), "w", encoding="utf-8") as f:
            f.write(txt)
        print(f"  {code}: {len(txt):,}자")


if __name__ == "__main__":
    main()
