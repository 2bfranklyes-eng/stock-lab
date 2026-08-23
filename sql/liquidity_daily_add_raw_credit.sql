-- liquidity_daily: 신용스프레드 실제값(%p) 저장 컬럼 추가
-- 목적: 조기경보 게이지. c_credit(0~100 백분위)만으론 '지금이 역사적으로 어디쯤인가'를 못 읽는다.
--   미국 c_credit 은 HYG/IEI 의 60일 평균 대비 비율이라 국면 변화만 잡고 절대수준 정보가 없다.
--   BAA10Y(무디스 Baa − 미10년물)는 1986년부터 있어 닷컴·금융위기와 직접 비교된다:
--     닷컴 정점 2.09 → +6M 2.52 → 최악 3.90 / 금융위기 정점 1.90 → +6M 3.38 → 최악 6.16
--   두 위기 모두 '벌어지는 데 6개월'이 걸렸다 — 그래서 조기경보로 쓸 값이 생긴다.
--   raw_credit = US: BAA10Y, KR: 회사채3년(AA-) − 국고채3년  %p  ← 이번에 추가.
-- Supabase SQL editor에서 1회 실행. 기존 anon read 정책이 신규 컬럼에도 그대로 적용됨.
alter table liquidity_daily add column if not exists raw_credit numeric;
