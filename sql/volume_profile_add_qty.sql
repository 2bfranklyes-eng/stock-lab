-- 매물대에 '소화 일수' 계산용 절대 수량을 추가. Supabase SQL editor에서 1회 실행.
--
-- 왜 필요한가: share(%)만으로는 "이 매물이 두꺼운가"를 알 수 없다. 비중은 창 안에서의
-- 상대값이라 종목 간 비교도, "며칠이면 소화되나"도 계산이 안 된다.
-- 절대 수량(주)과 하루 평균 거래량을 같이 두면 '하루 거래량의 몇 배'가 바로 나온다.
--
-- daily_qty·vol_ratio는 (code, win_days) 안에서 모든 행이 같은 값이라 중복이지만,
-- px·dt와 같은 방식이다 — 조인 없이 한 번의 조회로 화면을 그리려는 의도.
alter table volume_profile add column if not exists qty       numeric;  -- 이 구간 잔존 물량(주)
alter table volume_profile add column if not exists daily_qty numeric;  -- 최근 20일 평균 거래량(주)
alter table volume_profile add column if not exists vol_ratio numeric;  -- 최근일 거래량 ÷ 20일 평균
