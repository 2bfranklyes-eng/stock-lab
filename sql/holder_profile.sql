-- 주체별 '실측' 매물대 — holders.py가 매일 계산해 채우고, 웹 매물대 탭(개별종목)이 읽는다.
-- volume_profile(감쇠 모델 추정)과 달리 KRX 투자자별 순매수의 누적 실측이라 가정이 없다.
-- 순매수일엔 그날 고가~저가에 배분해 쌓고, 순매도일엔 그 주체 보유분에서 비례로 뺀다.
-- 창(win_days) 구간의 순매수만 보이므로 '창 이전부터 든 물량'은 없다 — 화면에 명시할 것.
--
-- avg_cost·pos_qty는 같은 (code, win_days, inv) 안에서 모든 행이 같은 값이라 중복이지만,
-- volume_profile의 px·dt와 같은 방식이다 — 조인 없이 한 번의 조회로 화면을 그리려는 의도.
-- Supabase SQL editor에서 1회 실행.
create table if not exists holder_profile (
  code     text not null,      -- 종목코드 6자리
  win_days int  not null,      -- 집계 구간(달력일): 91/182/365/730
  inv      text not null,      -- 기관합계 / 기타법인 / 개인 / 외국인합계
  bin_lo   numeric not null,   -- 가격 구간 하단
  bin_hi   numeric not null,   -- 가격 구간 상단
  qty      numeric not null,   -- 이 주체가 이 구간에서 사서 아직 안 판 추정 수량(주)
  share    numeric not null,   -- 전체(4주체 합) 대비 % — 같은 (code, win_days) 안에서 합 100
  pos_qty  numeric,            -- 이 주체의 창 구간 보유 수량 합(주)
  avg_cost numeric,            -- 이 주체의 평균 매입단가(원) — 순매수일 대금÷수량 가중
  px       numeric not null,   -- 계산 시점 종가
  dt       date not null,      -- 마지막 데이터 일자
  primary key (code, win_days, inv, bin_lo)
);
alter table holder_profile enable row level security;
drop policy if exists "public read holder_profile" on holder_profile;
create policy "public read holder_profile" on holder_profile for select using (true);
