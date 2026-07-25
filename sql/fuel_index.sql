-- 증시 실탄(자금유입) 지수 — 미국 주간(FRED 순유동성) / 한국 월간(ECOS M2·수급)
-- Supabase SQL editor에서 1회 실행. 웹은 anon 키로 read 하므로 public select 정책 부여.
-- 성분(c1~c3)은 시장별 의미가 다름(웹 config가 라벨 매핑):
--   US: c1=연준자산(WALCL) c2=재무부계정(TGA,반전) c3=역레포(RRP,반전) / raw1=순유동성$T raw2=역레포$B
--   KR: c1=M2증가율 c2=외국인순매수 c3=개인순매수 / raw1=M2 YoY% raw2=외국인 순매수(월)
--   freq: 'W'(미국 주간) / 'M'(한국 월간) — 웹에서 '월간' 뱃지 표시에 사용

create table if not exists fuel_index (
  market      text not null,
  dt          date not null,
  f_score     numeric,
  band        text,
  c1          numeric,
  c2          numeric,
  c3          numeric,
  raw1        numeric,
  raw2        numeric,
  freq        text,
  computed_at timestamptz default now(),
  primary key (market, dt)
);

create table if not exists fuel_backtest_stats (
  market text not null,
  band   text not null,
  n      int,
  fwd5   numeric, hit5  numeric,
  fwd10  numeric, hit10 numeric,
  fwd20  numeric, hit20 numeric,
  fwd30  numeric, hit30 numeric,
  fwd60  numeric, hit60 numeric,
  primary key (market, band)
);

alter table fuel_index enable row level security;
alter table fuel_backtest_stats enable row level security;

-- 공개 읽기(익명) 허용 — 다른 *_daily 테이블과 동일 정책
drop policy if exists "public read fuel_index" on fuel_index;
create policy "public read fuel_index" on fuel_index for select using (true);
drop policy if exists "public read fuel_backtest_stats" on fuel_backtest_stats;
create policy "public read fuel_backtest_stats" on fuel_backtest_stats for select using (true);
