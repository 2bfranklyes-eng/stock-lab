-- inflation_backtest_stats — I(t) 물가 밴드별 '이후수익률' 통계
--   inflation_backtest.py 가 (market, band) 기준으로 upsert 한다.
--   backtest_stats / liquidity_backtest_stats 와 동일 스키마 (fwd{h}=평균수익률%, hit{h}=승률%).
--   웹 대시보드(anon)는 읽기만, 쓰기는 파이프라인(service_role)만.
-- ▶ Supabase → SQL Editor 에 붙여넣고 1회 실행하면 됩니다.

create table if not exists public.inflation_backtest_stats (
  market text not null,
  band   text not null,
  n      integer,
  fwd5  double precision, hit5  double precision,
  fwd10 double precision, hit10 double precision,
  fwd20 double precision, hit20 double precision,
  fwd30 double precision, hit30 double precision,
  fwd60 double precision, hit60 double precision,
  primary key (market, band)
);

alter table public.inflation_backtest_stats enable row level security;

drop policy if exists "inflation_backtest_stats anon read" on public.inflation_backtest_stats;
create policy "inflation_backtest_stats anon read"
  on public.inflation_backtest_stats
  for select
  to anon
  using (true);
