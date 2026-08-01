-- 매물대 대상 종목 목록 — 웹 '매물대' 탭의 검색 목록이자, 계산 대상의 단일 출처.
-- krx.py가 매일 시총 순위로 갱신한다(코스피 상위 50% + 코스닥 상위 70%).
-- 프론트가 이 표만 읽으면 '검색되는데 데이터가 없는' 불일치가 구조적으로 생기지 않는다.
create table if not exists vp_stocks (
  code      text primary key,   -- 종목코드 6자리
  name      text not null,
  market    text not null,      -- KOSPI / KOSDAQ
  marcap    numeric,            -- 시가총액(원) — 검색 결과 정렬용
  hist_days int not null        -- 이 종목이 보유한 히스토리 길이(1825=5년 / 730=2년).
                                -- 프론트는 이 값보다 긴 집계 구간 버튼을 감춘다 —
                                -- 2년치뿐인 종목에 '5년'을 보여주면 2년 그림이 5년인 척하게 된다.
);
alter table vp_stocks enable row level security;
drop policy if exists "public read vp_stocks" on vp_stocks;
create policy "public read vp_stocks" on vp_stocks for select using (true);
