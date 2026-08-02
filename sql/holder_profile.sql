-- 주체별 순매수 누적 매물대 — holders.py가 매일 계산해 채우고, 웹 매물대 탭(개별종목)이 읽는다.
-- KRX 투자자별 순매수(실측)를 누적하되, 순매도일엔 '그 주체 보유분 전체에서 비례로 뺀다'는
-- 가정이 들어간다(감쇠 모델의 비례 가정을 주체별로 적용한 것). 판 게 산 것보다 많아지면
-- 0에서 다시 센다 — 그래서 pos_qty는 보유 지분이 아니고 주체 간 크기 비교로도 못 쓴다.
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
  pos_qty  numeric,            -- 이 주체의 창 내 순매수 잔량(주) — 0 리셋 있음, 보유 지분 아님
  net_qty  numeric,            -- 창 전체 단순 순매수 합(주, 음수=순매도) — 리셋 없는 값.
                               -- '기간에 실제로 늘었나 줄었나'는 이걸 본다
  avg_cost numeric,            -- 잔량의 평균 매입단가(원) — 순매수일 대금÷수량 가중
  px       numeric not null,   -- 계산 시점 종가
  dt       date not null,      -- 마지막 데이터 일자
  primary key (code, win_days, inv, bin_lo)
);
alter table holder_profile enable row level security;
drop policy if exists "public read holder_profile" on holder_profile;
create policy "public read holder_profile" on holder_profile for select using (true);
