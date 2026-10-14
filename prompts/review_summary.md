# 분기 점검 요약 — 보조 에이전트 지시문 (사업보고서 점검)

`report_text.py` 가 만든 묶음(.cache/packets/<분기>/<종목>.md)을 읽어 `review.py load` 가 적재할 JSON 을 쓰게 하는 지시문.
2026-10-15 시범에서 정했다: **Sonnet 으로(`model: "sonnet"`), 에이전트 하나에 5종목씩**. 같은 3종목에서 Opus 와
품질이 같거나 나았고(수주 숫자 완전 일치) 한도는 덜 쓴다. 실측: 종목당 5시간 한도 ~1%p, 주간 ~0.15%p.
5시간 한도를 다 쓰면 대화도 막히니 한 번에 80% 안쪽까지만 돌린다.

`{FQ}`(분기말, 예 2026-09-30), `{CODES}`(쉼표로), `{TAG}`(에이전트별 고유 이름)를 바꿔 넣는다.
에이전트끼리 같은 scratch 이름으로 스크립트를 써서 서로 덮어쓴 적이 있어, 작업 폴더를 에이전트마다 따로 준다.
결과는 코드로 다시 검증한다(형식·근거 절·수주 등식) — 에이전트의 자기 보고만 믿지 않는다.

---

You are summarizing Korean company quarterly-report "packets" for a personal stock-research app. Work only with the files described here. Do NOT run any database commands, do NOT edit any other files, do NOT browse the web. If you write any helper script, put it ONLY under C:\Users\user\stock-lab\.cache\agent_tmp\{TAG}\ (create it) — never in any shared scratch folder, and never reuse common names.

Packets (markdown, Korean) are in C:\Users\user\stock-lab\.cache\packets\{FQ}\ — handle exactly these files: {CODES} (each as <code>.md)

Each packet compares a company's report for fiscal_q {FQ} with its previous report. It contains: (1) "숫자 자동 체크" — code-computed checks (context only), (2) for sections II.1–II.7, IV, XI.4: only SENTENCES that are new or changed vs the previous report (numbers were masked during comparison, so a listed sentence's wording or presence is genuinely new; a listed sentence is new unless it is a pure table row), and (3) section II.4 (매출 및 수주상황) in FULL for both the current and previous report so numbers can be compared.

For EACH packet, write one JSON file to C:\Users\user\stock-lab\.cache\summaries\{FQ}\<code>.json (UTF-8, valid JSON, Korean text as-is, not \u-escaped) with exactly this shape:
{
  "code": "<6-digit code>",
  "fiscal_q": "{FQ}",
  "summary": "<Korean. 3–6 lines, each starting with '• '. Each line = one concrete change since the previous report, ending with the section tag in parentheses like (II.1) or (II.4). Prioritize: new business/markets/customers, product price or mix changes, raw-material/capacity/utilization changes, revenue-mix and order-backlog changes, new or removed risk factors, major contracts/R&D, events after the reporting date (XI.4). Skip boilerplate, period-label changes, and pure number refreshes that carry no meaning. If nothing meaningful changed, write a single line saying so.>",
  "extracted": {
    "backlog": null OR {
      "unit": "<unit as stated, e.g. 백만원>",
      "cur":  {"basis": "<e.g. 기준일, 연초 누적>", "begin": <number|null>, "new": <number|null>, "delivered": <number|null>, "end": <number|null>},
      "prev": {"basis": "...", "begin": <number|null>, "new": <number|null>, "delivered": <number|null>, "end": <number|null>},
      "identity_ok": <true if begin + new − delivered == end holds for cur (allow tiny rounding); false if all four are present and it does NOT hold; null if the table format makes the check impossible>,
      "quarter_new_orders": <cur.new − prev.new if both are cumulative within the same year, else null>,
      "note": "<one short Korean note>"
    },
    "segments": [ {"name": "<segment>", "cur_share_pct": <number|null>, "prev_share_pct": <number|null>} ] (top 3–5 by revenue share if a revenue-by-segment table is clearly present in II.4; otherwise []),
    "kpi": "<Korean, 1–2 key indicators worth tracking every quarter for THIS company, with the section where they appear>",
    "watch_points": ["<Korean, 1–3 things to check in the next quarterly report>"]
  }
}

Rules:
- Every number must come from the packet text (or a simple subtraction/division of packet numbers, which you should label as such). Never invent or estimate. If unsure, use null.
- backlog only for an ONGOING order-backlog (수주상황/수주잔고) table; a single completed contract or a revenue-recognition table is not a backlog → null. Many companies have none → null. Totals row (합계) preferred. Delivered amounts shown in parentheses or negative should be stored as positive.
- Never back-calculate a missing begin/new/delivered value from the identity itself (e.g. begin = end − new + delivered) — that makes the check circular. Leave it null and set identity_ok to null.
- Neutral, factual tone. No investment advice, no buy/sell language, no price targets, no speculation beyond the text.
- Keep summary lines short (under ~120 Korean characters each).

When done, reply with a short list: each code, whether backlog was found, and one line of the most notable change.
