-- 개별 종목 퀀트 — 스크리너(A) + 포트폴리오 구성·진단(B) 용 테이블 2개
--   screener.py 가 주 1회 갱신한다. 유니버스는 시가총액 상위 N종목(기본 500).
--
-- ⚠️ 이 데이터로 '검증된 전략'을 만들 수는 없다. 무료 데이터의 구조적 한계:
--    ① 생존편향 — 현재 상장 종목만 있어 과거 상폐·합병된 종목이 빠진다(실측 실패율 13%)
--    ② 시점 데이터 부재 — 재무제표가 최신 수정본이라 '그때 알 수 있었던 값'이 아니다
--    ③ 재무 이력 4~5년 — 팩터 검증에 필요한 10~20년에 못 미친다
--    → 화면에서도 '과거에 이랬다'까지만 말하고 미래 수익률은 주장하지 않는다.
-- ▶ Supabase → SQL Editor 에 붙여넣고 1회 실행하면 됩니다.

-- 종목 스냅샷 (재무 지표는 분기 단위로만 바뀌므로 주 1회 갱신이면 충분)
create table if not exists public.stock_meta (
  code            text primary key,      -- '005930' (거래소 코드)
  name            text,
  market          text,                  -- KOSPI / KOSDAQ
  sector          text,
  industry        text,
  close           double precision,      -- 종가(원)
  marcap          double precision,      -- 시가총액(원)
  per             double precision,      -- 시총 ÷ 순이익 (직접 계산 — 한국 종목은 야후가 안 줌)
  pbr             double precision,      -- 시총 ÷ 자본 (= PER × ROE)
  roe             double precision,
  debt_to_equity  double precision,
  op_margin       double precision,
  profit_margin   double precision,
  rev_growth      double precision,
  earn_growth     double precision,
  div_yield       double precision,
  beta            double precision,
  updated_at      timestamptz default now()
);

-- 월말 종가 — 포트폴리오 과거 시뮬레이션용. 일별이면 프론트가 못 받아 월말로 압축.
--   벤치마크는 code='KOSPI' / 'KOSDAQ' 로 같은 테이블에 넣는다.
create table if not exists public.stock_monthly (
  code   text not null,
  dt     date not null,
  close  double precision,
  primary key (code, dt)
);
create index if not exists stock_monthly_code_idx on public.stock_monthly (code);

alter table public.stock_meta enable row level security;
alter table public.stock_monthly enable row level security;

drop policy if exists "stock_meta anon read" on public.stock_meta;
create policy "stock_meta anon read" on public.stock_meta for select to anon using (true);

drop policy if exists "stock_monthly anon read" on public.stock_monthly;
create policy "stock_monthly anon read" on public.stock_monthly for select to anon using (true);
