-- 투자자별(기관·기타법인·개인·외국인) 일별 순매수 원자료 — holders.py가 pykrx로 채우는 캐시.
-- 이게 없으면 매일 전 종목 × 2년치를 다시 스크래핑해야 한다(KRX 부하·차단 위험).
-- 프론트는 집계 결과(holder_profile)만 읽으므로 원자료는 공개하지 않는다(service_role 전용).
-- Supabase SQL editor에서 1회 실행.
create table if not exists investor_flow (
  code text not null,          -- 종목코드 6자리
  dt   date not null,
  inv  text not null,          -- 기관합계 / 기타법인 / 개인 / 외국인합계
  vol  numeric not null,       -- 순매수 수량(주, 음수 = 순매도)
  val  numeric not null,       -- 순매수 대금(원) — 주체별 평균 매입단가 계산용
  primary key (code, dt, inv)
);
alter table investor_flow enable row level security;
