# stock-lab

시장 심리·유동성 분석 실험실. Supabase(별도 프로젝트) + Python 수집.

## 구조
- `ingest.py` — 미국 원천 지표(VIX·S&P500·TLT) 수집 → Supabase `indicator_raw`
- `.env` — 키 (Git에 안 올림). `SUPABASE_URL`, `SUPABASE_SERVICE_KEY`
- 다음: `S(t)` 심리점수 계산 → `sentiment_daily` 적재

## 실행
```powershell
pip install -r requirements.txt
# .env 의 SUPABASE_SERVICE_KEY 를 Supabase Settings→API 의 service_role 키로 채우기
python ingest.py
```

## 확인 (Supabase SQL Editor)
```sql
select code, count(*) 행수, min(dt) 시작, max(dt) 끝
from indicator_raw group by code order by code;
```

## 주의
- `service_role` 키는 `.env` 에만. GitHub·클라이언트 노출 금지.
- 대시보드는 `anon` 키 + RLS 읽기 정책으로 `sentiment_daily`만 조회.
