-- 자산배분 국면 지도 — allocation.py가 매일 계산해 채우고, 웹 자산배분 탭이 읽는다.
-- 성장기대 G(t) = 구리/금 비율의 '모멘텀'(63·126·252일 변화의 3년 백분위 평균).
--   구리=산업 수요, 금=피난처 — 비율이 오르는 중이면 시장이 성장 쪽으로 기대를 옮기는 중.
--   시장이 가격에 반영한 기대의 '방향'이지 실물 성장 수준이 아니다 — 화면 해설에 명시.
--   (일드커브 성분은 실측 대조로 기각: 10년-3개월은 연준을 늦게 반영해 2022-06 스태그 공포를
--    놓치고, 호황기 평탄화(2017)를 침체로 오독했다. 근거 수치는 allocation.py 헤더에.)
-- 물가축 i_score는 inflation_daily(US).i_score의 '스냅샷' — 상류 로직이 바뀌어도
-- 국면 이력이 소급해서 출렁이지 않게 여기 박제한다(재현성).
-- 사분면 경계는 50/50 + 히스테리시스(50±3을 완전히 벗어나야 전환) — 경계 근처 잦은 깜빡임 방지.
-- Supabase SQL editor에서 1회 실행.
create table if not exists regime_daily (
  market   text not null default 'GL',  -- 글로벌 단일 국면(재료가 미국·글로벌 가격이라)
  dt       date not null,
  g_score  numeric not null,            -- 성장기대 모멘텀 0~100 (50 위 = 기대 개선 중)
  i_score  numeric not null,            -- 물가압력 0~100 (inflation_daily 스냅샷)
  quadrant text not null,               -- g_up_i_dn / g_up_i_up / g_dn_i_up / g_dn_i_dn
  days_in  int not null,                -- 현 국면 지속 거래일수
  transition boolean not null,          -- 축이 50±5 안(전환주의) — 국면 라벨을 약하게 읽어야 함
  c_m63  numeric,                       -- 성분: 63일 변화 백분위
  c_m126 numeric,                       -- 성분: 126일 변화 백분위
  c_m252 numeric,                       -- 성분: 252일 변화 백분위
  raw_coppergold numeric,               -- 구리/금 실제 비율(카드용)
  primary key (market, dt)
);
alter table regime_daily enable row level security;
drop policy if exists "public read regime_daily" on regime_daily;
create policy "public read regime_daily" on regime_daily for select using (true);
