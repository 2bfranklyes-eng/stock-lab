-- asset_daily에 주식과의 롤링 상관 추가 — allocation.py가 채우고 🛡️ 상관 차트가 읽는다.
-- 63일(약 3달) 상관: '채권이 주식을 헤지해 주는 시기인가'가 시대마다 바뀐다는 걸
-- (2022년 상관 양전환) 직접 보여주기 위한 컬럼. 기존 테이블에 컬럼만 더한다.
-- Supabase SQL editor에서 1회 실행. (holder_profile_add_net.sql과 같은 패턴)
alter table asset_daily add column if not exists corr63_us numeric;  -- vs S&P500 일수익
alter table asset_daily add column if not exists corr63_kr numeric;  -- vs 코스피 일수익
