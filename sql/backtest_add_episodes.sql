-- 밴드 백테스트 표에 '독립 에피소드 수'를 병기하기 위한 컬럼.
--
-- 왜 필요한가: n(일수)은 독립 표본 수가 아니다. 겹치는 20일 창을 매일 세면
-- 한 사건이 수십 번 계상된다. 실제로 US 심리 '극단공포 86일'은 사건 9건,
-- KR '극단탐욕 66일'은 사건 6건이었다. 일수만 보면 근거가 10배 부풀어 보인다.
-- asset_regime_stats가 이미 n_days/n_episodes를 병기하는 것과 같은 문법으로 맞춘다.
alter table backtest_stats      add column if not exists n_episodes int;
alter table fuel_backtest_stats add column if not exists n_episodes int;
