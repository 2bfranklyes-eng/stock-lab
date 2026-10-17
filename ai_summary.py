# ai_summary.py — 분기 점검 AI 요약을 Claude API 로 (사업보고서 점검 2단계 자동화)
#
# 지금까지는 대화창의 Claude Code 가 보조 에이전트를 띄워 했던 일(묶음 읽기 → 요약 JSON 쓰기)을 코드로 옮긴 것.
# 지침은 prompts/review_summary.md 의 <!-- api --> 구간을 그대로 쓴다 — 에이전트 방식과 규칙이 갈라지지 않게.
# 결과는 review.check_summary 로 다시 검증하고, 통과한 것만 .cache/summaries/<분기>/ 에 쓴다(적재는 review.py load).
#
# 배치 API(요금 50% 할인, 보통 1시간 안에 끝남)가 기본. 배치 번호를 .cache/ai_batches/ 에 적어 두므로
# 기다리다 끊겨도 `--collect` 로 결과만 다시 받는다(같은 요청을 두 번 보내 돈을 두 번 쓰지 않게).
# ANTHROPIC_API_KEY 가 없으면 아무것도 안 하고 끝난다 — 키를 넣기 전에도 크론이 깨지지 않게.
#
# 실행:  python ai_summary.py --fq 2026-09-30 --todo 200        → 요약 없는 관심종목 순위대로, 배치
#        python ai_summary.py --fq 2026-06-30 --now 005930 …     → 몇 종목만 바로(할인 없음, 시험용)
#        python ai_summary.py --fq 2026-09-30 --dry --todo 200   → 보내지 않고 글자 수·예상 비용만
#        python ai_summary.py --fq 2026-09-30 --collect          → 마지막 배치 결과 다시 받기
#        python ai_summary.py --fq auto --todo 250 --load         → 크론: 직전 분기, 새로 나온 보고서만
#        … --load 를 붙이면 끝난 뒤 review.py load 까지
import argparse
import json
import os
import re
import sys
import time
from types import SimpleNamespace

from dotenv import load_dotenv

ROOT = os.path.dirname(os.path.abspath(__file__))
load_dotenv(os.path.join(ROOT, ".env"))

import report_text
import review

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

MODEL = "claude-sonnet-5-5"          # 2026-10-15 시범: 같은 종목에서 Opus 와 품질 동등 이상
PRICE = (2.0, 10.0)                  # 입력·출력 $/100만 토큰(Sonnet 5.5). 배치는 절반
MAX_TOKENS = 16000                   # 생각(adaptive thinking) 포함 상한 — 답 JSON 자체는 2~3천 토큰
PROMPT = os.path.join(ROOT, "prompts", "review_summary.md")
WAIT_MAX = 5 * 3600                  # GitHub 잡은 6시간에 끊긴다 — 배치는 보통 1시간 안
BATCHES = os.path.join(ROOT, ".cache", "ai_batches")


def auto_fq():
    """오늘 직전 분기말. 보고서는 그 뒤 45~90일에 걸쳐 나오고, todo 가 '그 분기 재무가 들어온 종목'만 고르므로
    토요일마다 돌리면 그 주에 새로 나온 회사만 조금씩 요약된다."""
    t = time.localtime()
    q = (t.tm_mon - 1) // 3
    y = t.tm_year if q else t.tm_year - 1
    return f"{y}-{['12-31', '03-31', '06-30', '09-30'][q]}"


def system_prompt(fq):
    s = open(PROMPT, encoding="utf-8").read()
    parts = re.findall(r"<!-- api -->\n(.*?)<!-- /api -->", s, re.S)
    assert len(parts) == 2, "review_summary.md 의 <!-- api --> 구간이 바뀌었다"
    return ("You summarize Korean company quarterly-report packets for a personal stock-research app.\n\n"
            + "\n".join(parts).replace("{FQ}", fq)
            + "\nReply with ONLY the JSON object — no code fences, no other text.")


def packets(fq, codes):
    """묶음 파일이 없으면 report_text 로 만든다(크론에서는 매번 새로). {종목: 본문}."""
    d = os.path.join(report_text.PACK, fq)
    os.makedirs(d, exist_ok=True)
    out = {}
    for c in codes:
        p = os.path.join(d, f"{c}.md")
        if not os.path.exists(p):
            txt, why = report_text.packet(c, fq)
            if not txt:
                print(f"  {c}: 묶음 없음 ({why})")
                continue
            open(p, "w", encoding="utf-8").write(txt)
        out[c] = open(p, encoding="utf-8").read()
    return out


def params(fq, code, txt):
    return {"model": MODEL, "max_tokens": MAX_TOKENS, "system": system_prompt(fq),
            "messages": [{"role": "user", "content": f"code {code}, fiscal_q {fq}\n\n{txt}"}]}


def save(fq, code, msg, tally, out):
    """답 하나 → 검증 → 파일. 실패 사유는 tally 에."""
    u = msg.usage
    tally["in"] += u.input_tokens
    tally["out"] += u.output_tokens
    text = "".join(b.text for b in msg.content if b.type == "text")
    m = re.search(r"\{.*\}", text, re.S)
    try:
        j = json.loads(m.group(0)) if m else None
    except ValueError:
        j = None
    if j is None:
        tally["bad"].append(f"{code} JSON 아님 (stop={msg.stop_reason})")
        return
    errs, warns = review.check_summary(j, code)
    if errs:
        tally["bad"].append(f"{code} {', '.join(errs)}")
        return
    for w in warns:
        print(f"  ⚠️ {code}: {w}")
    os.makedirs(out, exist_ok=True)
    with open(os.path.join(out, f"{code}.json"), "w", encoding="utf-8") as f:
        json.dump(j, f, ensure_ascii=False, indent=1)
    tally["ok"] += 1


def report(tally, batch):
    cost = (tally["in"] * PRICE[0] + tally["out"] * PRICE[1]) / 1e6 * (0.5 if batch else 1)
    print(f"요약 {tally['ok']}건 저장 · 거부 {len(tally['bad'])}건 · 토큰 입력 {tally['in']:,} 출력 {tally['out']:,}"
          f" · 약 ${cost:.2f}{' (배치 50%)' if batch else ''}")
    for x in tally["bad"]:
        print("  ✕", x)


def run_now(client, fq, pk, out):
    tally = {"ok": 0, "bad": [], "in": 0, "out": 0}
    for code, txt in pk.items():
        with client.messages.stream(**params(fq, code, txt)) as s:
            save(fq, code, s.get_final_message(), tally, out)
        print(f"  {code} 끝")
    report(tally, False)


def collect(client, fq, out, bid=None):
    if bid is None:
        bid = json.load(open(os.path.join(BATCHES, f"{fq}.json")))["id"]
    t0 = time.time()
    while True:
        b = client.messages.batches.retrieve(bid)
        if b.processing_status == "ended":
            break
        rc = b.request_counts
        print(f"  배치 {bid[-8:]} 처리 중 {rc.processing} · 끝 {rc.succeeded + rc.errored}", flush=True)
        if time.time() - t0 > WAIT_MAX:
            print(f"⚠️ {WAIT_MAX // 3600}시간 넘게 안 끝남 — 나중에 --collect 로 받으세요 (배치 {bid})")
            sys.exit(1)
        time.sleep(60)
    tally = {"ok": 0, "bad": [], "in": 0, "out": 0}
    for r in client.messages.batches.results(bid):
        if r.result.type == "succeeded":
            save(fq, r.custom_id, r.result.message, tally, out)
        else:
            tally["bad"].append(f"{r.custom_id} 배치 {r.result.type}")
    report(tally, True)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--fq", required=True, help="분기말(예 2026-09-30) 또는 auto")
    ap.add_argument("--todo", type=int, default=0, help="요약 없는 관심종목을 순위대로 n개")
    ap.add_argument("--now", action="store_true", help="배치 대신 바로(시험용, 할인 없음)")
    ap.add_argument("--dry", action="store_true", help="보내지 않고 크기·예상 비용만")
    ap.add_argument("--collect", action="store_true", help="마지막 배치 결과만 다시 받기")
    ap.add_argument("--load", action="store_true", help="끝나면 review.py load 까지")
    ap.add_argument("--out", help="저장 폴더 이름(기본 분기말) — 시험 때 기존 요약을 덮지 않게, 예 2026-06-30-api")
    ap.add_argument("codes", nargs="*")
    a = ap.parse_args()
    if a.fq == "auto":
        a.fq = auto_fq()
    out = os.path.join(ROOT, ".cache", "summaries", a.out or a.fq)

    if not a.dry and not os.environ.get("ANTHROPIC_API_KEY"):
        print("ANTHROPIC_API_KEY 없음 — AI 요약은 건너뜁니다")
        return
    if not a.collect:
        codes = a.codes or (report_text.todo(a.fq, a.todo) if a.todo else [])
        if not codes:
            print("요약할 종목 없음")
            return
        pk = packets(a.fq, codes)
        n_chr = sum(len(t) for t in pk.values()) + len(system_prompt(a.fq)) * len(pk)
        # 한국어는 대략 1.5자 ≈ 1토큰(시범 실측과 맞춰 볼 것). 출력은 생각 포함 종목당 ~5천 토큰으로 잡는다
        est = (n_chr / 1.5 * PRICE[0] + len(pk) * 5000 * PRICE[1]) / 1e6 * (1 if a.now else 0.5)
        print(f"{len(pk)}종목 · 묶음 {n_chr:,}자 · 예상 약 ${est:.2f}")
        if a.dry:
            return

    import anthropic
    client = anthropic.Anthropic()
    if a.collect:
        collect(client, a.fq, out)
    elif a.now:
        run_now(client, a.fq, pk, out)
    else:
        b = client.messages.batches.create(requests=[
            {"custom_id": code, "params": params(a.fq, code, txt)} for code, txt in pk.items()])
        os.makedirs(BATCHES, exist_ok=True)
        json.dump({"id": b.id, "codes": list(pk), "at": time.strftime("%Y-%m-%d %H:%M")},
                  open(os.path.join(BATCHES, f"{a.fq}.json"), "w"))
        print(f"배치 보냄 {b.id} — 기다리는 중(보통 1시간 안)")
        collect(client, a.fq, out, b.id)
    if a.load:
        review.cmd_load(SimpleNamespace(dir=out))


if __name__ == "__main__":
    main()
