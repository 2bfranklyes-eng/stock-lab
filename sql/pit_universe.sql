-- Point-in-time 유니버스 — '그 시점에 실제로 상장돼 있던 전 종목'을 남긴다.
--
-- 왜 필요한가 — stock_daily는 vp_stocks(오늘 시총 기준 상위 50%/70%)만 보관한다. 그래서
-- 과거 어느 시점을 봐도 '오늘 살아남은 종목'뿐이고, 상장폐지·시총 급감으로 빠진 종목은
-- 흔적도 없다. 이 편향의 크기를 factor.py로 실측했다:
--   · 5년 내내 존재한 175종목의 5년 수익률 중앙값 +87%(평균 +233%)
--   · 5년 전 시총 하위였던 88종목 +137% vs 당시 상위였던 종목 +19%
--   · 그 결과 '소형주 팩터'가 +74%/년으로 나왔다가, 유니버스가 넓어지는 구간만 보면
--     -26%로 부호가 뒤집힌다. 팩터가 아니라 선택 편향이었다.
-- 횡단면 검증을 하려면 매 시점의 진짜 유니버스가 필요한데, 과거는 복구가 안 된다.
-- 지금부터 쌓아야 1년 뒤에 12개월치가 생긴다.
--
-- 용량 설계 — 일별 전 종목을 영구 보관하면 연 88MB라 500MB 티어를 2년 안에 터뜨린다.
-- 그래서 일별은 40일만 굴리는 버퍼로 두고(14MB 고정), 월말 집계만 영구 보관한다
-- (연 4.3MB). 횡단면 팩터는 월별 리밸런싱이라 일별이 필요 없다.
--
-- KRX API 호출은 늘지 않는다 — krx.py는 이미 매일 그날 '전 종목'을 받아놓고
-- 오늘 유니버스가 아닌 걸 버리고 있었다. 버리지 않고 저장만 한다.
--
-- Supabase SQL editor에서 1회 실행.

-- ── 일별 버퍼 (40일 롤링, krx.py가 오래된 행을 지운다) ──
-- 월말 집계를 만들기 위한 임시 저장소일 뿐이라 공개하지 않는다(service_role 전용).
create table if not exists pit_daily (
  code   text not null,
  dt     date not null,
  market text,
  name   text,             -- 월말 집계로 넘길 때 쓴다(폐지 종목 이름 보존)
  close  numeric,
  tval   numeric,          -- 거래대금
  shares numeric,          -- 상장주식수
  mktcap numeric,
  primary key (code, dt)
);
alter table pit_daily enable row level security;

-- ── 월말 스냅샷 (영구) ──
-- 한 번 기록되면 지우지 않는다 — 그래야 상장폐지된 종목이 그 시점 기록으로 남는다.
-- 이게 point-in-time의 전부다.
create table if not exists pit_monthly (
  code     text not null,
  ym       text not null,   -- 'YYYY-MM'
  name     text,            -- 폐지된 종목도 이름을 알 수 있게 같이 저장
  market   text,
  close    numeric,         -- 월말 종가
  mktcap   numeric,         -- 월말 시가총액
  shares   numeric,         -- 월말 상장주식수
  tval_avg numeric,         -- 그달 일평균 거래대금
  vol      numeric,         -- 그달 일간 수익률 표준편차(변동성 팩터용)
  n_days   int,             -- 그달 거래일 수 — 적으면 거래정지·신규상장이라 걸러 쓴다
  primary key (code, ym)
);
alter table pit_monthly enable row level security;
create index if not exists pit_monthly_ym_idx on pit_monthly (ym);
