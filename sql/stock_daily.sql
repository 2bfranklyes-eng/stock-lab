-- 한국 일별 시세(종목 + 지수) — krx.py가 KRX OPEN API로 채움. 매물대의 원자료.
-- 종목은 '거래대금 ÷ 시가총액'이 곧 G&H의 진짜 회전율이라 모델이 근사가 아니라 정의대로 돈다.
-- 코스피·코스닥 지수도 같은 스캔에서 code='kospi'/'kosdaq'로 함께 넣는다 —
-- 야후(^KS11)는 하루 늦고 거래'량'만 주는데 KRX는 당일 고저가 + 거래'대금' + 시총을 준다.
-- 종목은 워치리스트(시총 상위 N + SCREENER_ALWAYS)만 — 전 종목을 넣으면 350만 행이 된다.
-- Supabase SQL editor에서 1회 실행.
create table if not exists stock_daily (
  code   text not null,        -- 종목코드 6자리 또는 지수 키(kospi/kosdaq)
  dt     date not null,
  open   numeric,
  high   numeric,
  low    numeric,
  close  numeric,
  tval   numeric,              -- 거래대금(원) — 매물대 가중치. 저가주 왜곡이 없어 거래량보다 낫다
  shares numeric,              -- 상장주식수 — 액면분할 판정에 씀
  mktcap numeric,              -- 시가총액 — 회전율 분모
  primary key (code, dt)
);
alter table stock_daily enable row level security;
-- 프론트는 volume_profile(집계 결과)만 읽으므로 원자료는 공개하지 않는다(service_role 전용).
