-- price_daily 를 '시장당 지수 1개' → '시장당 여러 지수'로 확장 (미국 S&P500·나스닥·다우 / 한국 코스피·코스닥)
--   기존 PK (market, dt) 로는 같은 날 여러 지수를 못 담아 (market, dt, code) 로 바꾼다.
--   기존 행은 대표 지수였으므로 us_index / kr_index 로 채워 넣는다. prices.py 가 어차피 전량 교체하지만,
--   SQL 실행 직후 ~ 스크립트 실행 사이에도 화면이 깨지지 않게 값을 채워두는 것.
-- ▶ Supabase → SQL Editor 에 붙여넣고 1회 실행하면 됩니다. (RLS/정책은 기존 것 그대로 유지)

alter table price_daily add column if not exists code text;

update price_daily
   set code = case when market = 'US' then 'us_index' else 'kr_index' end
 where code is null;

alter table price_daily alter column code set not null;

alter table price_daily drop constraint if exists price_daily_pkey;
alter table price_daily add constraint price_daily_pkey primary key (market, dt, code);
