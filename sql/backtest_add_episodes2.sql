-- 유동성·물가 밴드 통계에 '사건 수' 칸 (심리 backtest_stats 와 같은 정의 — 2026-10-17 검토)
-- 일수는 독립 표본이 아니다. 10일 평활 때문에 한 밴드가 수십~수백 일 이어져 극단 밴드의 근거가 몇 건뿐일 수 있다.
-- ▶ Supabase → SQL Editor 에서 1회 실행. 다음 갱신부터 채워지고, 웹 표에 '사건 N'으로 함께 나온다.
alter table public.liquidity_backtest_stats add column if not exists n_episodes int;
alter table public.inflation_backtest_stats add column if not exists n_episodes int;
