-- 공개용 주가 테이블 — 비교 탭에서 웹(anon)이 실제 주가를 지수와 겹쳐 그리기 위함.
-- indicator_raw(us_index/kr_index)는 service_role 전용이라 anon이 못 읽음 → 공개 복사본.
-- Supabase SQL editor에서 1회 실행. prices.py가 채움(refresh 크론에 포함).
create table if not exists price_daily (
  market text not null,
  dt     date not null,
  close  numeric,
  primary key (market, dt)
);
alter table price_daily enable row level security;
drop policy if exists "public read price_daily" on price_daily;
create policy "public read price_daily" on price_daily for select using (true);
