-- liquidity_daily: 일드커브 실제값(%p) 저장 컬럼 추가
-- 목적: 차트 툴팁에서 성분 점수(0~100)와 함께 '실제 수치'를 보여주기 위함.
--   raw_us10y=10년물 금리, raw_dxy=DXY(US)/신용스프레드(KR), raw_usdkrw=원/달러(KR),
--   raw_curve=일드커브(US: 10년-3개월, KR: 국고채10년-3년) %p  ← 이번에 추가.
-- Supabase SQL editor에서 1회 실행. 기존 anon read 정책이 신규 컬럼에도 그대로 적용됨.
alter table liquidity_daily add column if not exists raw_curve numeric;
