-- stock_meta 에 ROA · EV/EBITDA 두 열 추가 — guru.py 의 마법공식(그린블랫)이 쓴다.
--
-- 왜 여기에 붙이는가: screener.py 가 이미 한국 500종목의 yfinance info 를 부르고 있고,
-- 이 두 값은 그 응답 안에 이미 들어 있다. guru.py 가 따로 받으면 주 1회 요청이 500건 늘어
-- 야후 rate limit 에 걸린다(실측: 별도 수집 시 500종목 중 135종목만 채워지고 나머지는
-- YFRateLimitError — 그런데 그 실패가 '지표 없는 종목'과 구분이 안 돼 결과가 조용히 반쪽이 됐다).
--
-- 왜 ROE 가 아니라 ROA 인가: 자사주 매입으로 자본이 거의 없어진 회사는 ROE 가 수천 %로 뜬다
-- (실측: Masco 5862%). 회계 부산물이 실력으로 둔갑해 마법공식 순위가 통째로 망가진다.
-- ▶ Supabase → SQL Editor 에 붙여넣고 1회 실행한 뒤 `python screener.py` 를 다시 돌리면 채워집니다.

alter table public.stock_meta add column if not exists roa       double precision;
alter table public.stock_meta add column if not exists ev_ebitda double precision;

comment on column public.stock_meta.roa       is '순이익 ÷ 총자산 (소수, 0.05 = 5%)';
comment on column public.stock_meta.ev_ebitda is 'EV ÷ EBITDA. 역수가 이익수익률';
