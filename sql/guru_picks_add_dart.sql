-- guru_picks 에 DART 전환으로 생긴 열 4개 추가.
--
-- 한국 재무를 야후 → DART(금감원 전자공시)로 바꾸면서, 마법공식(그린블랫)의 두 축을
-- 시장별로 다르게 계산하게 됐다:
--   한국(DART) : 원본 그대로 — ROIC = EBIT ÷ (순운전자본+순고정자산), 이익수익률 = EBIT ÷ 시총
--   미국(야후) : EBIT·투하자본을 무료로 못 얻어 근사 — ROA, 그리고 EBITDA ÷ EV
-- 순위는 어차피 시장별로 따로 매기므로 섞이지 않지만, 어느 자로 쟀는지는 화면에 밝혀야 한다.
-- 그래서 계산에 쓴 값(earn_yield)과 출처(fin_src)를 행마다 같이 저장한다.
-- ▶ Supabase → SQL Editor 에 붙여넣고 1회 실행하면 됩니다.

alter table public.guru_picks add column if not exists roic       double precision;
alter table public.guru_picks add column if not exists ebit       double precision;
alter table public.guru_picks add column if not exists earn_yield double precision;
alter table public.guru_picks add column if not exists fin_src    text;

comment on column public.guru_picks.roic       is 'EBIT ÷ 투하자본. 한국(DART)만 채워진다';
comment on column public.guru_picks.ebit       is '영업이익. 한국(DART)만 채워진다';
comment on column public.guru_picks.earn_yield is '마법공식 이익수익률. 한국 EBIT/시총 · 미국 EBITDA/EV';
comment on column public.guru_picks.fin_src    is '재무 출처 — DART / 야후';
