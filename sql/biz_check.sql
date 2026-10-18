-- 사업보고서 점검 — 분기 재무 이력 · 공시 사건 · 점수 · 관심종목 · 점검 기록
--
-- 목표(2026-10-14 사용자): 지표로 유망 기업 ~200개를 추리고, 분기마다 보고서를 점검해
-- "계속 볼 가치가 있나"를 기록하며 판단한다. 원칙은 '숫자는 코드, 해석은 AI, 판정은 사람'.
--   · fin_q       : 정기보고서 한 건 = 한 행 (fin_hist.py). dart_fin(최신 1행 덮어쓰기)과 달리 이력이 남는다
--   · fin_q3m     : fin_q 의 누적값 → 분기 3개월 값 (뷰, 저장 공간 0)
--   · dart_corp   : 업종코드·결산월·금융업 여부 (CI 에는 캐시가 없어서 DB 에 둔다)
--   · dart_event  : CB·유상증자·자사주·감사의견·잠정실적 같은 공시 사건
--   · fin_score   : 최신 점수 스냅샷 (fin_score.py)
--   · watch       : 관심종목 — 점수로 들어오거나 직접 넣는다. '제외' 판정 전까지 남는다
--   · review      : 분기 점검 기록 — 자동 체크 · AI 요약 · 판정 · 메모
-- 사용자 결정으로 전부 공개(anon 읽기). 쓰기는 service_role(스크립트)만.
-- 원문 보고서는 DB 에 넣지 않는다(1건 6MB대) — 숫자와 짧은 요약만. 연 수 MB.
-- ▶ Supabase → SQL Editor 에 붙여넣고 1회 실행.

-- ── fin_q: 분기 재무 이력 ──────────────────────────────────────────────
-- 손익·현금흐름은 '연초부터 누적'(_ytd) 그대로 둔다 — 보고서가 주는 값 그대로라야 검증이 된다.
-- 현금흐름표는 누적만 주고(3개월 칸이 없다), 사업보고서는 연간만 준다. 3개월 값은 아래 뷰가 뺄셈으로 만든다.
-- 12월 결산 법인만 담는다(결산월이 다르면 분기말 계산이 어긋난다 — 비금융 상장사 중 소수).
create table if not exists public.fin_q (
  code            text not null,             -- 종목코드 '005930'
  fiscal_q        date not null,             -- 분기말 2026-06-30
  bsns_year       int  not null,
  reprt           text not null,             -- 11013 1분기 / 11012 반기 / 11014 3분기 / 11011 사업
  corp_code       text,
  fs_div          text,                      -- CFS 연결 / OFS 별도 — 바뀌면 전년 비교가 왜곡된다
  rcept_no        text,
  rcept_dt        date,                      -- 공시일. 과거 검증 때 '이 날 이후에만 알 수 있었던 값'
  revenue_ytd     double precision,
  op_income_ytd   double precision,
  net_income_ytd  double precision,
  ocf_ytd         double precision,          -- 영업활동현금흐름
  capex_ytd       double precision,          -- 유형+무형자산 취득 (양수)
  interest_ytd    double precision,          -- 이자의 지급 (양수, 현금흐름표)
  assets          double precision,
  liabilities     double precision,
  equity          double precision,
  cur_assets      double precision,
  cur_liabilities double precision,
  ppe             double precision,          -- 유형자산
  cash            double precision,          -- 현금및현금성자산
  receivables     double precision,          -- 매출채권
  inventory       double precision,          -- 재고자산
  updated_at      timestamptz default now(),
  primary key (code, fiscal_q)
);

-- ── fin_q3m: 누적 → 분기 3개월 값 ─────────────────────────────────────
-- Q1 은 누적이 곧 3개월. 나머지는 '같은 해 직전 분기' 누적을 뺀다.
-- 직전 분기가 비었거나 연결/별도가 바뀌었으면 null — 6개월치를 3개월로 착각하거나
-- 연결에서 별도를 빼는 사고를 막는다(예: 올해부터 별도로 바뀐 회사).
create or replace view public.fin_q3m with (security_invoker = on) as
with x as (
  select f.*,
         extract(month from f.fiscal_q)::int / 3 as qn,
         lag(f.fiscal_q)       over w as p_q,
         lag(f.fs_div)         over w as p_div,
         lag(f.revenue_ytd)    over w as p_rev,
         lag(f.op_income_ytd)  over w as p_op,
         lag(f.net_income_ytd) over w as p_net,
         lag(f.ocf_ytd)        over w as p_ocf,
         lag(f.capex_ytd)      over w as p_capex,
         lag(f.interest_ytd)   over w as p_int
  from public.fin_q f
  window w as (partition by f.code, f.bsns_year order by f.fiscal_q)
), y as (
  select x.*,
         (x.qn = 1) as first_q,
         (x.p_q = (date_trunc('quarter', x.fiscal_q::timestamp) - interval '1 day')::date
          and x.p_div = x.fs_div) as chain_ok
  from x
)
select code, fiscal_q, bsns_year, qn, reprt, fs_div, rcept_no, rcept_dt,
       -- 매출은 음수가 될 수 없다. 음수면 회사가 과거를 다시 작성한 것(중단사업 재분류 등 — 이번 보고서는
       -- 계속사업만, 직전 분기 누적은 옛 기준) → 빼면 틀린 값이라 비운다(2026-10-17 검토: 실측 16건, 최대 −7.4조)
       case when first_q then revenue_ytd    when chain_ok and revenue_ytd >= p_rev then revenue_ytd - p_rev end as revenue,
       case when first_q then op_income_ytd  when chain_ok then op_income_ytd  - p_op    end as op_income,
       case when first_q then net_income_ytd when chain_ok then net_income_ytd - p_net   end as net_income,
       case when first_q then ocf_ytd        when chain_ok then ocf_ytd        - p_ocf   end as ocf,
       case when first_q then capex_ytd      when chain_ok then capex_ytd      - p_capex end as capex,
       case when first_q then interest_ytd   when chain_ok then interest_ytd   - p_int   end as interest,
       assets, liabilities, equity, cur_assets, cur_liabilities, ppe, cash, receivables, inventory
from y;

-- ── dart_corp: 기업 정보 ──────────────────────────────────────────────
-- 금융업 판별: 업종코드 64·65·66 은 제외하되 64992(지주회사)는 금융지주(KB·신한)와 일반 지주(LG·SK)가
-- 같은 코드를 쓴다. 그래서 지주회사는 재무제표 모양으로 가른다 — 금융사는 유동/비유동 구분이 없다.
create table if not exists public.dart_corp (
  corp_code   text primary key,
  code        text,
  name        text,
  induty_code text,                          -- 표준산업분류(KSIC)
  acc_mt      text,                          -- 결산월 '12'
  fin_kind    text,                          -- null=일반 / financial / fin_holding / non_dec_fy
  updated_at  timestamptz default now()
);
create index if not exists dart_corp_code_idx on public.dart_corp (code);

-- ── dart_event: 공시 사건 ─────────────────────────────────────────────
create table if not exists public.dart_event (
  rcept_no  text primary key,
  rcept_dt  date not null,
  code      text,
  corp_code text,
  corp_name text,
  kind      text not null,                   -- cb / bw / eb / rights / buyback / cancel / dividend / holder / audit / prelim …
  report_nm text,
  detail    jsonb,                           -- 일부 종류만: 금액·전환가·의견 등
  created_at timestamptz default now()
);
create index if not exists dart_event_code_idx on public.dart_event (code, rcept_dt desc);

-- ── fin_score: 최신 점수 스냅샷 ───────────────────────────────────────
-- 네 축(성장·수익성·현금·건전성)을 유니버스 안 백분위(0~100)로 매기고 평균한다.
create table if not exists public.fin_score (
  code        text primary key,
  name        text,
  market      text,
  fiscal_q    date,                          -- 점수 기준 분기
  mktcap      double precision,
  rev_g       double precision,              -- 매출 TTM 전년 대비 (소수)
  op_g        double precision,              -- 영업이익 TTM 전년 대비
  roic        double precision,
  op_margin   double precision,
  fcf_margin  double precision,              -- FCF TTM ÷ 매출 TTM
  cash_conv   double precision,              -- 영업현금흐름 ÷ 순이익 (TTM)
  debt_ratio  double precision,              -- 총부채 ÷ 자본 (%)
  int_cov     double precision,              -- 영업이익 ÷ 이자지급 (배)
  s_growth    double precision,
  s_profit    double precision,
  s_cash      double precision,
  s_health    double precision,
  score       double precision,
  rank        int,
  flags       text[],                        -- 경고 표시(점수에는 안 넣는다): 'CB발행' '감사인교체' …
  excluded    text,                          -- 제외 사유 (null 이면 후보 대상)
  updated_at  timestamptz default now()
);

-- ── watch: 관심종목 ───────────────────────────────────────────────────
create table if not exists public.watch (
  code       text primary key,
  name       text,
  source     text not null default 'score',  -- score(점수로 들어옴) / manual(직접 추가)
  status     text not null default 'active', -- active 유지 / watch 관찰 / drop 제외
  added_at   date default current_date,
  thesis     text,                           -- 보는 이유
  kpi        text,                           -- 이 회사의 핵심 지표 (예: 수주잔고)
  kill       text,                           -- 깨지는 조건
  memo       text,
  updated_at timestamptz default now()
);

-- ── review: 분기 점검 기록 ─────────────────────────────────────────────
create table if not exists public.review (
  code        text not null,
  fiscal_q    date not null,
  rcept_no    text,
  reviewed_at timestamptz default now(),
  checks      jsonb,                         -- 자동 체크 [{rule, result: pass/warn/fail, value}]
  extracted   jsonb,                         -- 본문에서 뽑은 숫자 (수주잔고 등)
  summary     text,                          -- AI 요약 — 전 분기 대비 바뀐 점
  verdict     text,                          -- keep 유지 / watch 관찰 / drop 제외
  memo        text,
  primary key (code, fiscal_q)
);

-- ── 공개 읽기 (사용자 결정: 전부 공개) ─────────────────────────────────
alter table public.fin_q      enable row level security;
alter table public.dart_corp  enable row level security;
alter table public.dart_event enable row level security;
alter table public.fin_score  enable row level security;
alter table public.watch      enable row level security;
alter table public.review     enable row level security;
drop policy if exists "fin_q anon read"      on public.fin_q;
drop policy if exists "dart_corp anon read"  on public.dart_corp;
drop policy if exists "dart_event anon read" on public.dart_event;
drop policy if exists "fin_score anon read"  on public.fin_score;
drop policy if exists "watch anon read"      on public.watch;
drop policy if exists "review anon read"     on public.review;
create policy "fin_q anon read"      on public.fin_q      for select to anon using (true);
create policy "dart_corp anon read"  on public.dart_corp  for select to anon using (true);
create policy "dart_event anon read" on public.dart_event for select to anon using (true);
create policy "fin_score anon read"  on public.fin_score  for select to anon using (true);
create policy "watch anon read"      on public.watch      for select to anon using (true);
create policy "review anon read"     on public.review     for select to anon using (true);
grant select on public.fin_q3m to anon;
