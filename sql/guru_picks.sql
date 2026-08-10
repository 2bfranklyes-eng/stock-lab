-- 구루 스크리너 — 투자 대가 5인의 기준으로 걸러낸 종목 (guru.py 가 갱신)
--
-- 한 행 = "구루 × 종목". 같은 종목이 여러 구루에 중복으로 들어갈 수 있고,
-- 그게 오히려 의미 있는 신호다(서로 다른 철학이 같은 지점을 가리킴).
--
-- ⚠️ 이 테이블로 '검증된 전략'을 만들 수는 없다. stock_meta 와 같은 한계를 그대로 물려받는다:
--    ① 생존편향 — 현재 상장 종목만 있어 과거 상폐·합병된 종목이 빠진다
--    ② 시점 데이터 부재 — 재무제표가 최신 수정본이라 '그때 알 수 있었던 값'이 아니다
--    ③ 결측 30~40% — 지표가 없는 종목은 통과할 수 없다(= 조용히 탈락한다)
--    → 화면에서도 '지금 이 기준에 걸린다'까지만 말하고 미래 수익률은 주장하지 않는다.
-- ▶ Supabase → SQL Editor 에 붙여넣고 1회 실행하면 됩니다.

create table if not exists public.guru_picks (
  guru            text not null,         -- buffett / graham / lynch / greenblatt / oneil
  code            text not null,         -- 'AAPL' (미국) 또는 '005930' (한국 거래소 코드)
  rank            int,                   -- 같은 구루·같은 시장 안에서의 순위 (1이 최상위)
  score           double precision,      -- 구루마다 의미가 다르다 (프론트 GURUS[].scoreLabel 참고)
  name            text,
  market          text,                  -- US / KOSPI / KOSDAQ
  sector          text,
  currency        text,                  -- USD / KRW — 시총·주가 표기를 가르는 값
  close           double precision,
  marcap          double precision,
  -- 화면 표에 그대로 뿌리는 지표들. 스케일은 두 시장이 같게 맞춰져 있다:
  --   roe·op_margin·profit_margin·rev_growth·earn_growth = 소수 (0.15 = 15%)
  --   debt_to_equity·div_yield = 퍼센트 숫자 (78.4 = 78.4%)
  per             double precision,
  pbr             double precision,
  roe             double precision,
  roa             double precision,      -- 순이익 ÷ 총자산. 마법공식의 자본수익률 축
  ev_ebitda       double precision,      -- EV ÷ EBITDA. 역수가 마법공식의 이익수익률 축
  debt_to_equity  double precision,      -- 총차입금 ÷ 자본 (한국식 '부채비율'인 총부채 기준이 아님)
  op_margin       double precision,
  profit_margin   double precision,
  rev_growth      double precision,
  earn_growth     double precision,
  div_yield       double precision,
  peg             double precision,      -- PER ÷ 이익성장률(%)
  mom_12m         double precision,      -- 최근 12개월 주가 수익률 (소수)
  off_high        double precision,      -- 현재가 ÷ 52주 최고가 (1.0 = 신고가)
  fiscal_q        date,                  -- 재무 기준 분기말 — '언제 기준 숫자인가'
  updated_at      timestamptz default now(),
  primary key (guru, code)
);

create index if not exists guru_picks_guru_idx on public.guru_picks (guru, market, rank);

alter table public.guru_picks enable row level security;

drop policy if exists "guru_picks anon read" on public.guru_picks;
create policy "guru_picks anon read" on public.guru_picks for select to anon using (true);
