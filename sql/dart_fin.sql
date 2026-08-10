-- dart_fin — 금융감독원 DART 전자공시 원문 재무제표 (dart.py 가 갱신)
--
-- 야후 대신 이걸 쓰는 이유는 '속도'가 아니라 '커버리지'다.
--   · 야후 한국 재무 결측: PER 31% · 이익성장 40% · ROA 20% (실측)
--     → 그 종목들은 기준 미달이 아니라 '판정 불가'로 스크리너에서 조용히 빠진다
--   · DART 는 원문이라 결측이 없다 (샘플 60종목에서 1분기·사업보고서 59/59)
--
-- ⚠️ 반대로 DART 가 더 '느리다'. 이 API 는 정기보고서(사업·반기·분기)만 담고 7월에 나오는
--    잠정실적 공시는 안 들어온다. 분기 전환기 2~3주는 야후가 앞선다
--    (실측 2026-08-10: 야후는 삼성전자 2026-06-30, DART 는 아직 2026-03-31).
--
-- 손익 항목(revenue·op_income·net_income)은 전부 **TTM(최근 12개월)** 이다:
--   TTM = 직전 사업보고서 연간 + 당기 누적 − 전년 동기 누적
--   분기 누적을 그대로 쓰면 1분기 보고서일 때 PER 이 4배로 부풀고, 4를 곱하면 계절성이 큰
--   업종(조선·유통)이 왜곡된다.
-- 재무상태표 항목(assets·equity 등)은 그 분기말 시점 잔액이다.
-- ▶ Supabase → SQL Editor 에 붙여넣고 1회 실행하면 됩니다.

create table if not exists public.dart_fin (
  code             text primary key,   -- 거래소 종목코드 '005930'
  corp_code        text,               -- DART 고유번호 '00126380'
  name             text,
  market           text,               -- KOSPI / KOSDAQ / KONEX
  fs_div           text,               -- CFS(연결) / OFS(별도) — 연결 우선, 없으면 별도
  reprt            text,               -- 11011 사업 / 11013 1분기 / 11012 반기 / 11014 3분기
  bsns_year        int,
  fiscal_q         date,               -- 그 보고서가 다루는 분기말 (= 재무 기준일)
  rcept_no         text,               -- 공시 접수번호. dart.fss.or.kr/dsaf001/main.do?rcpNo=… 로 원문 확인 가능

  -- 손익 (TTM)
  revenue          double precision,
  op_income        double precision,   -- 영업이익 = 한국 회계기준의 EBIT
  net_income       double precision,

  -- 재무상태표 (분기말 잔액)
  assets           double precision,
  liabilities      double precision,
  equity           double precision,
  cur_assets       double precision,
  cur_liabilities  double precision,
  ppe              double precision,   -- 유형자산

  -- 성장률: 전년 '동기 누적' 대비. 야후 earningsGrowth 는 기저가 작으면 320배 같은 값이
  -- 나오는데, 여기선 원문 두 숫자를 직접 나눈다. 기저가 적자면 무의미해서 null.
  rev_growth       double precision,   -- 소수 (0.15 = 15%)
  earn_growth      double precision,

  -- 파생 지표
  roe              double precision,   -- 순이익 ÷ 자본 (소수)
  roa              double precision,   -- 순이익 ÷ 총자산 (소수)
  op_margin        double precision,
  profit_margin    double precision,
  debt_ratio       double precision,   -- ⚠️ 한국식 총부채÷자본 (%). 야후 debt_to_equity 는
                                       --    '총차입금' 기준이라 같은 회사도 값이 크게 다르다.
  -- 그린블랫 원본 공식용. 미국은 EBIT 를 못 구해 ROA·EBITDA/EV 로 근사하지만 한국은 원본이 된다.
  ebit             double precision,
  invested_capital double precision,   -- 순운전자본(유동자산−유동부채, 음수면 0) + 유형자산
  roic             double precision,   -- EBIT ÷ 투하자본

  updated_at       timestamptz default now()
);

create index if not exists dart_fin_market_idx on public.dart_fin (market);

alter table public.dart_fin enable row level security;

drop policy if exists "dart_fin anon read" on public.dart_fin;
create policy "dart_fin anon read" on public.dart_fin for select to anon using (true);
