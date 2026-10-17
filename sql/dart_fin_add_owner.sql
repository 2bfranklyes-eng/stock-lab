-- dart_fin 에 지배주주 몫 두 칸 추가 (2026-10-17 로직 검토)
-- 한국 PER·PBR·ROE 는 지배주주 순이익·지배주주 자본이 관행 기준이다. 연결 순이익·자본총계에는
-- 비지배지분 몫이 섞여 자회사 지분율이 낮은 지주사가 실제보다 훨씬 싸 보였다
-- (실측 SK㈜: 연결 순이익 28.0조 vs 지배주주 8.0조 → PER 3.5배 차이).
-- 별도 재무제표만 내는 회사는 총계와 같은 값이 들어간다.
-- ▶ Supabase → SQL Editor 에 붙여넣고 1회 실행. 값은 다음 dart.py 실행(토요일 크론)부터 채워진다.
alter table public.dart_fin
  add column if not exists net_income_owner double precision,   -- 지배주주 순이익 (TTM)
  add column if not exists equity_owner     double precision;   -- 지배주주 자본 (분기말 잔액)
