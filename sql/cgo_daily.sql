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
create table if not exists cgo_daily (
  dt        date not null,
  win_days  int  not null,     -- 집계 창(달력일): 182 / 365
  inv       text not null,     -- 기관합계 / 기타법인 / 개인 / 외국인합계
  n_stocks  int,               -- 그날 계산에 들어간 종목 수
  cgo_med   numeric,           -- 미실현손익률 중앙값(%) — 헤드라인. 평균은 이상치에 흔들린다
  cgo_avg   numeric,           -- 평균(%)
  under_pct numeric,           -- 물린(손실) 종목 비율(%)
  deep_pct  numeric,           -- 크게 물린(-20% 이하) 종목 비율(%)
  primary key (dt, win_days, inv)
);
alter table cgo_daily enable row level security;
drop policy if exists "public read cgo_daily" on cgo_daily;
create policy "public read cgo_daily" on cgo_daily for select using (true);
