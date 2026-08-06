-- 주체별 미실현손익(CGO, Capital Gains Overhang) 시계열 — cgo.py가 채운다.
--
-- 이론: 처분효과(Shefrin & Statman 1985) + Grinblatt & Han(2005).
--   사람은 오른 건 빨리 팔고 물린 건 붙들고 있어서, '얼마나 물려 있나'가 곧 매도 압력의 지도다.
--   개인이 깊이 물려 있으면 반등마다 본전 매도가 나오고, 극단으로 가면 팔 사람이 소진된다.
--
-- holder_profile은 '오늘 스냅샷'이라 과거가 없다. 이 표는 investor_flow(2024-07~) 캐시를
-- 되감아 만든 시계열이라 게이지·추이·백분위를 그릴 수 있다.
-- 프론트가 직접 읽으므로 public read (원자료 investor_flow는 계속 service_role 전용).
-- Supabase SQL editor에서 1회 실행.

-- 평단을 '최근 N일 창'에서 '반감기 N일 감쇠 가중'으로 바꾸며 열 이름도 바로잡는다.
-- 창을 자르면 N일 전 대량 매수가 빠지는 날 여러 종목 평단이 동시에 점프했다(하루 ±10%p).
-- 이미 win_days로 만들어 둔 표가 있으면 이름만 갈아끼운다.
do $$ begin
  if exists (select 1 from information_schema.columns
             where table_name = 'cgo_daily' and column_name = 'win_days') then
    alter table cgo_daily rename column win_days to hl_days;
  end if;
end $$;

create table if not exists cgo_daily (
  dt        date not null,
  hl_days   int  not null,     -- 매수 무게의 반감기(달력일): 182 / 365
  inv       text not null,     -- 기관합계 / 기타법인 / 개인 / 외국인합계
  n_stocks  int,               -- 그날 계산에 들어간 종목 수
  cgo_med   numeric,           -- 미실현손익률 중앙값(%) — 헤드라인. 평균은 이상치에 흔들린다
  cgo_avg   numeric,           -- 평균(%)
  under_pct numeric,           -- 물린(손실) 종목 비율(%)
  deep_pct  numeric,           -- 크게 물린(-20% 이하) 종목 비율(%)
  primary key (dt, hl_days, inv)
);
alter table cgo_daily enable row level security;
drop policy if exists "public read cgo_daily" on cgo_daily;
create policy "public read cgo_daily" on cgo_daily for select using (true);

-- 열을 바꾼 직후엔 PostgREST가 옛 스키마를 캐시하고 있어 적재가
-- PGRST204("Could not find the 'hl_days' column")로 막힌다. 캐시를 즉시 갱신시킨다.
notify pgrst, 'reload schema';
