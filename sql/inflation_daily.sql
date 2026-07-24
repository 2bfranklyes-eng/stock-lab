-- inflation_daily — 물가지수 I(t) 일별 (inflation.py 가 (market, dt) 기준 upsert)
--   liquidity_daily 와 동일 얼개 (i_score=종합, c_*=4성분, 높을수록 물가↑).
--   웹 대시보드(anon)는 읽기만, 쓰기는 파이프라인(service_role)만.
-- ▶ Supabase → SQL Editor 에 붙여넣고 1회 실행하면 됩니다.

create table if not exists public.inflation_daily (
  market   text not null,
  dt       date not null,
  i_score  double precision,
  band     text,
  c_be     double precision,   -- 기대인플레(미국 TIP/IEF, 한국 원/달러=수입물가)
  c_energy double precision,   -- 에너지(유가 USO)
  c_comm   double precision,   -- 원자재(DBC)
  c_metal  double precision,   -- 산업금속(DBB)
  primary key (market, dt)
);

alter table public.inflation_daily enable row level security;

drop policy if exists "inflation_daily anon read" on public.inflation_daily;
create policy "inflation_daily anon read"
  on public.inflation_daily
  for select
  to anon
  using (true);
