-- ai_daily — AI 사이클 계기판 원자료 (반도체 밸류체인 주가 + 자국 지수 대비 상대강도)
--   TSMC(대만) · 삼성전자·SK하이닉스(한국) · SOX(미국). ai_cycle.py 가 dt 기준 upsert.
--   비율(r_*)은 같은 거래소끼리 나눈 값이라 거래일 캘린더 문제가 없다.
--   ⚠️ 예측 지표가 아니라 '지금 얼마나 쏠려 있나'를 기술하는 계기판용이다.
-- ▶ Supabase → SQL Editor 에 붙여넣고 1회 실행하면 됩니다.

create table if not exists public.ai_daily (
  dt        date primary key,
  tsmc      double precision,   -- 2330.TW 종가 (NT$)
  twii      double precision,   -- 대만 가권지수
  samsung   double precision,   -- 005930.KS 종가 (원)
  hynix     double precision,   -- 000660.KS 종가 (원)
  kospi     double precision,   -- 코스피
  sox       double precision,   -- 필라델피아 반도체지수
  spx       double precision,   -- S&P500
  r_tsmc    double precision,   -- TSMC ÷ 가권
  r_samsung double precision,   -- 삼성전자 ÷ 코스피
  r_hynix   double precision,   -- 하이닉스 ÷ 코스피
  r_sox     double precision    -- SOX ÷ S&P500
);

alter table public.ai_daily enable row level security;

drop policy if exists "ai_daily anon read" on public.ai_daily;
create policy "ai_daily anon read"
  on public.ai_daily
  for select
  to anon
  using (true);
