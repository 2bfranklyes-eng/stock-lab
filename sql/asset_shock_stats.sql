-- 충격완화 통계 — allocation_shock.py가 만들고, 웹 자산배분 탭 🛡️ 섹션이 읽는다.
-- 두 종류의 행이 산다:
--   basis 'US'|'KR' + scope 'crash10'  = 급락월 조건표. 기준주식(S&P/코스피)의 캘린더 월수익
--     하위 10% 달에서 각 자산의 같은 달 수익 통계. n이 13~14달뿐이라 통계라기보다 '사례 모음'.
--     하위 10%는 전체 이력으로 정한 사후 기준(look-ahead) — 예측 규칙이 아니라 과거 묘사다.
--   basis 'EP' + scope 'ep_*'          = 위기 리플레이. 기준주식 고점→저점 구간(2026은 진행 중)의
--     자산별 누적수익·구간 내 최대낙폭. 2022년 채권 동반 폭락이 표에 그대로 남는다 —
--     '방어재는 위기마다 달랐다'는 게 이 표의 결론이자 존재 이유.
-- ret_krw = 달러자산을 원화로 환산(가격×원/달러)한 값 — 급락기 환율 완충('환율 방패')을
-- 숫자로 드러낸다. 원화 자산은 loc와 같다. 위기 목록을 결과를 알고 골랐다는 선택 편향은
-- 웹 해설에 자인한다.
-- Supabase SQL editor에서 1회 실행.
create table if not exists asset_shock_stats (
  basis    text not null,      -- 'US' | 'KR' (crash10의 기준주식) | 'EP' (위기 리플레이)
  scope    text not null,      -- 'crash10' | 'ep_2015yuan' | 'ep_2018q4' | 'ep_2020covid'
                               --  | 'ep_2022rates' | 'ep_2024yen' | 'ep_2026kr'
  asset    text not null,
  n        int  not null,      -- crash10: 급락월 수 / ep: 구간 거래일수
  ret_avg  numeric,            -- crash10: 같은 달 평균수익% / ep: 구간 누적수익% (자산 표시통화)
  ret_med  numeric,            -- crash10만: 중앙값%
  ret_krw  numeric,            -- 원화 환산 평균/누적% (달러자산×원달러, 원화자산은 loc와 동일)
  hit      numeric,            -- crash10만: 같은 달 상승 비율%
  worst    numeric,            -- crash10만: 최악의 달%
  mdd      numeric,            -- ep만: 구간 내 최대낙폭%
  stock_ret numeric,           -- 기준주식의 같은 통계% (비교 기준)
  primary key (basis, scope, asset)
);
alter table asset_shock_stats enable row level security;
drop policy if exists "public read asset_shock_stats" on asset_shock_stats;
create policy "public read asset_shock_stats" on asset_shock_stats for select using (true);
