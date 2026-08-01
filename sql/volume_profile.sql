-- 매물대(미소화 물량 추정) 테이블 — profile.py가 매일 채움(refresh 크론), 웹 '매물대' 탭이 읽음.
-- 집계 구간(win_days)별로 가격 구간(bin)마다 '아직 안 팔린 물량' 비중(share, 합 100)을 저장.
-- Supabase SQL editor에서 1회 실행.
create table if not exists volume_profile (
  code     text not null,      -- kospi / kosdaq / spx / nasdaq / dow
  win_days int  not null,      -- 집계 구간(달력일): 1825/1095/730/365/182/91/30
  bin_lo   numeric not null,   -- 가격 구간 하단
  bin_hi   numeric not null,   -- 가격 구간 상단
  share    numeric not null,   -- 미소화 잔존 비중(%) — 같은 (code, win_days) 안에서 합 100
  px       numeric not null,   -- 계산 시점 종가(위/아래 판정 기준)
  dt       date not null,      -- 마지막 데이터 일자
  primary key (code, win_days, bin_lo)
);
alter table volume_profile enable row level security;
drop policy if exists "public read volume_profile" on volume_profile;
create policy "public read volume_profile" on volume_profile for select using (true);
