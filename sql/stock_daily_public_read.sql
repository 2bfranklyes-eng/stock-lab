-- 매물대 탭에서 주가 그래프를 매물대와 겹쳐 그리려면 웹(anon)이 일별 종가를 읽어야 한다.
-- KRX가 공개하는 시장 데이터라 비공개로 둘 이유가 없다.
-- (프론트는 dt·close·shares 세 컬럼만, 선택한 집계 구간만큼만 가져간다)
-- Supabase SQL editor에서 1회 실행.
alter table stock_daily enable row level security;
drop policy if exists "public read stock_daily" on stock_daily;
create policy "public read stock_daily" on stock_daily for select using (true);
