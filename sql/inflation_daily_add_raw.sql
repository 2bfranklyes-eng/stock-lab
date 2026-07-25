-- inflation_daily 에 '실제 수치' 컬럼 추가 (성분 점수 0~100 옆에 원물 시세를 같이 보여주기 위함)
--   liquidity_daily 의 raw_* 와 같은 역할 — indicator_raw 는 anon 차단이라 프론트가 못 읽으므로
--   파이프라인(inflation.py)이 계산 결과에 실어 미리 적재한다.
-- ▶ Supabase → SQL Editor 에 붙여넣고 1회 실행하면 됩니다. (RLS/정책은 기존 것 그대로 유지)

alter table public.inflation_daily
  add column if not exists raw_wti    double precision,   -- WTI 유가 ($/배럴)   ← c_energy
  add column if not exists raw_copper double precision,   -- 구리 ($/lb)         ← c_metal
  add column if not exists raw_gsci   double precision,   -- S&P GSCI 원자재지수 ← c_comm
  add column if not exists raw_usdkrw double precision;   -- 원/달러 (한국 c_be = 수입물가)
