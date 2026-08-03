-- 국면별 자산 이후수익률 통계 — allocation_backtest.py가 만들고, 웹 국면 성적표가 읽는다.
-- 기존 밴드 백테스트(backtest_stats 등)와 같은 문법: 이후 N일 수익 평균 + 승률 + 표본수.
-- n_days와 별도로 n_episodes(그 국면이 연속 블록으로 몇 번 있었나)를 병기한다 —
-- 겹치는 창은 독립 표본이 아니라서, n_days가 커 보여도 에피소드 몇 번이면 '사례 모음'이다.
-- ccy: 'loc'=자산 표시통화 / 'krw'=원화 환산(달러자산 가격×원달러, 원화자산은 loc와 동일 복제)
-- Supabase SQL editor에서 1회 실행.
create table if not exists asset_regime_stats (
  regime   text not null,               -- g_up_i_dn / g_up_i_up / g_dn_i_up / g_dn_i_dn / all
  asset    text not null,
  ccy      text not null default 'loc',
  n_days   int  not null,               -- 그 국면의 거래일수
  n_episodes int not null,              -- 그 국면의 연속 블록 수 (적으면 '사례 모음')
  fwd5  numeric, fwd10 numeric, fwd20 numeric, fwd30 numeric, fwd60 numeric,   -- 이후 N일 평균수익 %
  hit5  numeric, hit10 numeric, hit20 numeric, hit30 numeric, hit60 numeric,   -- 이후 N일 상승확률 %
  primary key (regime, asset, ccy)
);
alter table asset_regime_stats enable row level security;
drop policy if exists "public read asset_regime_stats" on asset_regime_stats;
create policy "public read asset_regime_stats" on asset_regime_stats for select using (true);
