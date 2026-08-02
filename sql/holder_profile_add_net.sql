-- 주체별 카드에 '기간 전체 순매수/순매도'를 보여주기 위한 컬럼 추가.
-- pos_qty(잔량)는 판 게 산 것보다 많아지면 0에서 다시 세는 값이라, 기간에 실제로
-- 늘었나 줄었나를 못 말한다 — 외국인이 1년 내내 판 종목도 막바지 재매수 잔량만 보여
-- '외국인 물량이 적다'로 오독된다(실사용에서 나온 사례). net_qty가 그 답이다.
-- Supabase SQL editor에서 1회 실행.
alter table holder_profile add column if not exists net_qty numeric;
