-- 자산별 '위치 점수' — allocation.py가 매일 계산, 웹 자산 카드가 읽는다.
-- 합성 단일 점수를 의도적으로 만들지 않는다: 추세(c_trend)와 과열(c_heat)은 방향이 자주 반대라
-- 합치면 상쇄로 정보가 사라지고 '추천 점수'처럼 읽힌다. 게이지 2개를 병렬로 보여줄 것.
--   c_trend = 12-1 모멘텀(1달 전 가격/12달 전 가격)의 3년 백분위 — 추세가 자기 역사 대비 어디인가
--   c_heat  = 가격/200일선 이격의 3년 백분위 — 단기 과열/과랭이 자기 역사 대비 어디인가
-- anchor_a~d는 자산마다 의미가 다른 '참고 실수치'(웹 ASSET_META가 라벨을 정의):
--   gold:    a=미10년 실질금리(%) b=실질금리 63일 변화(bp) c=금/은 비율 백분위 d=금/원자재(GSCI) 백분위
--   us_bond: a=미10년 실질금리(%) b=실질금리 전이력 백분위
--   kr_bond: a=국고채10년 금리(%) b=금리 전이력 백분위
--   usdkrw:  a=원/달러 5년 백분위
--   dbc·us_index·kr_index·btc: 앵커 없음(억지 앵커는 과최적화 — 공통 2게이지만)
-- Supabase SQL editor에서 1회 실행.
create table if not exists asset_daily (
  asset    text not null,               -- gold/us_bond/kr_bond/dbc/usdkrw/us_index/kr_index/btc
  dt       date not null,
  c_trend  numeric,                     -- 추세 위치 0~100 (초기 1년은 창 부족으로 null 가능)
  c_heat   numeric,                     -- 과열 위치 0~100
  raw_px   numeric not null,            -- 최신가(자산 고유 단위)
  raw_dd252 numeric,                    -- 52주 고점 대비 낙폭(%)
  raw_r12m  numeric,                    -- 12개월 수익률(%)
  anchor_a numeric,
  anchor_b numeric,
  anchor_c numeric,
  anchor_d numeric,
  primary key (asset, dt)
);
alter table asset_daily enable row level security;
drop policy if exists "public read asset_daily" on asset_daily;
create policy "public read asset_daily" on asset_daily for select using (true);
