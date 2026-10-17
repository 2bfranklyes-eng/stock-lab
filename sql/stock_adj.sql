-- stock_adj — 주가 보정 사건(액면분할·병합·무상증자·유상증자 권리락·감자 …) (krx.py 가 갱신)
--
-- 왜 필요한가: stock_daily 는 수정주가가 아니다. 예전엔 '상장주식수가 급변한 날 주가가 그 역수만큼
-- 움직였으면 분할'로 판정했는데, 무상증자·유상증자는 주가가 꺾이는 날(권리락일)과 주식수가 늘어나는
-- 날(신주 상장일, 2~3주 뒤)이 달라 한 번도 걸리지 않았다(실측 티앤엘: 8/6 주가 반토막, 8/28 주식수 2배).
-- 그 종목들은 매물대·주체별 평단·CGO 가 '현재가 위에 매물 잔뜩, −50% 물림'으로 틀리게 나왔다.
--
-- KRX 일별 시세의 '전일대비'(CMPPREVDD_PRC)는 전일 종가가 아니라 그날의 기준가 대비다. 그래서
--   기준가 = 종가 − 전일대비,   ratio = 기준가 ÷ 전일 종가
-- 평소엔 정확히 1이고, 권리락·분할일엔 거래소가 정한 조정 비율이 그대로 나온다(티앤엘 0.506 = 1÷1.977).
-- 그날 이전 가격에 ratio 를 곱하면 수정주가가 된다.
-- ▶ Supabase → SQL Editor 에 붙여넣고 1회 실행.
create table if not exists public.stock_adj (
  code  text not null,          -- 종목코드
  dt    date not null,          -- 권리락·분할 적용일(그날부터 새 기준)
  ratio double precision not null,  -- 기준가 ÷ 전일 종가 (1:1 무상증자 ≈ 0.5, 5:1 액면분할 = 0.2, 감자 > 1)
  primary key (code, dt)
);
alter table public.stock_adj enable row level security;
drop policy if exists "public read stock_adj" on public.stock_adj;
create policy "public read stock_adj" on public.stock_adj for select using (true);
