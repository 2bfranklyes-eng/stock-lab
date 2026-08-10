# stock-lab — 시장 심리 대시보드

미국(그리고 곧 한국) 주식시장의 **심리점수 S(t)** 를 계산·검증·시각화하는 개인 프로젝트.
Supabase(방과후와 별도 프로젝트) + Python 파이프라인 + React 대시보드.

**라이브**: https://2bfranklyes-eng.github.io/stock-lab/

## 구조
- `ingest.py` — 원천 지표(VIX·S&P500·TLT·RSP·SPY) 수집 → Supabase `indicator_raw`
- `sentiment.py` — S(t) 심리점수 계산 → `sentiment_daily`
- `backtest.py` — 심리 밴드별 이후수익률 검증 → `backtest_stats`
- `liquidity.py` — L(t) 유동성 지수 계산 → `liquidity_daily`
- `liquidity_backtest.py` — 유동성 밴드별 이후수익률 검증 → `liquidity_backtest_stats`
- `inflation.py` — I(t) 물가 지수 계산(시장 반영 물가압력) → `inflation_daily`
- `inflation_backtest.py` — 물가 밴드별 이후수익률 검증 → `inflation_backtest_stats`
- `holders.py` — 주체별(개인·외국인·기관) 순매수 누적 매물대 → `investor_flow`(캐시)·`holder_profile` (KRX 정보데이터시스템 로그인 필요). 시총 상위 200 + `SCREENER_ALWAYS`
- `allocation.py` — 자산배분 국면(성장기대=구리/금 모멘텀 × 물가=I(t) 스냅샷) + 자산 8종 위치 점수 → `regime_daily`·`asset_daily`
- `allocation_backtest.py` — 국면별 자산 이후수익률 통계(n_episodes 병기, 자산통화·원화 환산) → `asset_regime_stats`
- `allocation_shock.py` — 충격완화 통계: 주식 급락월 조건표 + 위기 리플레이 6건(원화 환산 병기) → `asset_shock_stats`
- `screener.py` — 개별 종목 재무 스냅샷(한국 시총 상위 500) + 월말 종가 → `stock_meta`·`stock_monthly`
- `dart.py` — 금감원 전자공시(DART) 원문 재무제표 → `dart_fin`. 야후 한국 재무는 결측이 커서
  (PER 31%·이익성장 40%) '기준 미달'과 '판정 불가'가 구분되지 않았다. DART 는 결측이 없고
  영업이익(=EBIT)·투하자본까지 있어 마법공식을 원본대로 계산할 수 있다.
  ⚠️ 대신 **더 느리다** — 정기보고서만 담아서 7월 잠정실적은 안 들어온다(분기 전환기 2~3주는 야후가 앞섬)
- `guru.py` — 투자 대가 5인(버핏·그레이엄·린치·그린블랫·오닐)의 기준으로 미국(S&P500)·한국을
  걸러 `guru_picks`. 한국 재무 = `dart_fin`, 시세·섹터·차입금 = `stock_meta`, 미국 = 야후 직접 수집
  → **`screener.py` → `dart.py` → `guru.py` 순서로 돌려야 한다**
- `crossval.py` / `crossval_models.py` — 매물대 모델을 투자자 실측(B)과 대조 검증 (로컬 전용)
- `sql/` — 테이블 DDL(수동 생성용). 새 테이블 추가 시 여기 SQL을 Supabase SQL Editor에 실행
- `plot.py` — 로컬 검증용 그래프 (matplotlib)
- `web/` — Vite+React 대시보드 (GitHub Pages 배포)
- `.github/workflows/` — `deploy.yml`(Pages 배포), `refresh.yml`(한국 오전 7시, 미국 마감 후 전체 갱신),
  `refresh_kr.yml`(한국 오후 6시, 코스피 마감 반영 — 저녁에 열어도 당일 지표가 보이게)

## 🖥️ 다른 컴퓨터에서 이어하기

`.env` 계열(키 파일)은 git에 안 올라가니, 새 컴퓨터에선 이 3가지만 하면 됩니다.

```bash
# 1) 클론
git clone https://github.com/2bfranklyes-eng/stock-lab.git
cd stock-lab

# 2) 파이썬 준비 + 키 파일(.env) 만들기
pip install -r requirements.txt
#   .env.example 을 복사해 .env 로 만들고 아래를 채우기
#   · SUPABASE_SERVICE_KEY — service_role 키 = Supabase → Settings → API
#     (GitHub Secrets 에도 있지만 GitHub은 저장된 값을 다시 안 보여주므로 Supabase에서 복사)
#   · KRX_ID / KRX_PW — data.krx.co.kr 정보데이터시스템 로그인. holders.py(주체별 실측)에만 필요.
#     없으면 holders.py가 스스로 건너뛰고 나머지는 정상 동작.

# 3) 웹 준비 + 로컬 dev 키
cd web
npm install
#   web/.env.production 을 복사해 web/.env.local 로 저장하면 로컬 dev도 데이터 뜸
npm run dev        # http://localhost:5173/
```

> 윈도우에서 `python`이 Microsoft Store 안내를 띄우면, 스토어 스텁이 PATH를 가로챈 것입니다.
> python.org 설치 후 **설정 → 앱 → 앱 실행 별칭**에서 python.exe 별칭을 끄세요.

## 실행
```bash
python ingest.py             # 원천 수집
python sentiment.py          # 심리점수 계산
python liquidity.py          # 유동성 지수 계산
python inflation.py          # 물가 지수 계산
python backtest.py           # 심리 밴드별 검증
python liquidity_backtest.py # 유동성 밴드별 검증
python inflation_backtest.py # 물가 밴드별 검증
```

## 주의
- **`service_role`(secret) 키**는 `.env` 에만. GitHub·클라이언트 노출 금지. (자동갱신 크론은 GitHub Secrets 사용)
- `anon` 키는 공개용(RLS 보호) → `web/.env.production` 에 커밋돼 있음.
- 미국 휴장일에 VIX만 값이 들어오는 "반쪽 행"이 rolling 창을 오염시키므로, `sentiment.py`는 피벗 후 `dropna()`로 5개 지표가 다 있는 날만 사용.

## 다음 할 일
- **주체별 매물대 신규 종목 백필 진행 중** — 커버리지를 50→200으로 넓혔다. 신규 162종목은
  KRX 차단을 피하려 실행당 40종목씩만 받으므로(`NEW_PER_RUN`) 평일 크론 4회쯤이면 다 찬다.
  진행 상황은 실행 끝의 "백필 대기 N종목" 줄로 본다. 급하면 `python holders.py <코드…>` 로 지정 실행.
- 풋콜/VIX 기간구조 등 심리 성분 정밀화

## 주체별 매물대 커버리지를 더 넓히려면
상한을 정하는 건 이제 KRX 부하가 아니라 **Supabase 무료 티어(저장 500MB)** 다. 벌크 엔드포인트로 바꾼 뒤
일일 호출은 종목수와 무관하게 10회지만, 저장은 **종목당 약 410KB**씩 는다(`holder_profile` 960행
+ `investor_flow` 1,976행). 39종목 적재 전후 대시보드가 296MB→312MB로 움직인 걸로 실측한 값이다.
`investor_flow`는 해마다 종목당 ~120KB씩 더 는다.

2026-08 기준 사용량 312MB(62%) — 이 중 ~50MB는 같은 조직의 방과후 프로젝트 몫이다.

| 커버리지 | 예상 총 사용량 |
|---|---|
| 200 (현행, 백필 완료 시) | ~362MB (72%) |
| 300 | ~403MB (81%) |
| 500 | ~485MB (97%) ❌ |

**300이 현실적 상한이고 200에서 멈추는 게 안전하다.** 더 가려면 창을 4개→2개로 줄이거나 `NBINS` 를
낮추는 기능 트레이드오프, 또는 유료 전환이 필요하다. 늘리기 전엔 Supabase → Settings → Usage 재확인.

## 매물대 모델을 바꾸고 싶다면
`crossval_models.py` 가 심판대다 — 감쇠 모델(A)을 **투자자 순매수 실측(B)** 과의 분포 상관으로
평가한다. An(2016)류 이중속도·V자 확장을 이걸로 검증해 **기각**했고(현행 G&H 단일속도 유지),
근거 수치는 그 파일 헤더에 있다. 새 아이디어도 여기부터 통과시킬 것.
⚠️ 모델 내부 진단(두께↔변동성 상관)은 실측과 **반대 방향**을 가리켰다 — 판정 기준으로 쓰지 말 것.
