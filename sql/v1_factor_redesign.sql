-- 요인 재설계(v1)에 필요한 컬럼 추가 — 감사 결과 반영
--   ① inflation_daily.c_food : 물가의 '원자재(DBC)' 성분을 '식품(곡물 3종)'으로 교체.
--      DBC는 구성의 절반이 에너지라 유가를 두 번 세고 있었다(성분 상관 0.84).
--      기존 c_comm 컬럼은 지우지 않고 남겨둔다 — 과거 값 보존용, 새 적재분은 NULL.
--   ② fuel_index.raw3/raw4 : 미국 실탄의 성분(연준자산·재무부계정)을 '절대 $조'로 옮긴다.
--      지금은 c1~c3의 단위가 시장마다 달라(미국=절대 $조, 한국=0~100 백분위) 같은 컬럼에
--      다른 뜻이 담겨 있었다. c1~c3는 양쪽 다 백분위로 통일하고, 절대금액은 raw로 보낸다.
-- ▶ Supabase → SQL Editor 에 붙여넣고 1회 실행하면 됩니다. (RLS/정책은 기존 것 그대로 유지)

alter table public.inflation_daily
  add column if not exists c_food double precision;   -- 식품(옥수수·밀·대두 등가중)

alter table public.fuel_index
  add column if not exists raw3 double precision,     -- 미국: 연준 총자산($조)
  add column if not exists raw4 double precision;     -- 미국: 재무부계정 TGA($조)
