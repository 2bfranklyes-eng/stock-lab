# stock-lab — 시장 심리 대시보드

미국(그리고 곧 한국) 주식시장의 **심리점수 S(t)** 를 계산·검증·시각화하는 개인 프로젝트.
Supabase(방과후와 별도 프로젝트) + Python 파이프라인 + React 대시보드.

**라이브**: https://2bfranklyes-eng.github.io/stock-lab/

## 구조
- `ingest.py` — 원천 지표(VIX·S&P500·TLT·RSP·SPY) 수집 → Supabase `indicator_raw`
- `sentiment.py` — S(t) 심리점수 계산 → `sentiment_daily`
- `backtest.py` — 밴드별 이후수익률 검증 → `backtest_stats`
- `plot.py` — 로컬 검증용 그래프 (matplotlib)
- `web/` — Vite+React 대시보드 (GitHub Pages 배포)
- `.github/workflows/` — `deploy.yml`(Pages 배포), `refresh.yml`(평일 데이터 자동 갱신)

## 🖥️ 다른 컴퓨터에서 이어하기

`.env` 계열(키 파일)은 git에 안 올라가니, 새 컴퓨터에선 이 3가지만 하면 됩니다.

```bash
# 1) 클론
git clone https://github.com/2bfranklyes-eng/stock-lab.git
cd stock-lab

# 2) 파이썬 준비 + 키 파일(.env) 만들기
pip install -r requirements.txt
#   .env.example 을 복사해 .env 로 만들고 SUPABASE_SERVICE_KEY 채우기
#   (service_role 키 = Supabase → Settings → API. 이 프로젝트 GitHub Secrets 에도 있음)

# 3) 웹 준비 + 로컬 dev 키
cd web
npm install
#   web/.env.production 을 복사해 web/.env.local 로 저장하면 로컬 dev도 데이터 뜸
npm run dev        # http://localhost:5173/
```

## 실행
```bash
python ingest.py      # 원천 수집
python sentiment.py   # 심리점수 계산
python backtest.py    # 검증
```

## 주의
- **`service_role`(secret) 키**는 `.env` 에만. GitHub·클라이언트 노출 금지. (자동갱신 크론은 GitHub Secrets 사용)
- `anon` 키는 공개용(RLS 보호) → `web/.env.production` 에 커밋돼 있음.
- 미국 휴장일에 VIX만 값이 들어오는 "반쪽 행"이 rolling 창을 오염시키므로, `sentiment.py`는 피벗 후 `dropna()`로 5개 지표가 다 있는 날만 사용.

## 다음 할 일
- 🇰🇷 한국 시장(pykrx·FinanceDataReader) 추가 → 대시보드 오른쪽 칸 채우기
- 풋콜/VIX 기간구조 등 심리 성분 정밀화
