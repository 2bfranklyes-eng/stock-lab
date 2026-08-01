import { useEffect, useMemo, useState } from 'react'
import {
  LineChart, Line, XAxis, YAxis, Tooltip,
  ResponsiveContainer, ReferenceLine, CartesianGrid,
} from 'recharts'
import { supabase, hasKey } from './supabaseClient'
import './App.css'

const BANDS = [
  { name: '극단공포', color: '#2471a3' },
  { name: '공포', color: '#5dade2' },
  { name: '중립', color: '#95a5a6' },
  { name: '탐욕', color: '#e59866' },
  { name: '극단탐욕', color: '#c0392b' },
]
function bandOf(v) {
  if (v < 20) return BANDS[0]
  if (v < 40) return BANDS[1]
  if (v < 60) return BANDS[2]
  if (v < 80) return BANDS[3]
  return BANDS[4]
}
const BAND_DESC = {
  극단공포: '다들 겁에 질린 상태. 역사적으로는 반등이 잦았어요.',
  공포: '시장이 움츠러든 분위기.',
  중립: '뚜렷한 쏠림 없이 평범한 상태.',
  탐욕: '시장이 달아오른 분위기.',
  극단탐욕: '과열 상태. 역사적으로는 조정이 뒤따르기도 했어요.',
}
const STAT_ORDER = ['극단공포', '공포', '중립', '탐욕', '극단탐욕', '전체']
const SENT_STATS_NOTE = (
  <><b>극단공포</b> 뒤 반등이 뚜렷(역발상 엣지), <b>극단탐욕</b>은 밋밋. 20거래일 ≈ 1달. (표본 적어 참고용)</>
)

// 추이 그래프의 선들. 성분(변동성·모멘텀·안전자산선호·시장폭)은 s_score를 이루는 4재료.
// 배열 순서 = 범례 표시 순서(종합이 맨 앞). 색은 dataviz 검증 팔레트(대비·색각 통과).
// 그리는 순서는 따로(성분 먼저 → 종합이 맨 위) 처리해 종합선이 안 가리게 함.
const SERIES = [
  { key: 's_score', name: '심리점수(종합)', color: '#d97706', width: 2.2 },
  { key: 'c_vix', name: '변동성', color: '#2a78d6', width: 1.3 },
  { key: 'c_mom', name: '모멘텀', color: '#008300', width: 1.3 },
  { key: 'c_shv', name: '위험 선호', color: '#d55181', width: 1.3 },
  { key: 'c_breadth', name: '시장 폭', color: '#4a3aa7', width: 1.3 },
]

// 유동성 지수 L(t): 종합 + 4성분 (높을수록 완화). 색은 심리와 같은 검증 팔레트.
// raw(point, market): 툴팁에 띄울 '실제 수치'(점수 0~100과 별개). liquidity_daily에 저장된
//   raw_* 컬럼에서 읽음 — KR은 raw_us10y=국고채10년, raw_dxy=신용스프레드로 의미가 다름에 주의.
const wonFmt = (v) => (v == null ? null : Math.round(v).toLocaleString() + '원')
const L_SERIES = [
  { key: 'l_score', name: '유동성(종합)', color: '#d97706', width: 2.2 },
  { key: 'c_rate', name: '금리', color: '#2a78d6', width: 1.3,
    raw: (p) => (p.raw_us10y == null ? null : p.raw_us10y.toFixed(2) + '%') },
  { key: 'c_curve', name: '일드커브', color: '#008300', width: 1.3,
    raw: (p) => (p.raw_curve == null ? null : (p.raw_curve >= 0 ? '+' : '') + p.raw_curve.toFixed(2) + '%p') },
  { key: 'c_fx', name: '환율', color: '#d55181', width: 1.3,
    raw: (p, m) => (m === 'US' ? (p.raw_dxy == null ? null : p.raw_dxy.toFixed(1)) : wonFmt(p.raw_usdkrw)) },
  { key: 'c_credit', name: '신용', color: '#4a3aa7', width: 1.3,
    raw: (p, m) => (m === 'KR' && p.raw_dxy != null ? p.raw_dxy.toFixed(2) + '%p' : null) },
]
const L_BANDS = [
  { name: '극단긴축', color: '#c0392b' },
  { name: '긴축', color: '#e59866' },
  { name: '중립', color: '#95a5a6' },
  { name: '완화', color: '#52b788' },
  { name: '극단완화', color: '#1e8449' },
]
function liqBandOf(v) {
  if (v < 20) return L_BANDS[0]
  if (v < 40) return L_BANDS[1]
  if (v < 60) return L_BANDS[2]
  if (v < 80) return L_BANDS[3]
  return L_BANDS[4]
}
const L_BAND_DESC = {
  극단긴축: '돈줄이 크게 조인 상태. 자산엔 역풍.',
  긴축: '유동성이 마르는 분위기.',
  중립: '완화도 긴축도 아닌 평범한 상태.',
  완화: '돈이 풀리는 분위기. 자산엔 순풍.',
  극단완화: '유동성이 넘치는 상태.',
}
const L_STAT_ORDER = ['극단긴축', '긴축', '중립', '완화', '극단완화', '전체']
const LIQ_STATS_NOTE = (
  <>돈이 <b>풀린(완화)</b> 뒤 순풍인지, <b>조인(긴축)</b> 뒤 역풍인지. 20거래일 ≈ 1달. (표본 적어 참고용)</>
)

// 물가지수 I(t): 종합 + 4성분 (높을수록 물가↑). 색은 심리·유동성과 같은 검증 팔레트.
// raw(point, market): 유동성과 같은 방식 — 성분 점수(0~100) 옆에 대응하는 원물 시세를 띄운다.
//   기대인플레는 미국이 TIP/IEF '비율'이라 자연스러운 단위가 없어 한국(원/달러)만 표시.
const usdFmt = (v, d = 2) => (v == null ? null : '$' + v.toFixed(d))
const I_SERIES = [
  { key: 'i_score', name: '물가(종합)', color: '#d97706', width: 2.2 },
  { key: 'c_be', name: '기대인플레', color: '#2a78d6', width: 1.3,
    raw: (p, m) => (m === 'KR' ? wonFmt(p.raw_usdkrw) : null) },
  { key: 'c_energy', name: '에너지', color: '#008300', width: 1.3,
    raw: (p) => usdFmt(p.raw_wti, 1) },
  // 식품 = 옥수수·밀·대두 등가중 지수라 자연스러운 단위가 없어 실수치는 생략.
  { key: 'c_food', name: '식품', color: '#d55181', width: 1.3 },
  { key: 'c_metal', name: '산업금속', color: '#4a3aa7', width: 1.3,
    raw: (p) => usdFmt(p.raw_copper) },
]
// 물가는 온도계식: 낮을수록 저물가(파랑)·높을수록 고물가(빨강) — 심리 팔레트와 같은 방향.
const I_BANDS = [
  { name: '극단저물가', color: '#2471a3' },
  { name: '저물가', color: '#5dade2' },
  { name: '중립', color: '#95a5a6' },
  { name: '고물가', color: '#e59866' },
  { name: '극단고물가', color: '#c0392b' },
]
function infBandOf(v) {
  if (v < 20) return I_BANDS[0]
  if (v < 40) return I_BANDS[1]
  if (v < 60) return I_BANDS[2]
  if (v < 80) return I_BANDS[3]
  return I_BANDS[4]
}
const I_BAND_DESC = {
  극단저물가: '물가 압력이 매우 낮은(디스인플레) 상태.',
  저물가: '물가가 눌린 분위기.',
  중립: '물가 압력이 평범한 상태.',
  고물가: '물가가 달아오른 분위기.',
  극단고물가: '인플레가 과열된 상태. 금리·밸류에이션 부담.',
}
const I_STAT_ORDER = ['극단저물가', '저물가', '중립', '고물가', '극단고물가', '전체']
const INF_STATS_NOTE = (
  <>물가가 <b>눌릴(저물가)</b> 때 순풍인지, <b>달아오를(고물가)</b> 때 역풍인지. 20거래일 ≈ 1달. (표본 적어 참고용)</>
)

// 실탄 지수 F(t): 증시 자금유입/실탄 풍부도. 성분은 시장별로 달라 라벨을 시장별로 매핑.
//   US(주간): 연준자산 / 재무부계정 / 역레포   |   KR(월간): M2증가율 / 외국인 / 개인
function fSeries(market) {
  // 한국은 '개인 순매수'를 뺐다 — 외국인과 상관 -0.64인 거울상이라 평균에서 서로 지웠음.
  const comp = market === 'US'
    ? [['c1', '연준자산'], ['c2', '재무부계정'], ['c3', '역레포']]
    : [['c1', 'M2증가율'], ['c2', '외국인']]
  const colors = ['#2a78d6', '#008300', '#d55181']
  return [
    { key: 'f_score', name: '실탄(종합)', color: '#d97706', width: 2.2 },
    ...comp.map(([k, n], i) => ({ key: k, name: n, color: colors[i], width: 1.3 })),
  ]
}
const F_BANDS = [
  { name: '고갈', color: '#c0392b' }, { name: '부족', color: '#e59866' },
  { name: '중립', color: '#95a5a6' }, { name: '여유', color: '#52b788' },
  { name: '풍부', color: '#1e8449' },
]
function fuelBandOf(v) {
  if (v < 20) return F_BANDS[0]
  if (v < 40) return F_BANDS[1]
  if (v < 60) return F_BANDS[2]
  if (v < 80) return F_BANDS[3]
  return F_BANDS[4]
}
const F_BAND_DESC = {
  고갈: '증시로 들어올 돈이 마른 상태.', 부족: '자금 유입이 약한 분위기.',
  중립: '자금 흐름이 평범한 상태.', 여유: '증시로 돈이 들어오는 분위기.',
  풍부: '자금이 넘쳐 유입되는 상태.',
}
const F_STAT_ORDER = ['고갈', '부족', '중립', '여유', '풍부', '전체']
const FUEL_STATS_NOTE = (
  <>각 표본 = 실탄 진입 시점(🇺🇸 20거래일 간격 · 🇰🇷 매월초 — 서로 <b>안 겹치는 독립 구간</b>). <b>'이후 N일'</b>은 그 시점부터 <b>N거래일</b>(20일 ≈ 1달) 뒤 시장 수익률이에요.
    실탄이 <b>풍부</b>할 때 순풍인지, <b>고갈</b>일 때 바닥인지 — 느린 배경 지표라 참고용.</>
)
// 실탄 차트 구간 프리셋 — 미국=주간·한국=월간이라 슬라이스 '행 수'가 다름
const F_RANGES_US = [{ label: '1년', days: 52 }, { label: '3년', days: 156 }, { label: '5년', days: 260 }, { label: '전체', days: Infinity }]
const F_RANGES_KR = [{ label: '2년', days: 24 }, { label: '5년', days: 60 }, { label: '10년', days: 120 }, { label: '전체', days: Infinity }]
// 미국 실탄 차트: 순유동성 + 성분(연준자산·재무부계정·역레포) 전부 절대 $조 → 실제 금액이라 선 높이 차이가 보임
// 절대금액은 raw1~raw4에 있다 (c1~c3는 양 시장 공통으로 0~100 백분위).
const F_US_CHART = [
  { key: 'raw1', name: '순유동성', color: '#d97706', width: 2.4 },
  { key: 'raw3', name: '연준자산', color: '#2a78d6', width: 1.2 },
  { key: 'raw4', name: '재무부계정', color: '#008300', width: 1.2 },
  { key: 'raw2b', name: '역레포', color: '#d55181', width: 1.2 },
]

// 심리에 큰 충격을 준 굵직한 사건들. 차트 타임라인에 세로 표시선+이모지로만 얹음(선 series 아님).
// markets: 표시할 시장. 날짜는 대략적 발생일 — 실제 거래일로 스냅해서 그림.
const EVENTS = [
  { dt: '2020-03-23', emoji: '🦠', label: '코로나 팬데믹', markets: ['US', 'KR'] },
  { dt: '2022-02-24', emoji: '⚔️', label: '우크라이나 전쟁', markets: ['US', 'KR'] },
  { dt: '2023-03-10', emoji: '🏦', label: 'SVB 파산', markets: ['US', 'KR'] },
  { dt: '2023-10-07', emoji: '⚔️', label: '이스라엘 전쟁', markets: ['US', 'KR'] },
  { dt: '2024-08-05', emoji: '📉', label: '블랙먼데이', markets: ['US', 'KR'] },
  { dt: '2024-11-05', emoji: '🗳️', label: '미국 대선', markets: ['US', 'KR'] },
  { dt: '2024-12-03', emoji: '🚨', label: '비상계엄', markets: ['KR'] },
  { dt: '2025-04-03', emoji: '📊', label: '트럼프 관세', markets: ['US', 'KR'] },
]

// 이벤트 날짜를 series의 실제 거래일 category 값에 스냅(카테고리 축은 정확히 일치해야 표시됨).
// 화면 범위를 벗어나면 null → 표시 안 함.
function snapDt(series, target) {
  if (!series.length) return null
  const t = new Date(target).getTime()
  if (t < new Date(series[0].dt).getTime() || t > new Date(series[series.length - 1].dt).getTime()) return null
  let best = series[0].dt, bestDiff = Infinity
  for (const r of series) {
    const d = Math.abs(new Date(r.dt).getTime() - t)
    if (d < bestDiff) { bestDiff = d; best = r.dt }
  }
  return best
}
function eventsFor(market, series) {
  return EVENTS
    .filter((e) => e.markets.includes(market))
    .map((e) => ({ ...e, x: snapDt(series, e.dt) }))
    .filter((e) => e.x)
    // frac = 차트 가로 위치(0~1). 말풍선이 좌우 끝에서 잘리지 않게 기준점을 옮기는 데 씀.
    .map((e) => ({ ...e, frac: series.findIndex((r) => r.dt === e.x) / Math.max(1, series.length - 1) }))
}

// 이벤트 이모지 마커 — 커서를 대면 사건 이름·날짜가 뜬다.
// ReferenceLine label에 '함수'가 아니라 '엘리먼트'로 넘긴다: recharts가 cloneElement로
// viewBox만 주입해줘 evt·setTip이 그대로 살아있고, 컴포넌트 타입이 고정돼 호버 중 리마운트가 없다.
// (함수로 넘기면 렌더마다 새 타입이 돼 커서 올린 순간 마커가 다시 마운트된다.)
// 이모지 글자만으론 커서를 맞히기 어려워 투명 사각형으로 판정 범위를 넓힌다.
function EventMarker({ evt, setTip, viewBox }) {
  if (!viewBox) return null
  const top = Math.min(viewBox.y, viewBox.y + (viewBox.height || 0))  // 세로선의 위쪽 끝
  return (
    <g style={{ cursor: 'help' }}
      onMouseEnter={() => setTip({ ...evt, px: viewBox.x, py: top })}
      onMouseLeave={() => setTip(null)}>
      <rect x={viewBox.x - 10} y={top - 17} width={20} height={19} fill="transparent" />
      <text x={viewBox.x} y={top - 4} textAnchor="middle" fontSize={12}>{evt.emoji}</text>
    </g>
  )
}

function EventTip({ tip }) {
  if (!tip) return null
  const shift = tip.frac > 0.78 ? '-92%' : tip.frac < 0.22 ? '-8%' : '-50%'
  return (
    <div className="event-tip" style={{ left: tip.px, top: tip.py + 4, transform: `translateX(${shift})` }}>
      <b>{tip.emoji} {tip.label}</b><span>{tip.dt}</span>
    </div>
  )
}

// 밴드표: 이후수익률 기간(거래일) 토글 옵션. backtest_stats 의 fwd{h}/hit{h} 컬럼과 대응.
const HORIZONS = [5, 10, 20, 30, 60]
// 심리 추이 차트: 표시 구간 프리셋(거래일 수). 시리즈 끝에서 그만큼만 잘라 보여줌.
const RANGES = [
  { label: '1달', days: 21 }, { label: '3달', days: 63 }, { label: '6달', days: 126 },
  { label: '1년', days: 252 }, { label: '2년', days: 504 }, { label: '3년', days: 756 },
  { label: '전체', days: Infinity },
]

// 상단 탭: 시장 배경요인 섹션 전환. key = 렌더할 섹션.
const TABS = [
  { key: 'sent', label: '시장심리', emoji: '😨' },
  { key: 'liq', label: '유동성', emoji: '💧' },
  { key: 'inf', label: '물가', emoji: '🔥' },
  { key: 'fuel', label: '실탄', emoji: '💰' },
  { key: 'mix', label: '종합', emoji: '🧭' },
  { key: 'cmp', label: '비교', emoji: '📊' },
  { key: 'vp', label: '매물대', emoji: '⛰️' },
  { key: 'ai', label: 'AI 사이클', emoji: '🤖' },
  { key: 'scr', label: '종목', emoji: '🔎' },
  { key: 'pf', label: '포트폴리오', emoji: '🧺' },
]

// ── 개별 종목 (스크리너 · 포트폴리오 공용) ──
// ⚠️ 무료 데이터의 한계상 '검증된 전략'을 만들 수 없다 — 생존편향(현재 상장 종목만),
// 시점데이터 부재(재무제표가 최신 수정본), 재무이력 4~5년. 화면은 '지금 이렇다' /
// '과거에 이랬다'까지만 말하고 미래 수익률은 주장하지 않는다.
const FIN_COLS = [
  { key: 'per', name: 'PER', fmt: (v) => v?.toFixed(1), lowGood: true, hint: '시총÷순이익. 낮을수록 싸다' },
  { key: 'pbr', name: 'PBR', fmt: (v) => v?.toFixed(2), lowGood: true, hint: '시총÷자본. 낮을수록 싸다' },
  { key: 'roe', name: 'ROE', fmt: (v) => (v * 100).toFixed(0) + '%', lowGood: false, hint: '자본 대비 이익. 높을수록 좋다' },
  { key: 'op_margin', name: '영업이익률', fmt: (v) => (v * 100).toFixed(0) + '%', lowGood: false, hint: '매출 대비 영업이익' },
  { key: 'debt_to_equity', name: '부채비율', fmt: (v) => v.toFixed(0), lowGood: true, hint: '자본 대비 부채. 낮을수록 안전' },
  { key: 'rev_growth', name: '매출성장', fmt: (v) => (v > 0 ? '+' : '') + (v * 100).toFixed(0) + '%', lowGood: false, hint: '전년 대비 매출 증가율' },
  { key: 'div_yield', name: '배당', fmt: (v) => v.toFixed(1) + '%', lowGood: false, hint: '배당수익률' },
]
const won = (v) => {
  if (v == null) return '—'
  if (v >= 1e12) return (v / 1e12).toFixed(1) + '조'
  if (v >= 1e8) return Math.round(v / 1e8).toLocaleString() + '억'
  return Math.round(v).toLocaleString()
}
// 데이터 한계를 화면 어디서나 같은 문장으로 — 탭마다 말이 달라지면 신뢰가 깨진다
const STOCK_CAVEAT = (
  <>⚠️ <b>이 숫자로 전략을 검증할 수는 없습니다.</b> 무료 데이터라 ① 과거 상장폐지된 종목이
    목록에서 빠져 있고(생존편향) ② 재무제표가 당시 값이 아닌 최신 수정본이며
    ③ 이력이 4~5년뿐입니다. <b>"지금 이 종목이 이렇다"까지가 정직한 한계</b>예요.</>
)

// ── 종합 탭: 4요인을 비율대로 합쳐 '투자 매력도' 하나로 ──
// 방향(invert)은 개념 + 밴드 백테스트 근거로 정했다. 심리는 선형 상관이 약해도(한국 +0.08)
// 극단에서만 작동하는 역발상 지표라 반전이 맞다(극단공포−극단탐욕 이후20일 US +5.3%p / KR +3.5%p).
const MIX_FACTORS = [
  { key: 's', name: '심리', color: '#2a78d6', table: 'sentiment_daily', col: 's_score',
    invert: true, hint: '공포일수록 유리 (역발상)' },
  { key: 'l', name: '유동성', color: '#008300', table: 'liquidity_daily', col: 'l_score',
    invert: false, hint: '완화일수록 유리' },
  { key: 'i', name: '물가', color: '#4a3aa7', table: 'inflation_daily', col: 'i_score',
    invert: true, hint: '저물가일수록 유리' },
  { key: 'f', name: '실탄', color: '#d55181', table: 'fuel_index', col: 'f_score',
    invert: false, hint: '풍부할수록 유리' },
]
// 기본은 '배경만'(심리 0). 심리는 4성분이 거의 다 주가 파생(모멘텀 = 지수÷125일평균)이라,
// 넣으면 "주가로 주가를 설명"하는 꼴이 되고 선행성도 오히려 떨어진다.
//   배경 3요인의 주가 선행 상관(+60일): US 0.41 / KR 0.47   ← 심리 포함시 0.36 / 0.29
// 기간을 반으로 갈라도 4개 구간 전부에서 같은 방향으로 살아남은 건 '배경만'뿐이었다.
const MIX_PRESETS = [
  { name: '배경만', w: { s: 0, l: 35, i: 35, f: 35 } },
  { name: '심리 포함', w: { s: 20, l: 25, i: 30, f: 25 } },
  { name: '물가 중심', w: { s: 0, l: 25, i: 50, f: 25 } },
  { name: '유동성·실탄', w: { s: 0, l: 40, i: 20, f: 40 } },
]
const MIX_BANDS = [
  { name: '매우 불리', color: '#c0392b' }, { name: '불리', color: '#e59866' },
  { name: '중립', color: '#95a5a6' }, { name: '유리', color: '#52b788' },
  { name: '매우 유리', color: '#1e8449' },
]
function mixBandOf(v) {
  if (v < 20) return MIX_BANDS[0]
  if (v < 40) return MIX_BANDS[1]
  if (v < 60) return MIX_BANDS[2]
  if (v < 80) return MIX_BANDS[3]
  return MIX_BANDS[4]
}
const MIX_BAND_DESC = {
  '매우 불리': '네 요인이 모두 역풍 쪽. 역사적으로 드문 구간이에요.',
  불리: '배경 조건이 우호적이지 않은 상태.',
  중립: '특별히 유리하지도 불리하지도 않은 평범한 국면.',
  유리: '배경 조건이 우호적인 상태.',
  '매우 유리': '네 요인이 모두 순풍 쪽. 역사적으로 드문 구간이에요.',
}
const MIX_HORIZONS = [20, 60, 120]

export default function App() {
  const [tab, setTab] = useState('sent')
  if (!hasKey) return <Setup />
  return (
    <div className="wrap">
      <nav className="topnav">
        {TABS.map((t) => (
          <button key={t.key} className={tab === t.key ? 'on' : ''} onClick={() => setTab(t.key)}>
            {t.emoji} {t.label}
          </button>
        ))}
      </nav>
      {tab === 'sent' && <SentimentSection />}
      {tab === 'liq' && <LiquiditySection />}
      {tab === 'inf' && <InflationSection />}
      {tab === 'fuel' && <FuelSection />}
      {tab === 'mix' && <CompositeSection />}
      {tab === 'cmp' && <ComparisonSection />}
      {tab === 'vp' && <ProfileSection />}
      {tab === 'ai' && <AISection />}
      {tab === 'scr' && <ScreenerSection />}
      {tab === 'pf' && <PortfolioSection />}
    </div>
  )
}

function SentimentSection() {
  return (
    <>
      <header>
        <h1>시장 심리</h1>
        <p className="lead">
          시장이 지금 <b>겁먹었는지(공포)</b> 아니면 <b>들떴는지(탐욕)</b> 를 0~100 점수로.
          <b> 미국과 한국</b>을 나란히 봅니다. (실적이 아니라 시장 분위기)
        </p>
      </header>
      <div className="cols">
        <MarketColumn market="US" flag="🇺🇸" name="미국" />
        <div className="divider" />
        <MarketColumn market="KR" flag="🇰🇷" name="한국" />
      </div>
      <MethodCard />
      <Glossary />
    </>
  )
}

function LiquiditySection() {
  return (
    <>
      <header>
        <h1>유동성</h1>
        <p className="lead">
          돈이 얼마나 <b>풀렸는지(완화)</b> 아니면 <b>조였는지(긴축)</b> 를 0~100 점수로.
          <b> 금리·환율·신용</b>을 합쳐 봅니다. (자산가격의 바탕이 되는 돈의 흐름)
        </p>
      </header>
      <div className="cols">
        <LiquidityColumn market="US" flag="🇺🇸" name="미국" />
        <div className="divider" />
        <LiquidityColumn market="KR" flag="🇰🇷" name="한국" />
      </div>
      <LiquidityMethod />
    </>
  )
}

function InflationSection() {
  return (
    <>
      <header>
        <h1>물가</h1>
        <p className="lead">
          물가가 지금 <b>눌렸는지(저물가)</b> 아니면 <b>달아올랐는지(고물가)</b> 를 0~100 점수로.
          <b> 유가·원자재·기대인플레</b>를 합쳐 봅니다. (시장이 매일 반영하는 물가 압력)
        </p>
      </header>
      <div className="cols">
        <InflationColumn market="US" flag="🇺🇸" name="미국" />
        <div className="divider" />
        <InflationColumn market="KR" flag="🇰🇷" name="한국" />
      </div>
      <InflationMethod />
    </>
  )
}

function MarketColumn({ market, flag, name }) {
  const [series, setSeries] = useState([])
  const [latest, setLatest] = useState(null)
  const [stats, setStats] = useState([])
  const [state, setState] = useState('loading') // loading | ok | empty | error

  useEffect(() => {
    let alive = true
    ;(async () => {
      try {
        // Supabase는 요청당 최대 1000행 → 약 6년(2020~) 커버하려면 페이지네이션으로 나눠 받는다.
        const PAGE = 1000, WANT = 1650
        let all = []
        for (let from = 0; from < WANT; from += PAGE) {
          const to = Math.min(from + PAGE - 1, WANT - 1)
          const { data, error } = await supabase
            .from('sentiment_daily')
            .select('dt,s_score,band,c_vix,c_mom,c_shv,c_breadth')
            .eq('market', market)
            .order('dt', { ascending: false })
            .range(from, to)
          if (error) throw error
          all = all.concat(data || [])
          if (!data || data.length < to - from + 1) break  // 데이터 소진
        }
        if (!alive) return
        if (all.length === 0) { setState('empty'); return }
        const rows = all.slice().reverse()
        setSeries(rows); setLatest(rows[rows.length - 1]); setState('ok')
        const { data: bt } = await supabase.from('backtest_stats').select('*').eq('market', market)
        if (alive && bt) setStats(bt)
      } catch {
        if (alive) setState('error')
      }
    })()
    return () => { alive = false }
  }, [market])

  return (
    <div className="col">
      <div className="col-head">{flag} <b>{name}</b></div>
      {state === 'loading' && <div className="col-msg">불러오는 중…</div>}
      {state === 'error' && <div className="col-msg">데이터를 불러오지 못했어요</div>}
      {state === 'empty' && (
        <div className="col-msg soon">
          🚧<br /><b>데이터 준비 중</b><br />
          <span>{name} 시장은 곧 추가돼요</span>
        </div>
      )}
      {state === 'ok' && latest && <MarketBody latest={latest} series={series} stats={stats} market={market} />}
    </div>
  )
}

// 공용 게이지 (심리·유동성 공통). band = {name, color}.
function Gauge({ value, band, lowLabel, highLabel, desc }) {
  return (
    <section className="gauge" style={{ '--c': band.color }}>
      <div className="score">{Math.round(value)}</div>
      <div className="band">{band.name}</div>
      <div className="scale"><span>0 · {lowLabel}</span><span>{highLabel} · 100</span></div>
      <div className="bar"><div className="fill" style={{ width: `${value}%` }} /></div>
      <p className="gauge-note">{desc}</p>
    </section>
  )
}

// 커스텀 툴팁: 각 성분의 점수(0~100)와 함께 '실제 수치'(config.raw 정의 시)를 보여줌.
//   예) 금리  4.45%  95 — 굵은 값=실제 국고채10년, 옅은 값=점수. (사용자 혼동 "금리:95" 해소)
function ChartTooltip({ active, payload, label, config, market, mainKey, valueFmt = null }) {
  if (!active || !payload || !payload.length) return null
  const point = payload[0].payload
  const order = config.map((c) => c.key)
  const rows = [...payload].sort((a, b) => order.indexOf(a.dataKey) - order.indexOf(b.dataKey))
  const anyRaw = rows.some((e) => {
    const c = config.find((x) => x.key === e.dataKey)
    return c && c.raw && c.raw(point, market) != null
  })
  return (
    <div className="chart-tip">
      <div className="tip-date">{label}</div>
      {rows.map((e) => {
        const cfg = config.find((c) => c.key === e.dataKey)
        const rawStr = cfg && cfg.raw ? cfg.raw(point, market) : null
        return (
          <div key={e.dataKey} className={'tip-row' + (e.dataKey === mainKey ? ' main' : '')}>
            <span className="tip-name"><i style={{ background: e.color }} />{e.name}</span>
            <span className="tip-val">
              {valueFmt ? <b>{valueFmt(e.value)}</b> : (<>{rawStr && <b>{rawStr}</b>}<em>{Math.round(e.value)}</em></>)}
            </span>
          </div>
        )
      })}
      {anyRaw && <div className="tip-foot">굵은 값 = 실제 수치 · 옅은 값 = 점수(0~100)</div>}
    </div>
  )
}

// 공용 추이 차트: 종합선 + 성분선 + 구간선택 + 이벤트선 + 커스텀 범례.
//   config[0] = 종합(범례 맨 앞, z축 맨 위). mainKey = 종합 dataKey.
function TrendChart({ series, config, market, title, refLines, note, mainKey, ranges = RANGES, defaultRange = 756, yDomain = [0, 100], valueFmt = null }) {
  const [range, setRange] = useState(defaultRange)   // 기본 3년(또는 지정값)
  const [hidden, setHidden] = useState(() => new Set())
  const [evtTip, setEvtTip] = useState(null)         // 이벤트 이모지에 커서 올렸을 때
  const toggle = (k) => setHidden((h) => {
    const n = new Set(h)
    if (n.has(k)) n.delete(k); else n.add(k)
    return n
  })
  const shown = range === Infinity ? series : series.slice(-range)
  const events = eventsFor(market, shown)
  const drawOrder = [...config.slice(1), config[0]]  // 성분 먼저 → 종합이 맨 위
  return (
    <section className="card">
      <h2>{title}</h2>
      <div className="seg">
        {ranges.map((r) => (
          <button key={r.label} className={range === r.days ? 'on' : ''}
            onClick={() => setRange(r.days)}>{r.label}</button>
        ))}
      </div>
      <div className="chart-wrap">
      <EventTip tip={evtTip} />
      <ResponsiveContainer width="100%" height={248}>
        <LineChart data={shown} margin={{ top: 18, right: 8, left: -22, bottom: 0 }}>
          <CartesianGrid strokeDasharray="3 3" opacity={0.15} />
          <XAxis dataKey="dt" tick={{ fontSize: 10 }} minTickGap={48} />
          <YAxis domain={yDomain} tick={{ fontSize: 10 }} width={valueFmt ? 34 : undefined} />
          <Tooltip content={(props) => <ChartTooltip {...props} config={config} market={market} mainKey={mainKey} valueFmt={valueFmt} />}
            wrapperStyle={{ outline: 'none' }} />
          {refLines.map((r) => (
            <ReferenceLine key={r.y} y={r.y} stroke={r.color} strokeDasharray="4 4" />
          ))}
          {events.map((e) => (
            <ReferenceLine key={e.dt + e.label} x={e.x} stroke="#b0b4ba" strokeDasharray="2 3"
              label={<EventMarker evt={e} setTip={setEvtTip} />} />
          ))}
          {drawOrder.map((s) => (
            <Line key={s.key} type="monotone" dataKey={s.key} name={s.name}
              stroke={s.color} dot={false} strokeWidth={s.width}
              strokeOpacity={s.key === mainKey ? 1 : 0.85}
              hide={hidden.has(s.key)} isAnimationActive={false} />
          ))}
        </LineChart>
      </ResponsiveContainer>
      </div>
      <div className="chart-legend">
        {config.map((s) => (
          <button key={s.key} className={hidden.has(s.key) ? 'off' : ''} onClick={() => toggle(s.key)}>
            <span className="swatch" style={{ background: s.color, height: s.key === mainKey ? 4 : 2 }} />
            {s.name}
          </button>
        ))}
      </div>
      <p className="note">{note}</p>
    </section>
  )
}

function MarketBody({ latest, series, stats, market }) {
  const b = bandOf(latest.s_score)
  return (
    <>
      <p className="col-date">{latest.dt} 기준</p>
      <Gauge value={latest.s_score} band={b} lowLabel="공포" highLabel="탐욕" desc={BAND_DESC[b.name]} />
      <TrendChart
        series={series} config={SERIES} market={market} mainKey="s_score"
        title="S(t) 심리점수 추이"
        refLines={[{ y: 80, color: '#c0392b' }, { y: 20, color: '#2471a3' }]}
        note={<>굵은 <b style={{ color: '#d97706' }}>주황</b>이 종합 심리점수, 얇은 4선은 그걸 이루는 성분(각 0~100, 높을수록 탐욕 쪽). <b>범례를 누르면</b> 선을 켜고 끌 수 있어요.</>}
      />
      <StatsCard stats={stats} />
    </>
  )
}

function StatsCard({ stats, order = STAT_ORDER, note = SENT_STATS_NOTE, countLabel = '일수' }) {
  const [h, setH] = useState(20)
  if (!stats || stats.length === 0) return null
  const byBand = Object.fromEntries(stats.map((s) => [s.band, s]))
  return (
    <section className="card">
      <h2>밴드별 '이후 {h}일' 수익률</h2>
      <div className="seg">
        {HORIZONS.map((x) => (
          <button key={x} className={h === x ? 'on' : ''} onClick={() => setH(x)}>{x}일</button>
        ))}
      </div>
      <table className="stats">
        <thead><tr><th>밴드</th><th>{countLabel}</th><th>이후{h}일</th><th>승률</th></tr></thead>
        <tbody>
          {order.map((bd) => {
            const s = byBand[bd]
            if (!s) return null
            const v = s[`fwd${h}`]
            const hit = s[`hit${h}`]
            if (v == null) {
              return (
                <tr key={bd} className={bd === '전체' ? 'base' : ''}>
                  <td>{bd}</td><td>{s.n}</td><td>—</td><td>—</td>
                </tr>
              )
            }
            const color = v > 2 ? '#1e8449' : v < 0 ? '#c0392b' : 'inherit'
            return (
              <tr key={bd} className={bd === '전체' ? 'base' : ''}>
                <td>{bd}</td>
                <td>{s.n}</td>
                <td style={{ color, fontWeight: v > 2 || v < 0 ? 700 : 400 }}>
                  {v > 0 ? '+' : ''}{v}%
                </td>
                <td>{hit == null ? '—' : `${hit}%`}</td>
              </tr>
            )
          })}
        </tbody>
      </table>
      <p className="note">{note}</p>
    </section>
  )
}

// ── 유동성 섹션 ──
function RawFigures({ latest, market }) {
  const pct = (v) => (v == null ? '—' : `${v.toFixed(2)}%`)
  const num = (v, d = 1) => (v == null ? '—' : v.toLocaleString(undefined, { maximumFractionDigits: d }))
  const spread = (v) => (v == null ? '—' : `${v.toFixed(2)}%p`)
  // KR: raw_us10y=국고채10년, raw_dxy=신용스프레드(회사채-국고채) — liquidity.py에서 시장별 의미 다름
  const items = market === 'US'
    ? [['미 10년물 금리', pct(latest.raw_us10y)], ['달러지수(DXY)', num(latest.raw_dxy)]]
    : [['원/달러', num(latest.raw_usdkrw, 0)], ['국고채 10년', pct(latest.raw_us10y)], ['신용스프레드', spread(latest.raw_dxy)]]
  return (
    <div className="raw-figs">
      {items.map(([label, val]) => (
        <div key={label} className="raw-fig">
          <span className="rf-label">{label}</span>
          <span className="rf-val">{val}</span>
        </div>
      ))}
    </div>
  )
}

function LiquidityBody({ latest, series, stats, market }) {
  const b = liqBandOf(latest.l_score)
  return (
    <>
      <p className="col-date">{latest.dt} 기준</p>
      <Gauge value={latest.l_score} band={b} lowLabel="긴축" highLabel="완화" desc={L_BAND_DESC[b.name]} />
      <RawFigures latest={latest} market={market} />
      <TrendChart
        series={series} config={L_SERIES} market={market} mainKey="l_score"
        title="L(t) 유동성 추이"
        refLines={[{ y: 80, color: '#1e8449' }, { y: 20, color: '#c0392b' }]}
        note={<>굵은 <b style={{ color: '#d97706' }}>주황</b>이 종합 유동성, 얇은 4선은 성분(각 0~100, 높을수록 완화). <b>범례를 누르면</b> 선을 켜고 끌 수 있어요.</>}
      />
      <StatsCard stats={stats} order={L_STAT_ORDER} note={LIQ_STATS_NOTE} />
    </>
  )
}

function LiquidityColumn({ market, flag, name }) {
  const [series, setSeries] = useState([])
  const [latest, setLatest] = useState(null)
  const [stats, setStats] = useState([])
  const [state, setState] = useState('loading')
  useEffect(() => {
    let alive = true
    ;(async () => {
      try {
        const PAGE = 1000, WANT = 1650
        let all = []
        for (let from = 0; from < WANT; from += PAGE) {
          const to = Math.min(from + PAGE - 1, WANT - 1)
          const { data, error } = await supabase
            .from('liquidity_daily')
            .select('dt,l_score,band,c_rate,c_curve,c_fx,c_credit,raw_us10y,raw_dxy,raw_usdkrw,raw_curve')
            .eq('market', market)
            .order('dt', { ascending: false })
            .range(from, to)
          if (error) throw error
          all = all.concat(data || [])
          if (!data || data.length < to - from + 1) break
        }
        if (!alive) return
        if (all.length === 0) { setState('empty'); return }
        const rows = all.slice().reverse()
        setSeries(rows); setLatest(rows[rows.length - 1]); setState('ok')
        // 밴드별 이후수익률 통계 — 테이블이 아직 없으면(error) 조용히 표만 생략.
        const { data: bt } = await supabase.from('liquidity_backtest_stats').select('*').eq('market', market)
        if (alive && bt) setStats(bt)
      } catch {
        if (alive) setState('error')
      }
    })()
    return () => { alive = false }
  }, [market])

  return (
    <div className="col">
      <div className="col-head">{flag} <b>{name}</b></div>
      {state === 'loading' && <div className="col-msg">불러오는 중…</div>}
      {state === 'error' && <div className="col-msg">데이터를 불러오지 못했어요</div>}
      {state === 'empty' && (
        <div className="col-msg soon">🚧<br /><b>데이터 준비 중</b></div>
      )}
      {state === 'ok' && latest && <LiquidityBody latest={latest} series={series} stats={stats} market={market} />}
    </div>
  )
}

// ── 물가 섹션 (유동성과 동일 구조) ──
// 점수 옆에 원물 시세를 같이 보여준다. 한국은 원/달러(수입물가)가 성분이라 맨 앞에.
function InflationFigures({ latest, market }) {
  const wti = latest.raw_wti == null ? '—' : `$${latest.raw_wti.toFixed(1)}`
  const copper = latest.raw_copper == null ? '—' : `$${latest.raw_copper.toFixed(2)}`
  const krw = latest.raw_usdkrw == null ? '—' : `${Math.round(latest.raw_usdkrw).toLocaleString()}원`
  const items = market === 'US'
    ? [['유가(WTI)', wti], ['구리', copper]]
    : [['원/달러', krw], ['유가(WTI)', wti], ['구리', copper]]
  return (
    <div className="raw-figs">
      {items.map(([label, val]) => (
        <div key={label} className="raw-fig">
          <span className="rf-label">{label}</span><span className="rf-val">{val}</span>
        </div>
      ))}
    </div>
  )
}

function InflationBody({ latest, series, stats, market }) {
  const b = infBandOf(latest.i_score)
  return (
    <>
      <p className="col-date">{latest.dt} 기준</p>
      <Gauge value={latest.i_score} band={b} lowLabel="저물가" highLabel="고물가" desc={I_BAND_DESC[b.name]} />
      <InflationFigures latest={latest} market={market} />
      <TrendChart
        series={series} config={I_SERIES} market={market} mainKey="i_score"
        title="I(t) 물가 추이"
        refLines={[{ y: 80, color: '#c0392b' }, { y: 20, color: '#2471a3' }]}
        note={<>굵은 <b style={{ color: '#d97706' }}>주황</b>이 종합 물가, 얇은 4선은 성분(각 0~100, 높을수록 물가↑). <b>범례를 누르면</b> 선을 켜고 끌 수 있어요.</>}
      />
      <StatsCard stats={stats} order={I_STAT_ORDER} note={INF_STATS_NOTE} />
    </>
  )
}

function InflationColumn({ market, flag, name }) {
  const [series, setSeries] = useState([])
  const [latest, setLatest] = useState(null)
  const [stats, setStats] = useState([])
  const [state, setState] = useState('loading')
  useEffect(() => {
    let alive = true
    ;(async () => {
      try {
        const PAGE = 1000, WANT = 1650
        let all = []
        for (let from = 0; from < WANT; from += PAGE) {
          const to = Math.min(from + PAGE - 1, WANT - 1)
          const { data, error } = await supabase
            .from('inflation_daily')
            .select('dt,i_score,band,c_be,c_energy,c_food,c_metal,raw_wti,raw_copper,raw_usdkrw')
            .eq('market', market)
            .order('dt', { ascending: false })
            .range(from, to)
          if (error) throw error
          all = all.concat(data || [])
          if (!data || data.length < to - from + 1) break
        }
        if (!alive) return
        if (all.length === 0) { setState('empty'); return }
        const rows = all.slice().reverse()
        setSeries(rows); setLatest(rows[rows.length - 1]); setState('ok')
        // 밴드별 이후수익률 통계 — 테이블이 아직 없으면(error) 조용히 표만 생략.
        const { data: bt } = await supabase.from('inflation_backtest_stats').select('*').eq('market', market)
        if (alive && bt) setStats(bt)
      } catch (e) {
        if (!alive) return
        // 활성화 전(테이블 미생성)이면 에러 대신 '준비 중'으로 표시.
        const msg = `${e?.message || ''} ${e?.code || ''}`
        setState(/exist|find the table|PGRST205|42P01/i.test(msg) ? 'empty' : 'error')
      }
    })()
    return () => { alive = false }
  }, [market])

  return (
    <div className="col">
      <div className="col-head">{flag} <b>{name}</b></div>
      {state === 'loading' && <div className="col-msg">불러오는 중…</div>}
      {state === 'error' && <div className="col-msg">데이터를 불러오지 못했어요</div>}
      {state === 'empty' && (
        <div className="col-msg soon">🚧<br /><b>데이터 준비 중</b></div>
      )}
      {state === 'ok' && latest && <InflationBody latest={latest} series={series} stats={stats} market={market} />}
    </div>
  )
}

function MethodCard() {
  const ing = [
    ['😨 변동성 (공포)', '얼마나 겁먹었나 — 미국은 VIX, 한국은 코스피 실현변동성'],
    ['📈 모멘텀', '지수가 최근 평균(125일)보다 위인가'],
    ['🎢 위험 선호', '주식 vs 안전채권 — 주식이 이기면 위험선호↑(탐욕), 채권이 이기면(공포)'],
    ['👥 시장 폭 (골고루↔쏠림)', '대형주 쏠림인가(공포) vs 골고루 오르나(탐욕) — 미국 동일가중 vs 대형주, 한국 코스닥 vs 코스피(대형주)'],
  ]
  return (
    <section className="card method">
      <h2>🔧 이 점수, 어떻게 만드나요?</h2>
      <p className="cap">실적·뉴스가 아니라 '시장 분위기'를 4가지 각도로 재서 하나로 합친 값이에요.</p>
      <ul>
        {ing.map(([t, d]) => (
          <li key={t}><b>{t}</b> — {d}</li>
        ))}
      </ul>
      <p className="note">
        각 재료를 <b>지난 1년 중 몇 %ile</b>인지로 0~100 환산 → 공포 재료는 뒤집어 방향을 통일
        → <b>4개 평균</b> → 최근 10일로 부드럽게(평활) = 최종 심리점수.
      </p>
    </section>
  )
}

function LiquidityMethod() {
  const ing = [
    ['💵 금리', '정책·시장금리가 낮을수록 완화 (미국 10년물, 한국 국고채10년)'],
    ['📐 일드커브', '장단기 금리차 — 가파를수록 완화적 (미국 10년-3개월, 한국 국고채 10년-3년)'],
    ['💱 환율', '통화 강세 = 자금 유입 (미국 달러지수, 한국 원/달러)'],
    ['🏦 신용', '신용스프레드 좁을수록 완화 (미국 HYG/IEI, 한국 회사채-국고채)'],
  ]
  return (
    <section className="card method">
      <h2>💧 유동성(L), 어떻게 만드나요?</h2>
      <p className="cap">"돈이 얼마나 풀렸나"를 4가지 각도로 재서 하나로 합친 값. 높을수록 완화(풍부).</p>
      <ul>
        {ing.map(([t, d]) => (
          <li key={t}><b>{t}</b> — {d}</li>
        ))}
      </ul>
      <p className="note">
        각 재료를 <b>지난 1년 중 몇 %ile</b>인지로 0~100 환산 → 긴축 재료는 뒤집어 방향 통일 → <b>4개 평균</b> →
        10일 평활. 절대 수준이 아니라 <b>지난 1년 대비 완화/긴축</b>이라, 저금리가 오래된 시기는 중립으로 읽혀요.
      </p>
    </section>
  )
}

function InflationMethod() {
  const ing = [
    ['📈 기대인플레', '시장이 반영한 물가 — 물가연동채(TIP)÷국채(IEF). 글로벌 공통'],
    ['🛢️ 에너지', '유가가 오를수록 물가↑ (WTI 원유)'],
    ['🌾 식품', '곡물이 오를수록 밥상물가↑ (옥수수·밀·대두 등가중)'],
    ['🔩 산업금속', '구리 등 실물 수요가 강할수록 물가↑ (구리 선물)'],
  ]
  return (
    <section className="card method">
      <h2>🔥 물가(I), 어떻게 만드나요?</h2>
      <p className="cap">CPI는 월간·후행이라, 시장이 매일 반영하는 "물가 압력"을 4가지 각도로 재서 합친 값. 높을수록 물가↑.</p>
      <ul>
        {ing.map(([t, d]) => (
          <li key={t}><b>{t}</b> — {d}</li>
        ))}
      </ul>
      <p className="note">
        각 재료를 <b>지난 1년 중 몇 %ile</b>인지로 0~100 환산 → <b>4개 평균</b> → 10일 평활.
        절대 수준이 아니라 <b>지난 1년 대비 물가 압력</b>이라, 실제 CPI보다 방향 전환을 먼저 잡아요.
      </p>
      <p className="note">
        재료는 ETF가 아니라 <b>원물 시세</b>(WTI·곡물·구리 선물)를 씁니다. 선물 롤오버 ETF(USO 등)는
        콘탱고에서 가격이 계속 깎여, 2015~2026 유가가 <b>+70%</b> 오르는 동안 USO는 <b>-14%</b>였어요 — 물가 대리변수가 못 됩니다.
      </p>
      <p className="note">
        🇰🇷 한국은 같은 원자재를 <b>원화로 환산</b>해서 봅니다. 실제로 치르는 값이 원화 기준이라,
        원 약세면 같은 유가라도 체감 물가가 오르니까요.
      </p>
    </section>
  )
}

// ── 실탄 섹션 (증시 자금유입; 미국 주간 FRED / 한국 월간 ECOS) ──
function FuelFigures({ latest, market }) {
  const items = market === 'US'
    ? [['순유동성', latest.raw1 == null ? '—' : `$${latest.raw1.toFixed(2)}T`],
       ['역레포', latest.raw2 == null ? '—' : `$${Math.round(latest.raw2)}B`]]
    : [['M2 증가율', latest.raw1 == null ? '—' : `${latest.raw1.toFixed(1)}%`],
       ['외국인 순매수(월)', latest.raw2 == null ? '—' : Math.round(latest.raw2).toLocaleString()]]
  return (
    <div className="raw-figs">
      {items.map(([label, val]) => (
        <div key={label} className="raw-fig">
          <span className="rf-label">{label}</span><span className="rf-val">{val}</span>
        </div>
      ))}
    </div>
  )
}

function FuelBody({ latest, series, stats, market }) {
  const b = fuelBandOf(latest.f_score)
  const monthly = latest.freq === 'M'
  return (
    <>
      <p className="col-date">{latest.dt} 기준{monthly && <span className="freq-badge">월간</span>}</p>
      <Gauge value={latest.f_score} band={b} lowLabel="고갈" highLabel="풍부" desc={F_BAND_DESC[b.name]} />
      <FuelFigures latest={latest} market={market} />
      {market === 'US' ? (
        <TrendChart
          series={series} config={F_US_CHART}
          market={market} mainKey="raw1" title="실탄 절대 추이 ($조)"
          ranges={F_RANGES_US} defaultRange={Infinity}
          yDomain={['auto', 'auto']} valueFmt={(v) => `$${v.toFixed(2)}T`} refLines={[]}
          note={<>전부 <b>실제 달러($조)</b>예요. 굵은 주황 <b>순유동성</b> = 연준자산 − 재무부계정 − 역레포. 성분 선 높이가 다른 게 진짜 금액 차이(연준 ~$6.7조 vs 재무부 ~$0.8조). 위 게이지(0~100)는 순유동성의 <b>과거 대비 위치</b>.</>}
        />
      ) : (
        <TrendChart
          series={series} config={fSeries(market)} market={market} mainKey="f_score"
          title="F(t) 실탄 추이"
          ranges={F_RANGES_KR} defaultRange={Infinity}
          refLines={[{ y: 80, color: '#1e8449' }, { y: 20, color: '#c0392b' }]}
          note={<>굵은 <b style={{ color: '#d97706' }}>주황</b>이 종합 실탄, 얇은 3선은 성분(각 0~100, 높을수록 유입). <b>한국은 월간·단위가 달라(%·원) 절대금액 합산이 안 돼</b> 백분위로 봅니다.</>}
        />
      )}
      <StatsCard stats={stats} order={F_STAT_ORDER} note={FUEL_STATS_NOTE} countLabel={monthly ? '개월' : '표본'} />
    </>
  )
}

function FuelColumn({ market, flag, name }) {
  const [series, setSeries] = useState([])
  const [latest, setLatest] = useState(null)
  const [stats, setStats] = useState([])
  const [state, setState] = useState('loading')
  useEffect(() => {
    let alive = true
    ;(async () => {
      try {
        const { data, error } = await supabase
          .from('fuel_index')
          .select('dt,f_score,band,c1,c2,c3,raw1,raw2,raw3,raw4,freq')
          .eq('market', market).order('dt', { ascending: true })
        if (error) throw error
        if (!alive) return
        if (!data || data.length === 0) { setState('empty'); return }
        // raw2는 헤드라인 카드용 $십억 → 차트는 다른 선과 단위를 맞추려 $조로 환산해 둔다
        const rows = data.map((r) => ({ ...r, raw2b: r.raw2 == null ? null : r.raw2 / 1000 }))
        setSeries(rows); setLatest(rows[rows.length - 1]); setState('ok')
        const { data: bt } = await supabase.from('fuel_backtest_stats').select('*').eq('market', market)
        if (alive && bt) setStats(bt)
      } catch (e) {
        if (!alive) return
        const msg = `${e?.message || ''} ${e?.code || ''}`
        setState(/exist|find the table|PGRST205|42P01/i.test(msg) ? 'empty' : 'error')
      }
    })()
    return () => { alive = false }
  }, [market])
  return (
    <div className="col">
      <div className="col-head">{flag} <b>{name}</b></div>
      {state === 'loading' && <div className="col-msg">불러오는 중…</div>}
      {state === 'error' && <div className="col-msg">데이터를 불러오지 못했어요</div>}
      {state === 'empty' && <div className="col-msg soon">🚧<br /><b>데이터 준비 중</b></div>}
      {state === 'ok' && latest && <FuelBody latest={latest} series={series} stats={stats} market={market} />}
    </div>
  )
}

function FuelSection() {
  return (
    <>
      <header>
        <h1>실탄</h1>
        <p className="lead">
          증시로 <b>실제 들어올 수 있는 돈</b>이 얼마나 되는지 0~100 점수로.
          유동성이 <b>돈의 값</b>이라면 이건 <b>돈의 양·유입</b>이에요. <b>(미국 주간 · 한국 월간)</b>
        </p>
      </header>
      <div className="cols">
        <FuelColumn market="US" flag="🇺🇸" name="미국" />
        <div className="divider" />
        <FuelColumn market="KR" flag="🇰🇷" name="한국" />
      </div>
      <FuelMethod />
    </>
  )
}

function FuelMethod() {
  return (
    <section className="card method">
      <h2>💰 실탄(F), 어떻게 만드나요?</h2>
      <p className="cap">"증시에 투입될 수 있는 돈"을 시장별로 재서 합친 값. 높을수록 실탄 풍부(유입).</p>
      <ul>
        <li><b>🇺🇸 미국 (주간)</b> — Fed 순유동성 = 연준 총자산 − 재무부계정(TGA) − 역레포(RRP). 연준이 푼 돈 중 시중에 도는 부분.</li>
        <li><b>🇰🇷 한국 (월간)</b> — M2 증가율 + 외국인 순매수. 돈의 양 + 실제 수급.</li>
      </ul>
      <p className="note">
        각 재료를 <b>과거 대비 몇 %ile</b>인지로 0~100 환산 → 평균 → 평활.
        <b> ⚠️ 한국은 일간 예탁금·외국인 데이터 접근이 막혀 월간 ECOS(통화량·투자자 순매수)로 대체</b>해요 — 미국(주간)보다 느립니다.
      </p>
      <p className="note">
        한국에서 <b>개인 순매수는 뺐습니다</b> — 외국인과 서로의 거래상대라 상관 <b>-0.64</b>인 거울상이라,
        같이 평균내면 변동폭의 <b>56%가 상쇄돼</b> 신호가 사라졌어요.
      </p>
    </section>
  )
}

// ── 비교 섹션: 실제 주가에 대표 지수(심리·유동성·물가·실탄)를 겹쳐 봄 (듀얼 Y축) ──
// 우리 지수(0~100)는 검증 팔레트(파랑·초록·보라·분홍), 주가는 무채색+갈색 계열로 묶어
// "주가 한 덩어리 vs 지수들"이 한눈에 갈리게 한다. price_daily.code 와 key가 1:1.
const PRICE_LINES = {
  US: [
    { key: 'us_index', name: 'S&P500', color: '#111827', width: 2 },
    { key: 'us_nasdaq', name: '나스닥', color: '#6b7280', width: 1.4 },
    { key: 'us_dow', name: '다우', color: '#b45309', width: 1.4 },
  ],
  KR: [
    { key: 'kr_index', name: '코스피', color: '#111827', width: 2 },
    { key: 'kr_kosdaq', name: '코스닥', color: '#b45309', width: 1.4 },
  ],
}
const IDX_LINES = [
  { key: 's', name: '심리', color: '#2a78d6', width: 1.3 },
  { key: 'l', name: '유동성', color: '#008300', width: 1.3 },
  { key: 'i', name: '물가', color: '#4a3aa7', width: 1.3 },
  { key: 'f', name: '실탄', color: '#d55181', width: 1.3 },
]

// 주가 표시 방식. 지수마다 절대 수준이 크게 달라(다우 5.2만 vs S&P 7.4천, 코스피 6.7천 vs 코스닥 748)
// 실제값을 한 축에 겹치면 낮은 지수가 바닥에 눌려 안 보인다 → 기본은 '지수화'.
const PMODES = [
  { key: 'base', label: '지수화(시작=100)' },
  { key: 'raw', label: '실제 주가' },
  { key: 'mom', label: '추세이탈' },
]

// 주가(오른축, 시장별 지수 여러 개) + 0~100 지수선(왼축)을 겹쳐 그리는 공용 차트.
// 비교 탭과 종합 탭이 같은 주가 처리(지수화·추세이탈·범례·이벤트)를 쓰므로 하나로 묶었다.
//   idxLines : 왼축(0~100)에 그릴 선들. 비교=4요인, 종합=종합점수 하나.
//   idxDesc  : 설명문에서 그 선들을 뭐라고 부를지.
//   refLines : 왼축 기준선(종합 탭의 60/40 경계).
function PriceOverlayChart({ rows, market, title, idxLines, idxDesc, refLines = [], height = 288, extraNote = null }) {
  const [range, setRange] = useState(756)
  const [hidden, setHidden] = useState(() => new Set())
  const [pmode, setPmode] = useState('base')  // base=지수화 / raw=실제주가 / mom=추세이탈
  const [evtTip, setEvtTip] = useState(null)  // 이벤트 이모지에 커서 올렸을 때
  const toggle = (k) => setHidden((h) => { const n = new Set(h); if (n.has(k)) n.delete(k); else n.add(k); return n })
  const pxLines = PRICE_LINES[market]
  const isMom = pmode === 'mom'
  const isBase = pmode === 'base'

  // 추세이탈 = 125일 이동평균 대비 %. 추세를 걷어내 평균회귀형으로 → 지수와 동행이 눈에 보임.
  // 지수마다 상장·휴장일이 달라 값이 빈 날이 있어, 이동평균은 '값이 있는 날'만 세어 계산한다.
  const data = useMemo(() => rows.map((r, i) => {
    const o = { ...r }
    for (const l of pxLines) {
      let sum = 0, n = 0
      for (let j = Math.max(0, i - 124); j <= i; j++) {
        const v = rows[j][l.key]
        if (v != null) { sum += v; n++ }
      }
      o['mom_' + l.key] = r[l.key] != null && n >= 60 ? (r[l.key] / (sum / n) - 1) * 100 : null
    }
    return o
  }), [rows, pxLines])

  const shown = range === Infinity ? data : data.slice(-range)
  // 지수화: 보이는 구간의 첫 값을 100으로. 구간을 바꾸면 기준도 따라 바뀐다(그 구간 안의 상대 성과).
  const plotted = useMemo(() => {
    if (!isBase) return shown
    const first = {}
    for (const l of pxLines) {
      const hit = shown.find((r) => r[l.key] != null)
      if (hit) first[l.key] = hit[l.key]
    }
    return shown.map((r) => {
      const o = { ...r }
      for (const l of pxLines) {
        o['base_' + l.key] = r[l.key] != null && first[l.key] ? (r[l.key] / first[l.key]) * 100 : null
      }
      return o
    })
  }, [shown, isBase, pxLines])

  const events = eventsFor(market, plotted)
  const pxKey = (k) => (isBase ? 'base_' + k : isMom ? 'mom_' + k : k)
  const pxFmt = (v) => (v == null ? '—'
    : isMom ? `${v > 0 ? '+' : ''}${v.toFixed(1)}%`
    : isBase ? v.toFixed(1) : Math.round(v).toLocaleString())
  return (
    <section className="card">
      <h2>{title}</h2>
      <div className="seg">
        {RANGES.map((r) => (
          <button key={r.label} className={range === r.days ? 'on' : ''} onClick={() => setRange(r.days)}>{r.label}</button>
        ))}
      </div>
      <div className="seg">
        {PMODES.map((m) => (
          <button key={m.key} className={pmode === m.key ? 'on' : ''} onClick={() => setPmode(m.key)}>{m.label}</button>
        ))}
      </div>
      <div className="chart-wrap">
      <EventTip tip={evtTip} />
      <ResponsiveContainer width="100%" height={height}>
        <LineChart data={plotted} margin={{ top: 18, right: 2, left: -24, bottom: 0 }}>
          <CartesianGrid strokeDasharray="3 3" opacity={0.15} />
          <XAxis dataKey="dt" tick={{ fontSize: 10 }} minTickGap={48} />
          <YAxis yAxisId="idx" domain={[0, 100]} tick={{ fontSize: 10 }} />
          <YAxis yAxisId="px" orientation="right" domain={['auto', 'auto']} width={46} tick={{ fontSize: 9 }}
            tickFormatter={(v) => (isMom ? `${Math.round(v)}%` : Math.round(v).toLocaleString())} />
          <Tooltip formatter={(v, name) => [
            pxLines.some((l) => l.name === name) ? pxFmt(v) : Math.round(v), name]}
            wrapperStyle={{ outline: 'none' }} />
          {isMom && <ReferenceLine yAxisId="px" y={0} stroke="#94a3b8" strokeDasharray="3 3" />}
          {isBase && <ReferenceLine yAxisId="px" y={100} stroke="#94a3b8" strokeDasharray="3 3" />}
          {refLines.map((r) => (
            <ReferenceLine key={r.y} yAxisId="idx" y={r.y} stroke={r.color} strokeDasharray="4 4" />
          ))}
          {events.map((e) => (
            <ReferenceLine key={e.dt + e.label} yAxisId="idx" x={e.x} stroke="#b0b4ba" strokeDasharray="2 3"
              label={<EventMarker evt={e} setTip={setEvtTip} />} />
          ))}
          {pxLines.map((s) => (
            <Line key={s.key} yAxisId="px" type="monotone" dataKey={pxKey(s.key)} name={s.name}
              stroke={s.color} dot={false} strokeWidth={s.width}
              hide={hidden.has(s.key)} isAnimationActive={false} connectNulls />
          ))}
          {idxLines.map((s) => (
            <Line key={s.key} yAxisId="idx" type="monotone" dataKey={s.key} name={s.name}
              stroke={s.color} dot={false} strokeWidth={s.width} strokeOpacity={0.85}
              hide={hidden.has(s.key)} isAnimationActive={false} connectNulls />
          ))}
        </LineChart>
      </ResponsiveContainer>
      </div>
      <div className="chart-legend">
        {[...pxLines, ...idxLines].map((s) => (
          <button key={s.key} className={hidden.has(s.key) ? 'off' : ''} onClick={() => toggle(s.key)}>
            <span className="swatch" style={{ background: s.color, height: s.width >= 2 ? 4 : 2 }} />
            {s.name}
          </button>
        ))}
      </div>
      <p className="note">
        {isBase
          ? <>무채색·갈색 선 = <b>주가</b>(오른축, 보이는 구간 첫날=100), {idxDesc}.
              절대 수준이 크게 달라({market === 'US' ? '다우 5.2만 vs S&P 7.4천' : '코스피 6.7천 vs 코스닥 748'})
              같은 출발선에 놓고 <b>어느 쪽이 더 올랐나</b>로 봅니다.</>
          : isMom
            ? <>주가 선 = <b>추세이탈</b>(125일 평균 대비 %, 오른축), {idxDesc}.
                추세를 걷어내면 <b>지수와 함께 출렁이는 게</b> 보여요.</>
            : <><b>실제 지수값</b>(오른축) 그대로예요 — 절대 수준 차이가 커서 낮은 지수는 바닥에 눌려 보입니다.
                하나만 남기고 범례로 끄거나, <b>지수화</b>로 보세요. ({idxDesc})</>}
        {' '}범례로 켜고 끌 수 있어요.
      </p>
      {extraNote && <p className="note">{extraNote}</p>}
    </section>
  )
}

function ComparisonChart({ rows, market }) {
  return (
    <PriceOverlayChart rows={rows} market={market} title="주가 vs 지수 겹쳐보기"
      idxLines={IDX_LINES} idxDesc="색선 = 지수 0~100(왼축)" />
  )
}

function ComparisonColumn({ market, flag, name }) {
  const [rows, setRows] = useState([])
  const [state, setState] = useState('loading')
  useEffect(() => {
    let alive = true
    ;(async () => {
      // tie: dt만으로 정렬하면 한 날짜에 행이 여러 개인 테이블(price_daily는 지수별로 3행)에서
      //      페이지 경계 순서가 흔들려 중복·누락이 생긴다 → 총순서가 되도록 두 번째 키로 정렬.
      const page = async (table, cols, tie) => {
        let all = [], from = 0
        for (;;) {
          let q = supabase.from(table).select(cols).eq('market', market).order('dt')
          if (tie) q = q.order(tie)
          const { data, error } = await q.range(from, from + 999)
          if (error) throw error
          all = all.concat(data || [])
          if (!data || data.length < 1000) break
          from += 1000
        }
        return all
      }
      try {
        const [px, sent, liq, inf, fuel] = await Promise.all([
          page('price_daily', 'dt,close,code', 'code'), page('sentiment_daily', 'dt,s_score'),
          page('liquidity_daily', 'dt,l_score'), page('inflation_daily', 'dt,i_score'),
          page('fuel_index', 'dt,f_score'),
        ])
        if (!alive) return
        if (!px.length) { setState('empty'); return }
        // 지수별 code를 한 날짜 행에 펼친다 — {dt, us_index, us_nasdaq, us_dow, s, l, i, f}
        const byDt = new Map()
        px.forEach((p) => {
          let r = byDt.get(p.dt)
          if (!r) { r = { dt: p.dt }; byDt.set(p.dt, r) }
          r[p.code] = p.close
        })
        sent.forEach((x) => { const r = byDt.get(x.dt); if (r) r.s = x.s_score })
        liq.forEach((x) => { const r = byDt.get(x.dt); if (r) r.l = x.l_score })
        inf.forEach((x) => { const r = byDt.get(x.dt); if (r) r.i = x.i_score })
        // 실탄은 주간/월간이라 주가 날짜에 없을 수 있음 → 가장 가까운(≤) 거래일에 스냅
        const dts = [...byDt.keys()]
        fuel.forEach((x) => {
          let lo = 0, hi = dts.length - 1, best = -1
          while (lo <= hi) { const m = (lo + hi) >> 1; if (dts[m] <= x.dt) { best = m; lo = m + 1 } else hi = m - 1 }
          if (best >= 0) { const r = byDt.get(dts[best]); if (r) r.f = x.f_score }
        })
        setRows([...byDt.values()]); setState('ok')
      } catch (e) {
        if (!alive) return
        const msg = `${e?.message || ''} ${e?.code || ''}`
        setState(/exist|find the table|PGRST205|42P01/i.test(msg) ? 'empty' : 'error')
      }
    })()
    return () => { alive = false }
  }, [market])
  return (
    <div className="col">
      <div className="col-head">{flag} <b>{name}</b></div>
      {state === 'loading' && <div className="col-msg">불러오는 중…</div>}
      {state === 'error' && <div className="col-msg">데이터를 불러오지 못했어요</div>}
      {state === 'empty' && <div className="col-msg soon">🚧<br /><b>데이터 준비 중</b><br /><span>price_daily 테이블 필요</span></div>}
      {state === 'ok' && <ComparisonChart rows={rows} market={market} />}
    </div>
  )
}

function ComparisonSection() {
  return (
    <>
      <header>
        <h1>비교</h1>
        <p className="lead">
          우리가 만든 지수(심리·유동성·물가·실탄)를 <b>실제 주가에 겹쳐</b> 봅니다.
          지수 고점·저점이 시장 전환과 맞물리는지 눈으로 확인하는 검증용 뷰예요.
        </p>
      </header>
      <div className="cols">
        <ComparisonColumn market="US" flag="🇺🇸" name="미국" />
        <div className="divider" />
        <ComparisonColumn market="KR" flag="🇰🇷" name="한국" />
      </div>
      <ComparisonMethod />
    </>
  )
}

function ComparisonMethod() {
  return (
    <section className="card method">
      <h2>📊 어떻게 읽나요?</h2>
      <p className="cap">이 지수들은 <b>예측기가 아니라 상태 측정기</b>예요. "지금 상태"를 잘 그리는지가 핵심.</p>
      <ul>
        <li><b>동행(지금 상태)</b> — 심리 지수는 최근 주가 흐름과 상관 <b>≈0.5</b>. 시장 분위기를 정확히 반영합니다.</li>
        <li><b>예측(앞으로)</b> — 미래 수익률과의 상관은 0.1 안팎. 금융에선 이게 정상(0.5 예측은 차익거래로 사라짐).</li>
        <li><b>유의한 신호</b> — 🇺🇸 실탄 '풍부' 뒤 이후20일 +2.8%(독립표본 26개, p&lt;0.01) 정도가 통계적으로 뚜렷.</li>
      </ul>
      <p className="note">지수가 주가와 <b>겹쳐 움직이면(동행)</b> 상태를 잘 잡는 것. 예측은 <b>극단에서만</b> 약하게 기대하세요.</p>
    </section>
  )
}

// ── 매물대 섹션: profile.py가 매일 적재하는 volume_profile을 그대로 그림 ──
// 모델: 하루 거래량을 고가~저가에 배분 + Grinblatt&Han식 회전율 감쇠(과거 물량이 매일
// 그날 회전율만큼 비례 소진). '아직 안 팔린 물량'이 어느 가격대에 얼마나 남았는지의 근사.
const VP_CODES = [
  { code: 'kospi', name: '🇰🇷 코스피' }, { code: 'kosdaq', name: '🇰🇷 코스닥' },
  { code: 'spx', name: '🇺🇸 S&P500' }, { code: 'nasdaq', name: '🇺🇸 나스닥' },
  { code: 'dow', name: '🇺🇸 다우' },
]
const VP_WINS = [
  { days: 1825, label: '5년' }, { days: 1095, label: '3년' }, { days: 730, label: '2년' },
  { days: 365, label: '1년' }, { days: 182, label: '6개월' }, { days: 91, label: '3개월' },
  { days: 30, label: '1개월' },
]

function ProfileSection() {
  const [mode, setMode] = useState('idx')    // idx = 지수 / stk = 개별종목
  const [code, setCode] = useState('kospi')
  const [win, setWin] = useState(365)
  const [rows, setRows] = useState([])
  const [state, setState] = useState('loading')
  const [stocks, setStocks] = useState([])
  const [q, setQ] = useState('')

  // 종목 목록은 vp_stocks — 매물대가 실제로 계산된 종목의 단일 출처라
  // '검색은 되는데 데이터가 없는' 불일치가 생기지 않는다. (1,700여 종목이라 페이지네이션)
  useEffect(() => {
    let alive = true
    ;(async () => {
      let all = []
      for (let from = 0; from < 4000; from += 1000) {
        const { data } = await supabase.from('vp_stocks').select('code,name,market,hist_days')
          .order('marcap', { ascending: false }).range(from, from + 999)
        if (!data || !data.length) break
        all = all.concat(data)
        if (data.length < 1000) break
      }
      if (alive) setStocks(all)
    })()
    return () => { alive = false }
  }, [])

  const stock = stocks.find((s) => s.code === code)
  // 검색: 종목명 부분일치 또는 코드 앞자리. 시총 순으로 이미 정렬돼 있어 상위가 먼저 걸린다.
  const hits = useMemo(() => {
    const k = q.trim().toLowerCase()
    if (!k) return stocks.slice(0, 24)
    return stocks.filter((s) => s.name.toLowerCase().includes(k) || s.code.startsWith(k)).slice(0, 24)
  }, [q, stocks])
  const options = mode === 'idx' ? VP_CODES : hits
  // 2년치뿐인 종목에 '5년' 버튼을 남기면 2년 그림이 5년인 척하게 된다 → 보유 구간까지만 노출
  const wins = mode === 'idx' || !stock ? VP_WINS
    : VP_WINS.filter((w) => w.days <= stock.hist_days)

  function switchMode(m) {
    if (m === mode) return
    setMode(m)
    setCode(m === 'idx' ? 'kospi' : (stocks[0]?.code || ''))
    if (m === 'idx' && win > 1825) setWin(365)
  }

  // 5년 창을 보다가 2년치뿐인 종목으로 옮기면 조회가 빈 결과가 된다 → 보유 구간으로 내린다
  useEffect(() => {
    if (stock && win > stock.hist_days) setWin(stock.hist_days)
  }, [stock, win])

  useEffect(() => {
    let alive = true
    ;(async () => {
      setState('loading')
      try {
        const { data, error } = await supabase
          .from('volume_profile').select('*')
          .eq('code', code).eq('win_days', win)
          .order('bin_lo', { ascending: false })   // 위(고가) → 아래(저가)로 그림
        if (error) throw error
        if (!alive) return
        if (!data || data.length === 0) { setState('empty'); return }
        setRows(data); setState('ok')
      } catch {
        if (alive) setState('error')
      }
    })()
    return () => { alive = false }
  }, [code, win])

  return (
    <>
      <header>
        <h1>매물대</h1>
        <p className="lead">
          가격대별로 <b>아직 안 팔린 물량(미소화 매물)</b>이 얼마나 쌓여 있는지 추정합니다.
          현재가 <b>위 매물은 반등을 막는 저항</b>, 아래 매물은 지지 · <b>얇은 구간은 진공</b>(가격이 빠르게 통과).
          집계 구간을 바꿔 <b>언제 쌓인 매물인지</b> 나눠 보세요.
        </p>
      </header>
      <div className="seg">
        <button className={mode === 'idx' ? 'on' : ''} onClick={() => switchMode('idx')}>📈 지수</button>
        <button className={mode === 'stk' ? 'on' : ''} onClick={() => switchMode('stk')}>🏢 개별종목</button>
      </div>
      {mode === 'stk' && (
        <div className="vp-search">
          <input value={q} onChange={(e) => setQ(e.target.value)}
            placeholder={`종목명 또는 코드 검색 (${stocks.length.toLocaleString()}종목)`} />
          {q && <button className="vp-clear" onClick={() => setQ('')} aria-label="검색어 지우기">✕</button>}
        </div>
      )}
      <div className="seg">
        {options.map((c) => (
          <button key={c.code} className={code === c.code ? 'on' : ''} onClick={() => setCode(c.code)}>
            {c.name}
          </button>
        ))}
        {mode === 'stk' && !options.length && <span className="vp-none">검색 결과가 없어요</span>}
      </div>
      <div className="seg">
        {wins.map((w) => (
          <button key={w.days} className={win === w.days ? 'on' : ''} onClick={() => setWin(w.days)}>
            {w.label}
          </button>
        ))}
        {mode === 'stk' && stock && stock.hist_days < 1825 && (
          <span className="vp-none">시총 상위 200종목만 5년·3년까지 봅니다</span>
        )}
      </div>
      {state === 'loading' && <div className="col-msg">불러오는 중…</div>}
      {state === 'error' && <div className="col-msg">데이터를 불러오지 못했어요</div>}
      {state === 'empty' && (
        <div className="col-msg soon">
          🚧<br /><b>데이터 준비 중</b><br />
          <span>다음 자동 갱신(평일 아침 7시) 후에 채워져요</span>
        </div>
      )}
      {state === 'ok' && <ProfileBody rows={rows} />}
      <ProfileMethod />
    </>
  )
}

// 수량 표기: 억/만주 단위로 접어 읽기 쉽게
const qtyFmt = (v) => {
  if (v == null) return '—'
  if (v >= 1e8) return (v / 1e8).toFixed(1) + '억주'
  if (v >= 1e4) return Math.round(v / 1e4).toLocaleString() + '만주'
  return Math.round(v).toLocaleString() + '주'
}

function ProfileBody({ rows }) {
  const [hover, setHover] = useState(null)
  const px = rows[0].px
  const dt = rows[0].dt
  const daily = rows[0].daily_qty          // 최근 20일 평균 거래량(주)
  const vratio = rows[0].vol_ratio
  const max = Math.max(...rows.map((r) => r.share))
  const mid = (r) => (r.bin_lo + r.bin_hi) / 2
  const above = rows.filter((r) => mid(r) > px)
  const upShare = above.reduce((s, r) => s + r.share, 0)
  const wall = above.length ? above.reduce((a, b) => (b.share > a.share ? b : a)) : null
  const upQty = above.reduce((s, r) => s + (r.qty || 0), 0)
  const fmt = (v) => Math.round(v).toLocaleString()
  // 가격 라벨은 12개 안팎만 (90구간을 다 쓰면 겹쳐서 못 읽음)
  const step = Math.max(1, Math.ceil(rows.length / 12))
  // 현재가 표시선: 현재가가 속한 구간 위에 그린다
  const nowIdx = rows.findIndex((r) => r.bin_lo <= px)

  // 현재가에서 그 구간까지 '지나가야 할' 물량. 위로 가면 저항, 아래로 가면 지지를 누적한다.
  // rows는 고가→저가 순이라 위쪽은 hover~nowIdx, 아래쪽은 nowIdx~hover 구간이 경로가 된다.
  function pathQty(i) {
    const [a, b] = i < nowIdx ? [i, nowIdx] : [nowIdx, i]
    return rows.slice(a, b + 1).reduce((s, r) => s + (r.qty || 0), 0)
  }

  return (
    <>
      <div className="raw-figs">
        <div className="raw-fig"><span className="rf-label">현재가 ({dt})</span><span className="rf-val">{fmt(px)}</span></div>
        <div className="raw-fig"><span className="rf-label">현재가 위 매물</span>
          <span className="rf-val" style={{ color: upShare > 60 ? '#c0392b' : undefined }}>{Math.round(upShare)}%</span></div>
        <div className="raw-fig"><span className="rf-label">최대 저항(본전 매물 벽)</span>
          <span className="rf-val">{wall ? `${fmt(wall.bin_lo)}~${fmt(wall.bin_hi)} (+${(mid(wall) / px * 100 - 100).toFixed(1)}%)` : '없음 (신고가 영역)'}</span></div>
      </div>
      {daily > 0 && (
        <div className="raw-figs">
          <div className="raw-fig"><span className="rf-label">위쪽 매물 전량 소화에 필요한 거래일</span>
            <span className="rf-val">{above.length ? `${(upQty / daily).toFixed(1)}일치` : '—'}</span></div>
          <div className="raw-fig"><span className="rf-label">하루 평균 거래량 (20일)</span>
            <span className="rf-val">{qtyFmt(daily)}</span></div>
          <div className="raw-fig"><span className="rf-label">최근일 거래량 배율</span>
            <span className="rf-val" style={{ color: vratio >= 1.5 ? '#c0392b' : undefined }}>
              {vratio == null ? '—' : `${vratio.toFixed(2)}배`}</span></div>
        </div>
      )}
      <section className="card">
        <div className="vp-bars">
          {rows.map((r, i) => (
            <div key={r.bin_lo}>
              {i === nowIdx && <div className="vp-now"><span>현재가 {fmt(px)}</span></div>}
              {/* 모바일엔 커서가 없다 — 탭으로도 같은 정보가 뜨게 클릭을 함께 받는다 */}
              <div className={'vp-row' + (hover === i ? ' on' : '')}
                onMouseEnter={() => setHover(i)} onMouseLeave={() => setHover(null)}
                onClick={() => setHover(hover === i ? null : i)}>
                <span className="vp-price">{i % step === 0 ? fmt(r.bin_lo) : ''}</span>
                <div className="vp-bar" style={{
                  width: `${Math.max(0.5, r.share / max * 100)}%`,
                  background: mid(r) > px ? '#c0392b' : '#2471a3',
                }} />
              </div>
            </div>
          ))}
        </div>
        {hover != null && (
          <div className="vp-tip">
            <b>{fmt(rows[hover].bin_lo)} ~ {fmt(rows[hover].bin_hi)}</b>
            <span>({(mid(rows[hover]) / px * 100 - 100).toFixed(1)}%)</span>
            {rows[hover].qty != null && <em>이 구간 {qtyFmt(rows[hover].qty)}</em>}
            {daily > 0 && (
              <em>현재가↔여기 {qtyFmt(pathQty(hover))} = <b>{(pathQty(hover) / daily).toFixed(1)}일치</b></em>
            )}
          </div>
        )}
        <p className="note">
          <b style={{ color: '#c0392b' }}>빨강</b> = 현재가 위(반등 시 본전 매도 압력) ·{' '}
          <b style={{ color: '#2471a3' }}>파랑</b> = 아래(하락 시 받치는 손바뀜 물량) ·
          막대 길이 = 잔존 물량(최대=1). 막대가 짧은 곳은 <b>진공 구간</b> — 가격이 빠르게 지나가기 쉬워요.
          <b> 막대를 누르거나 커서를 올리면</b> 거기까지 가는 데 며칠치 거래량이 필요한지 나옵니다.
        </p>
      </section>
    </>
  )
}

function ProfileMethod() {
  return (
    <section className="card method">
      <h2>⛰️ 어떻게 계산하나요?</h2>
      <ul>
        <li><b>배분</b> — 하루 거래량을 그날 고가~저가 가격 구간에 나눠 쌓습니다(볼륨 프로파일).</li>
        <li><b>소진</b> — 쌓인 물량은 매일 <b>그날 회전율만큼 비례로 손바뀜</b>돼 줄어듭니다
          (Grinblatt&amp;Han 2005). 급등락이 반복되면 회전율이 치솟아 옛 매물이 빨리 소화돼요.</li>
        <li><b>집계 구간</b> — 5년~1개월로 잘라 계산합니다. 짧은 구간 = 최근 진입자의 물량만 본 것.</li>
        <li><b>개별종목이 더 정확합니다</b> — 종목은 <b>거래대금÷시가총액</b>이 곧 진짜 회전율이라
          모델이 정의대로 돌아가고, 매물대라는 개념 자체도 합성물인 지수보다 또렷해요.</li>
        <li><b>소화 일수</b> — 쌓인 물량 ÷ 하루 평균 거래량. "이 구간을 지나가려면 며칠치 거래가
          필요한가"입니다. 짧을수록 빨리 통과하지만, <b>어느 방향으로 갈지는 말해주지 않습니다</b> —
          거래가 매수로 터질지 매도로 터질지는 매물대 밖의 일이에요.</li>
      </ul>
      <p className="note">⚠️ <b>한계</b>: 지수는 개별 종목의 합성이라 매물대가 개별주보다 흐릿하고,
        회전율도 유통주식수 대신 <b>직전 1년 거래량 합 대비</b>로 근사합니다(한국 지수는 KRX 실제 회전율 사용) ·
        거래량은 KRX 기준(NXT 미포함) · 일봉이라 장중 가격대 배분은 균등 가정 · 파생/ETF 간접 물량은 안 잡힙니다.
        <b>정밀 측정이 아니라 구조 파악용</b>이에요.</p>
    </section>
  )
}

// ── 종합 섹션 ──
// 비율 슬라이더는 한 벌만 두고 두 시장에 함께 적용한다(같은 기준으로 비교해야 의미가 있음).
// 비율은 브라우저에 저장해 새로고침해도 유지한다(고정값 슬롯 포함).
const MIX_LS_KEY = 'stocklab.mix.v1'
// 저장된 값에 빠진 요인이 있으면(요인이 추가·변경된 뒤 등) 기본값으로 메워 준다.
// 안 그러면 value={undefined}가 돼 input이 uncontrolled로 바뀐다.
const fillW = (o) => Object.fromEntries(
  MIX_FACTORS.map((f) => [f.key, Number.isFinite(o?.[f.key]) ? o[f.key] : 0]))
const fillInv = (o) => Object.fromEntries(
  MIX_FACTORS.map((f) => [f.key, typeof o?.[f.key] === 'boolean' ? o[f.key] : f.invert]))

function loadMixPrefs() {
  try {
    const s = JSON.parse(localStorage.getItem(MIX_LS_KEY))
    if (!s) return {}
    return {
      w: s.w ? fillW(s.w) : null,
      inv: s.inv ? fillInv(s.inv) : null,
      pinned: s.pinned ? { w: fillW(s.pinned.w), inv: fillInv(s.pinned.inv) } : null,
    }
  } catch { return {} }
}

function CompositeSection() {
  const saved = useMemo(loadMixPrefs, [])
  const [w, setW] = useState(() => saved.w || MIX_PRESETS[0].w)
  const [inv, setInv] = useState(() => saved.inv
    || Object.fromEntries(MIX_FACTORS.map((f) => [f.key, f.invert])))
  const [pinned, setPinned] = useState(() => saved.pinned || null)

  useEffect(() => {   // 사파리 프라이빗 모드 등에서 막힐 수 있어 조용히 무시
    try { localStorage.setItem(MIX_LS_KEY, JSON.stringify({ w, inv, pinned })) } catch { /* 저장 불가 */ }
  }, [w, inv, pinned])

  const total = MIX_FACTORS.reduce((a, f) => a + (w[f.key] || 0), 0)
  const sameW = (a, b) => MIX_FACTORS.every((f) => (a[f.key] || 0) === (b[f.key] || 0))
  const preset = MIX_PRESETS.find((p) => sameW(p.w, w))
  const onPinned = pinned && sameW(pinned.w, w)
    && MIX_FACTORS.every((f) => !!pinned.inv[f.key] === !!inv[f.key])
  const setNum = (k, v) => setW({ ...w, [k]: Math.max(0, Math.min(100, Math.round(v) || 0)) })

  return (
    <>
      <header>
        <h1>종합</h1>
        <p className="lead">
          <b>주가와 무관한 배경 요인</b>(유동성·물가·실탄)을 내가 정한 비율로 합쳐 하나의 점수로.
          이 요인들은 주가보다 <b>관성이 커서</b>, 앞으로 두 달쯤을 가늠하는 데 쓸 수 있어요.
          <b> 아래 조절판은 화면에 붙어 있어</b> 그래프를 보면서 바로 바꿀 수 있습니다.
        </p>
      </header>

      <div className="cols">
        <CompositeColumn market="US" flag="🇺🇸" name="미국" w={w} inv={inv} />
        <div className="divider" />
        <CompositeColumn market="KR" flag="🇰🇷" name="한국" w={w} inv={inv} />
      </div>

      {/* 화면 아래에 붙여둔다 — 차트를 보든 표를 보든 스크롤 없이 손이 닿게 */}
      <section className="card weights dock">
        <div className="whead">
          <h2>⚖️ 비율 조절</h2>
          <div className="seg">
            {MIX_PRESETS.map((p) => (
              <button key={p.name} className={preset && preset.name === p.name && !onPinned ? 'on' : ''}
                onClick={() => setW(p.w)}>{p.name}</button>
            ))}
            {pinned && (
              <button className={onPinned ? 'on' : ''}
                onClick={() => { setW(pinned.w); setInv(pinned.inv) }}>📌 내 비율</button>
            )}
            <button className="wpin" onClick={() => setPinned({ w: { ...w }, inv: { ...inv } })}>
              {pinned ? '내 비율 갱신' : '📌 내 비율로 고정'}
            </button>
            {pinned && <button className="wpin" onClick={() => setPinned(null)}>고정 해제</button>}
          </div>
        </div>
        {MIX_FACTORS.map((f) => (
          <div key={f.key} className="wrow">
            <span className="wname"><i style={{ background: f.color }} />{f.name}</span>
            <input type="range" min="0" max="100" step="1" value={w[f.key]}
              style={{ accentColor: f.color }}
              onChange={(e) => setNum(f.key, +e.target.value)} />
            <input type="number" className="wnum" min="0" max="100" value={w[f.key]}
              onChange={(e) => setNum(f.key, +e.target.value)} />
            <span className="wpct">{total ? Math.round((w[f.key] / total) * 100) : 0}%</span>
            <button className={'wdir' + (inv[f.key] ? ' on' : '')}
              title="점수가 높을 때 유리한지, 낮을 때 유리한지 뒤집습니다"
              onClick={() => setInv({ ...inv, [f.key]: !inv[f.key] })}>
              {inv[f.key] ? '반전' : '정방향'}
            </button>
            <span className="whint">{inv[f.key] === f.invert ? f.hint : '방향을 뒤집었어요'}</span>
          </div>
        ))}
        <p className="note">
          가운데 칸에 <b>숫자를 직접 넣어도</b> 됩니다. 비율은 합이 100%가 되도록 자동 환산되니
          아무 값이나 써도 되고, <b>📌 내 비율로 고정</b>을 누르면 이 브라우저에 저장돼 다음에도 그대로 열립니다.
        </p>
      </section>
      <CompositeMethod />
    </>
  )
}

function CompositeColumn({ market, flag, name, w, inv }) {
  const [rows, setRows] = useState([])
  const [state, setState] = useState('loading')
  const [h, setH] = useState(60)

  useEffect(() => {
    let alive = true
    ;(async () => {
      const page = async (table, cols, tie) => {
        let all = [], from = 0
        for (;;) {
          let q = supabase.from(table).select(cols).eq('market', market).order('dt')
          if (tie) q = q.order(tie)
          const { data, error } = await q.range(from, from + 999)
          if (error) throw error
          all = all.concat(data || [])
          if (!data || data.length < 1000) break
          from += 1000
        }
        return all
      }
      try {
        const [px, ...facs] = await Promise.all([
          page('price_daily', 'dt,close,code', 'code'),
          ...MIX_FACTORS.map((f) => page(f.table, `dt,${f.col}`)),
        ])
        if (!alive) return
        // 주가는 지수별 code를 그대로 펼친다 — 비교 탭과 같은 차트를 쓰기 때문(지수화·추세이탈)
        const byDt = new Map()
        px.forEach((p) => {
          let r = byDt.get(p.dt)
          if (!r) { r = { dt: p.dt }; byDt.set(p.dt, r) }
          r[p.code] = p.close
        })
        MIX_FACTORS.forEach((f, k) => {
          facs[k].forEach((x) => { const r = byDt.get(x.dt); if (r) r[f.key] = x[f.col] })
        })
        // 실탄은 주간/월간이라 빈 날이 많음 → 직전값으로 이어 붙인다(그날까지 알려진 최신값)
        const main = PRICE_LINES[market][0].key    // 대표 지수 — 밴드 통계는 이걸로 낸다
        const out = []
        const last = {}
        for (const r of byDt.values()) {
          for (const f of MIX_FACTORS) {
            if (r[f.key] == null) r[f.key] = last[f.key]
            else last[f.key] = r[f.key]
          }
          if (r[main] != null && MIX_FACTORS.every((f) => r[f.key] != null)) out.push(r)
        }
        if (!out.length) { setState('empty'); return }
        setRows(out); setState('ok')
      } catch (e) {
        if (!alive) return
        const msg = `${e?.message || ''} ${e?.code || ''}`
        setState(/exist|find the table|PGRST205|42P01/i.test(msg) ? 'empty' : 'error')
      }
    })()
    return () => { alive = false }
  }, [market])

  // 비율이 바뀔 때마다 다시 계산되는 부분 — 여기가 슬라이더의 반응 지점.
  const data = useMemo(() => {
    const tot = MIX_FACTORS.reduce((a, f) => a + (w[f.key] || 0), 0) || 1
    return rows.map((r) => {
      let mix = 0
      for (const f of MIX_FACTORS) {
        mix += (inv[f.key] ? 100 - r[f.key] : r[f.key]) * (w[f.key] || 0) / tot
      }
      return { ...r, mix }
    })
  }, [rows, w, inv])

  const stats = useMemo(() => {
    const main = PRICE_LINES[market][0].key       // 대표 지수(미국 S&P500 / 한국 코스피)
    // runs = 연속 구간 수. 'n일'은 통계처럼 보이지만 붙어있는 날은 사실상 한 사건이라,
    // 실제 근거가 몇 개인지 같이 세어 보여준다(n=394일이 국면 8개인 경우가 실제로 있었음).
    const buckets = MIX_BANDS.map((b) => ({ band: b, n: 0, sum: 0, win: 0, runs: 0 }))
    let prev = -1
    for (let k = 0; k + h < data.length; k++) {
      const a = data[k][main], z = data[k + h][main]
      if (a == null || z == null) continue
      const bi = Math.min(4, Math.floor(data[k].mix / 20))
      const b = buckets[bi]
      if (bi !== prev) b.runs++
      prev = bi
      b.n++; b.sum += (z / a - 1) * 100; if (z > a) b.win++
    }
    return buckets
  }, [data, h, market])

  const latest = data.length ? data[data.length - 1] : null
  return (
    <div className="col">
      <div className="col-head">{flag} <b>{name}</b></div>
      {state === 'loading' && <div className="col-msg">불러오는 중…</div>}
      {state === 'error' && <div className="col-msg">데이터를 불러오지 못했어요</div>}
      {state === 'empty' && <div className="col-msg soon">🚧<br /><b>데이터 준비 중</b></div>}
      {state === 'ok' && latest && (
        <>
          <p className="col-date">{latest.dt} 기준</p>
          <Gauge value={latest.mix} band={mixBandOf(latest.mix)} lowLabel="불리" highLabel="유리"
            desc={MIX_BAND_DESC[mixBandOf(latest.mix).name]} />
          <OutlookCard data={data} market={market} />
          <MixChart data={data} market={market} />
          <section className="card">
            <h2>종합점수 밴드별 '이후 {h}일' 수익률</h2>
            <div className="seg">
              {MIX_HORIZONS.map((x) => (
                <button key={x} className={h === x ? 'on' : ''} onClick={() => setH(x)}>{x}일</button>
              ))}
            </div>
            <table className="stats">
              <thead><tr><th>구간</th><th>일수</th><th>이후{h}일</th><th>승률</th></tr></thead>
              <tbody>
                {stats.map((b, k) => {
                  if (!b.n) return null
                  const avg = b.sum / b.n
                  const color = avg > 2 ? '#1e8449' : avg < 0 ? '#c0392b' : 'inherit'
                  return (
                    <tr key={b.band.name}>
                      <td><span className="bdot" style={{ background: b.band.color }} />
                        {k * 20}~{k * 20 + 20} {b.band.name}</td>
                      <td>{b.n}<span className="runs">국면 {b.runs}</span></td>
                      <td style={{ color, fontWeight: avg > 2 || avg < 0 ? 700 : 400 }}>
                        {avg > 0 ? '+' : ''}{avg.toFixed(1)}%
                      </td>
                      <td>{Math.round((b.win / b.n) * 100)}%</td>
                    </tr>
                  )
                })}
              </tbody>
            </table>
            <p className="note">
              지금 비율로 <b>과거 전체를 다시 계산</b>한 결과예요. 위로 갈수록 수익률이 높아지면
              그 비율이 국면을 잘 가른다는 뜻입니다.
            </p>
            <p className="note">
              ⚠️ <b>'일수'가 아니라 '국면 수'를 보세요.</b> 붙어있는 날들은 사실상 한 사건이라,
              300일이어도 국면이 5개면 근거는 <b>5개</b>입니다. 국면이 한 자릿수면 우연일 수 있어요.
            </p>
          </section>
        </>
      )}
    </div>
  )
}

// 전망 카드 — '지금과 비슷한 배경이었던 과거'의 이후 수익률 분포.
// 점 예측이 아니라 분포로 낸다. 배경지수의 절대 수준은 시대별로 이동해서(2016년의 60과
// 2025년의 60이 다름) 고정 임계값은 기간을 갈랐을 때 무너졌다 — '지난 3년 중 몇 %'로만 통했다.
// 60일 지평인 이유: 요인 지속성이 20일 .93 / 60일 .78인데 120일부터 물가가 .27로 무너진다.
const OUTLOOK_H = 60
const OUTLOOK_WIN = 756      // 백분위 기준 창 = 3년
const OUTLOOK_NEAR = 12      // '비슷한 위치'로 볼 백분위 허용 오차(%p)

function OutlookCard({ data, market }) {
  const out = useMemo(() => {
    const main = PRICE_LINES[market][0].key
    // 각 시점의 '지난 3년 중 백분위' — 그 시점까지의 과거만 사용(미래 정보 없음)
    const p = new Array(data.length).fill(null)
    for (let i = 0; i < data.length; i++) {
      const from = Math.max(0, i - OUTLOOK_WIN)
      let cnt = 0, n = 0
      for (let j = from; j < i; j++) { if (data[j].mix < data[i].mix) cnt++; n++ }
      if (n >= 250) p[i] = (cnt / n) * 100
    }
    const cur = p[p.length - 1]
    if (cur == null) return null
    const rets = [], idxs = []
    for (let i = 0; i + OUTLOOK_H < data.length; i++) {
      if (p[i] == null || Math.abs(p[i] - cur) > OUTLOOK_NEAR) continue
      const a = data[i][main], z = data[i + OUTLOOK_H][main]
      if (a == null || z == null) continue
      rets.push((z / a - 1) * 100); idxs.push(i)
    }
    if (rets.length < 30) return { cur, n: rets.length, thin: true }
    let runs = 0
    idxs.forEach((v, k) => { if (k === 0 || v - idxs[k - 1] > 5) runs++ })
    const s = [...rets].sort((a, b) => a - b)
    const q = (x) => s[Math.min(s.length - 1, Math.floor(s.length * x))]
    return { cur, n: rets.length, runs,
      avg: rets.reduce((a, b) => a + b, 0) / rets.length,
      win: (rets.filter((r) => r > 0).length / rets.length) * 100,
      p10: q(0.1), p90: q(0.9), worst: s[0], best: s[s.length - 1] }
  }, [data, market])

  if (!out) return null
  // cur = '지난 3년 값 중 몇 %가 오늘보다 낮은가'. 높을수록 유리한 점수이므로
  // 위쪽이면 '상위 N%', 아래쪽이면 '하위 N%'로 읽어야 방향을 헷갈리지 않는다.
  const pos = out.cur >= 50
    ? { label: `상위 ${Math.round(100 - out.cur)}%`, good: true }
    : { label: `하위 ${Math.round(out.cur)}%`, good: false }
  if (out.thin) {
    return (
      <section className="card">
        <h2>🔮 {OUTLOOK_H}일 전망</h2>
        <p className="note">지금과 비슷한 배경이었던 과거가 {out.n}일뿐이라 통계를 낼 수 없어요.
          비율을 바꾸거나 데이터가 더 쌓이길 기다려야 합니다.</p>
      </section>
    )
  }
  const tone = out.avg > 3 ? '#1e8449' : out.avg < 0 ? '#c0392b' : '#334155'
  return (
    <section className="card outlook">
      <h2>🔮 {OUTLOOK_H}일 전망</h2>
      <p className="cap">
        지금 배경은 지난 3년 중 <b style={{ color: pos.good ? '#1e8449' : '#c0392b' }}>{pos.label}</b>
        {pos.good ? ' (우호적인 편)' : ' (우호적이지 않은 편)'}.
        과거 <b>비슷한 위치</b>였을 때 이후 {OUTLOOK_H}일은 —
      </p>
      <div className="ocells">
        <div><span>평균</span><b style={{ color: tone }}>{out.avg > 0 ? '+' : ''}{out.avg.toFixed(1)}%</b></div>
        <div><span>올랐던 비율</span><b>{Math.round(out.win)}%</b></div>
        <div><span>흔한 범위</span><b>{out.p10.toFixed(0)}~{out.p90.toFixed(0)}%</b></div>
      </div>
      <div className="owarn">
        <b>근거는 {out.runs}개 국면입니다</b> ({out.n}일이지만 붙어있는 날은 한 사건).
        최악 {out.worst.toFixed(0)}% · 최고 {out.best.toFixed(0)}%까지 있었어요.
        {out.runs < 10 && <> 국면이 {out.runs}개면 <b>우연일 수 있는 수준</b>입니다.</>}
      </div>
      <p className="note">
        평균 하나만 보지 마세요. <b>'흔한 범위'가 실제로 겪을 폭</b>이고, 그마저 10번 중 2번은 벗어납니다.
        이건 <b>비슷한 배경에서 과거에 이랬다</b>는 기록이지 앞으로의 약속이 아니에요.
      </p>
    </section>
  )
}

const MIX_IDX_LINE = [{ key: 'mix', name: '종합점수', color: '#d97706', width: 2.4 }]
const MIX_REF = [{ y: 60, color: '#1e8449' }, { y: 40, color: '#c0392b' }]

function MixChart({ data, market }) {
  return (
    <PriceOverlayChart rows={data} market={market} title="종합점수 vs 주가"
      idxLines={MIX_IDX_LINE} idxDesc={<>굵은 <b style={{ color: '#d97706' }}>주황</b> = 종합점수 0~100(왼축)</>}
      refLines={MIX_REF}
      extraNote={<>가로 점선은 <b>60(유리)</b>·<b>40(불리)</b> 경계예요. 주황이 낮을 때 주가가 바닥이었는지 눈으로 확인해보세요.</>} />
  )
}

function CompositeMethod() {
  return (
    <section className="card method">
      <h2>🧭 종합점수, 어떻게 읽나요?</h2>
      <p className="cap">
        네 요인을 <b>같은 방향(높을수록 유리)</b>으로 맞춘 뒤 비율대로 평균낸 값. 0~100.
      </p>
      <ul>
        <li><b>💧 유동성</b> — 정방향. 돈이 풀렸을수록 유리.</li>
        <li><b>🔥 물가</b> — <b>반전</b>. 저물가일수록 유리.</li>
        <li><b>💰 실탄</b> — 정방향. 증시로 들어올 돈이 많을수록 유리.</li>
        <li><b>😨 심리</b> — <b>기본값 0</b>. 아래 이유로 뺐지만 슬라이더로 넣어볼 수 있어요.</li>
      </ul>
      <p className="note">
        <b>왜 심리를 뺐나</b> — 심리는 4성분이 거의 다 <b>주가로 만들어져</b> 있어요(모멘텀 = 지수÷125일평균,
        위험선호 = 주식−채권, 시장폭 = 지수−지수). 넣으면 <b>주가로 주가를 설명</b>하는 꼴이 됩니다.
        실제로 심리를 빼니 주가 선행 상관(+60일)이 🇺🇸 0.36→<b>0.41</b>, 🇰🇷 0.29→<b>0.47</b>로 올라갔어요.
        심리는 <b>"지금 상태"</b>를 재는 데 쓰고(동시점 상관 0.5), <b>"앞으로"</b>는 배경 3요인에 맡깁니다.
      </p>
      <p className="note">
        <b>왜 60일인가</b> — 요인이 얼마나 오래 관성을 갖는지가 예측 지평을 정합니다.
        유동성은 60일 뒤에도 0.78, 실탄 0.75로 버티지만 120일부터 물가가 0.27로 무너져요.
        참고로 <b>주가 추세는 60일이면 0.17</b>까지 떨어집니다 — 배경이 주가보다 훨씬 오래 갑니다.
      </p>
      <p className="note">
        ⚠️ <b>절대 점수가 아니라 상대 위치로 보세요.</b> 기간을 반으로 갈라 검증했더니
        "60점 이상이면 유리" 같은 고정 기준은 무너졌지만(🇰🇷 전반 -1.3% / 후반 +24.2%),
        <b>"지난 3년 중 상위 30%"</b>는 미국·한국 네 구간 전부에서 통했어요. 전망 카드가 이 방식을 씁니다.
      </p>
    </section>
  )
}

// ── AI 사이클 계기판 ──
// ⚠️ 예측 탭이 아니다. 반도체 실물지표(한국수출·자본재수주·재고·PPI)의 붕괴 예측력을
// 검증했더니 오경보율 70~82%로 기준선(71%)을 하나도 넘지 못했다(2026-07).
// 이 탭은 ① 지금 얼마나 쏠려 있나(상대강도) ② 결정적 신호는 지표가 아니라 분기 문서에
// 있다는 체크리스트 — 두 가지만 담는다.
const AI_NAMES = [
  { key: 'sox', rkey: 'r_sox', name: 'SOX 반도체지수', base: 'S&P500 대비', color: '#d97706',
    fmt: (v) => Math.round(v).toLocaleString() },
  { key: 'tsmc', rkey: 'r_tsmc', name: 'TSMC', base: '가권 대비', color: '#2a78d6',
    fmt: (v) => 'NT$' + Math.round(v).toLocaleString() },
  { key: 'samsung', rkey: 'r_samsung', name: '삼성전자', base: '코스피 대비', color: '#008300',
    fmt: (v) => Math.round(v).toLocaleString() + '원' },
  { key: 'hynix', rkey: 'r_hynix', name: 'SK하이닉스', base: '코스피 대비', color: '#d55181',
    fmt: (v) => Math.round(v).toLocaleString() + '원' },
]

// 컬럼별 통계 — 결측(거래소 휴장)이 섞여 있어 '값이 있는 날'만으로 계산한다.
function aiStat(rows, key) {
  const s = rows.filter((r) => r[key] != null)
  if (s.length < 130) return null
  const last = s[s.length - 1][key]
  const y1 = s.length > 252 ? (last / s[s.length - 253][key] - 1) * 100 : null
  let hi = -Infinity
  for (let i = Math.max(0, s.length - 125); i < s.length; i++) hi = Math.max(hi, s[i][key])
  return { last, y1, fromHi: (last / hi - 1) * 100 }
}

function AISection() {
  const [rows, setRows] = useState([])
  const [state, setState] = useState('loading')
  useEffect(() => {
    let alive = true
    ;(async () => {
      try {
        let all = [], from = 0
        for (;;) {
          const { data, error } = await supabase.from('ai_daily').select('*')
            .order('dt').range(from, from + 999)
          if (error) throw error
          all = all.concat(data || [])
          if (!data || data.length < 1000) break
          from += 1000
        }
        if (!alive) return
        if (!all.length) { setState('empty'); return }
        setRows(all); setState('ok')
      } catch (e) {
        if (!alive) return
        const msg = `${e?.message || ''} ${e?.code || ''}`
        setState(/exist|find the table|PGRST205|42P01/i.test(msg) ? 'empty' : 'error')
      }
    })()
    return () => { alive = false }
  }, [])

  return (
    <>
      <header>
        <h1>AI 사이클</h1>
        <p className="lead">
          AI 랠리를 이끄는 <b>반도체 밸류체인</b>(미국 SOX · 대만 TSMC · 한국 삼성전자·하이닉스)이
          자국 지수 대비 <b>얼마나 쏠려 있는지</b>를 봅니다.
          <b> 예측하지 않습니다</b> — 쏠림의 해소 시점을 알려주는 지표는 검증 결과 없었어요.
        </p>
      </header>
      {state === 'loading' && <div className="col-msg">불러오는 중…</div>}
      {state === 'error' && <div className="col-msg">데이터를 불러오지 못했어요</div>}
      {state === 'empty' && (
        <div className="col-msg soon">🚧<br /><b>데이터 준비 중</b><br /><span>ai_daily 테이블 필요</span></div>
      )}
      {state === 'ok' && (
        <>
          <AIStatus rows={rows} />
          <AIChart rows={rows} />
          <AIChecklist />
          <AIMethod />
        </>
      )}
    </>
  )
}

function AIStatus({ rows }) {
  const latest = rows[rows.length - 1]
  return (
    <section className="card">
      <h2>현재 상태 <span style={{ fontWeight: 400, color: '#94a3b8' }}>({latest.dt} 기준)</span></h2>
      <table className="stats">
        <thead><tr><th>종목</th><th>주가</th><th>1년 수익률</th><th>쏠림 (상대강도, 125일 고점 대비)</th></tr></thead>
        <tbody>
          {AI_NAMES.map((n) => {
            const px = aiStat(rows, n.key)
            const rel = aiStat(rows, n.rkey)
            if (!px || !rel) return null
            const hot = rel.fromHi > -3   // 고점 3% 이내면 쏠림 최고조 부근
            return (
              <tr key={n.key}>
                <td><span className="bdot" style={{ background: n.color }} />{n.name}</td>
                <td>{n.fmt(px.last)}</td>
                <td style={{ color: px.y1 > 0 ? '#1e8449' : '#c0392b' }}>
                  {px.y1 == null ? '—' : `${px.y1 > 0 ? '+' : ''}${px.y1.toFixed(0)}%`}
                </td>
                <td style={{ fontWeight: 700, color: hot ? '#c0392b' : '#334155' }}>
                  {rel.fromHi > 0 ? '+' : ''}{rel.fromHi.toFixed(1)}%
                  <span style={{ fontWeight: 400, color: '#94a3b8' }}> {n.base}{hot ? ' · 고점권' : ''}</span>
                </td>
              </tr>
            )
          })}
        </tbody>
      </table>
      <p className="note">
        <b>쏠림</b> = 종목÷자국지수 비율이 최근 125일 고점에서 얼마나 내려왔나.
        <b> 0%에 가까울수록 시장 대비 쏠림이 최고조</b>, 음수가 깊어질수록 식는 중입니다.
        1년 수익률이 크면서 쏠림이 이미 마이너스면 — 랠리는 컸는데 <b>지수 대비 주도력은 꺾이는 중</b>이란 뜻이에요.
      </p>
    </section>
  )
}

function AIChart({ rows }) {
  const [mode, setMode] = useState('rel')     // rel=상대강도 / px=주가
  const [range, setRange] = useState(756)
  const [hidden, setHidden] = useState(() => new Set())
  const [evtTip, setEvtTip] = useState(null)
  const toggle = (k) => setHidden((h) => { const n = new Set(h); if (n.has(k)) n.delete(k); else n.add(k); return n })
  const lines = useMemo(() => AI_NAMES.map((n) => ({
    key: mode === 'rel' ? n.rkey : n.key,
    name: mode === 'rel' ? `${n.name.split(' ')[0]}(${n.base})` : n.name.split(' ')[0],
    color: n.color, width: n.key === 'sox' ? 2.2 : 1.4,
  })), [mode])
  const shown = range === Infinity ? rows : rows.slice(-range)
  // 보이는 구간 첫 값=100으로 지수화 — 통화·단위가 달라 절대값 비교가 무의미하다
  const plotted = useMemo(() => {
    const first = {}
    for (const l of lines) {
      const hit = shown.find((r) => r[l.key] != null)
      if (hit) first[l.key] = hit[l.key]
    }
    return shown.map((r) => {
      const o = { dt: r.dt }
      for (const l of lines) o[l.key] = r[l.key] != null && first[l.key] ? (r[l.key] / first[l.key]) * 100 : null
      return o
    })
  }, [shown, lines])
  const events = eventsFor('US', plotted)
  return (
    <section className="card">
      <h2>{mode === 'rel' ? '상대강도 추이 (자국 지수 대비, 구간 시작=100)' : '주가 추이 (구간 시작=100)'}</h2>
      <div className="seg">
        {RANGES.map((r) => (
          <button key={r.label} className={range === r.days ? 'on' : ''} onClick={() => setRange(r.days)}>{r.label}</button>
        ))}
      </div>
      <div className="seg">
        <button className={mode === 'rel' ? 'on' : ''} onClick={() => setMode('rel')}>상대강도(지수 대비)</button>
        <button className={mode === 'px' ? 'on' : ''} onClick={() => setMode('px')}>주가</button>
      </div>
      <div className="chart-wrap">
      <EventTip tip={evtTip} />
      <ResponsiveContainer width="100%" height={278}>
        <LineChart data={plotted} margin={{ top: 18, right: 8, left: -18, bottom: 0 }}>
          <CartesianGrid strokeDasharray="3 3" opacity={0.15} />
          <XAxis dataKey="dt" tick={{ fontSize: 10 }} minTickGap={48} />
          <YAxis domain={['auto', 'auto']} tick={{ fontSize: 10 }} width={40} />
          <Tooltip formatter={(v, n) => [v == null ? '—' : v.toFixed(1), n]} wrapperStyle={{ outline: 'none' }} />
          <ReferenceLine y={100} stroke="#94a3b8" strokeDasharray="3 3" />
          {events.map((e) => (
            <ReferenceLine key={e.dt + e.label} x={e.x} stroke="#b0b4ba" strokeDasharray="2 3"
              label={<EventMarker evt={e} setTip={setEvtTip} />} />
          ))}
          {lines.map((l) => (
            <Line key={l.key} type="monotone" dataKey={l.key} name={l.name}
              stroke={l.color} dot={false} strokeWidth={l.width}
              hide={hidden.has(l.key)} isAnimationActive={false} connectNulls />
          ))}
        </LineChart>
      </ResponsiveContainer>
      </div>
      <div className="chart-legend">
        {lines.map((l) => (
          <button key={l.key} className={hidden.has(l.key) ? 'off' : ''} onClick={() => toggle(l.key)}>
            <span className="swatch" style={{ background: l.color, height: l.width >= 2 ? 4 : 2 }} />
            {l.name}
          </button>
        ))}
      </div>
      <p className="note">
        {mode === 'rel'
          ? <><b>상대강도 = 종목 ÷ 자국 지수.</b> 100 위면 그 구간에서 지수를 이기는 중.
              과거 사이클(2018·2021·2024)에서 <b>상대강도 꺾임은 예고가 아니라 동행</b>이었어요 — 확인용이지 선행 신호가 아닙니다.</>
          : <>통화가 달라(NT$·원·pt) <b>구간 시작=100으로 지수화</b>했어요. 어느 종목이 더 올랐는지만 비교됩니다.</>}
        {' '}범례로 켜고 끌 수 있어요.
      </p>
    </section>
  )
}

function AIChecklist() {
  const items = [
    ['🏗️ 하이퍼스케일러 CapEx 가이던스', 'MS·구글·아마존·메타 실적발표. "수요 초과" → "규율 있는(disciplined) 투자"로 언어가 바뀌는 순간이 사실상의 전환 선언'],
    ['📉 감가상각 연한 변경', '서버 수명을 4→6년으로 늘리는 회계 변경 = GPU 비용을 미래로 미는 것. 이미 일부 시작 — 추가 연장 여부를 10-K/10-Q 주석에서'],
    ['🧾 엔비디아 매출채권 vs 매출', '매출채권 증가율이 매출 증가율을 계속 앞서면 밀어내기 신호. 분기 10-Q'],
    ['🔄 순환 조달 구조', '엔비디아→고객사 투자→그 돈으로 GPU 구매. 네오클라우드 회사채 스프레드·GPU 담보대출 조건이 조이는지'],
    ['📊 AI 매출 ÷ CapEx 갭', '연 수천억$ 투자를 정당화할 최종 매출이 자라는가. GPU는 4~6년이면 소진되는 자산이라 시간 제한이 있는 질문'],
  ]
  return (
    <section className="card method">
      <h2>📋 분기 체크리스트 — 결정적 신호는 지표가 아니라 문서에</h2>
      <p className="cap">
        서브프라임을 미리 본 사람들은 지표가 아니라 <b>원본 문서</b>를 읽었어요.
        AI 사이클의 전환도 아래 다섯 가지에서 먼저 드러날 가능성이 높습니다 — 분기마다 직접 확인하는 목록입니다.
      </p>
      <ul>
        {items.map(([t, d]) => (
          <li key={t}><b>{t}</b> — {d}</li>
        ))}
      </ul>
      <p className="note">
        구조적 시한장치: 닷컴의 광섬유는 20년을 갔지만 <b>GPU는 4~6년이면 소진</b>됩니다.
        "언젠가 수익화"가 허용되는 시간이 짧고, 감가상각 연장은 그 시계를 억지로 늦추는 행위로 읽힙니다.
      </p>
    </section>
  )
}

function AIMethod() {
  return (
    <section className="card method">
      <h2>🤖 이 계기판이 말할 수 있는 것 / 없는 것</h2>
      <ul>
        <li><b>말할 수 있는 것</b> — 지금 반도체 밸류체인이 자국 시장 대비 얼마나 쏠려 있고, 그 쏠림이 식는 중인지 달아오르는 중인지.</li>
        <li><b>말할 수 없는 것</b> — 쏠림이 언제 해소될지. 실물 선행지표 후보(한국 수출·자본재 수주·재고·반도체 PPI)를
          과거 반도체 사이클 고점 9개에 대해 검증한 결과 <b>오경보율 70~82%로, 아무 신호 없는 기준선(71%)을 하나도 넘지 못했어요.</b></li>
        <li><b>그래서</b> — 이 탭엔 예측 점수가 없습니다. 상태 기술(위 표·차트) + 분기 문서 체크리스트가 전부입니다.</li>
      </ul>
      <p className="note">
        참고: 과거 사이클에서 SOX가 고점 후 12개월 내 -25% 이상 빠질 확률은 <b>29%</b>였습니다 —
        원래 변동성이 큰 지수라, 쏠림이 높다는 사실만으로 하락을 단정할 수 없어요.
      </p>
    </section>
  )
}

// stock_meta 전체를 한 번 받아 두 탭이 공유한다(500종목 = 1페이지 남짓).
function useStockMeta() {
  const [meta, setMeta] = useState(null)
  const [state, setState] = useState('loading')
  useEffect(() => {
    let alive = true
    ;(async () => {
      try {
        let all = [], from = 0
        for (;;) {
          const { data, error } = await supabase.from('stock_meta').select('*')
            .order('marcap', { ascending: false }).order('code').range(from, from + 999)
          if (error) throw error
          all = all.concat(data || [])
          if (!data || data.length < 1000) break
          from += 1000
        }
        if (!alive) return
        if (!all.length) { setState('empty'); return }
        setMeta(all); setState('ok')
      } catch (e) {
        if (!alive) return
        const msg = `${e?.message || ''} ${e?.code || ''}`
        setState(/exist|find the table|PGRST205|42P01/i.test(msg) ? 'empty' : 'error')
      }
    })()
    return () => { alive = false }
  }, [])
  return { meta, state }
}

// '언제 기준 숫자인가' — 수집 시각이 아니라 재무 기준 분기가 신선도의 척도다.
// 주가는 주 1회 갱신되지만 재무는 분기마다만 바뀌고 공시까지 45일이 더 걸린다.
function FiscalNote({ meta, codes = null }) {
  const rows = codes ? meta.filter((s) => codes.includes(s.code)) : meta
  const cnt = {}
  let none = 0
  for (const s of rows) {
    if (!s.fiscal_q) none++
    else cnt[s.fiscal_q] = (cnt[s.fiscal_q] || 0) + 1
  }
  const sorted = Object.entries(cnt).sort((a, b) => b[1] - a[1])
  if (!sorted.length) {
    return <p className="note fiscal">📅 재무 기준일 정보가 아직 없어요 — screener.py 재실행이 필요합니다.</p>
  }
  const [top, n] = sorted[0]
  // 다수 분기보다 '최신'인 종목과 '이전'인 종목을 갈라 센다.
  // 이걸 합쳐 "더 오래된"이라고 쓰면 2분기를 먼저 낸 기업(현대차 등)이 낡은 것처럼 읽힌다.
  const newer = sorted.filter(([q]) => q > top).reduce((a, [, c]) => a + c, 0)
  const older = sorted.filter(([q]) => q < top).reduce((a, [, c]) => a + c, 0)
  return (
    <p className="note fiscal">
      📅 <b>재무 기준일을 종목마다 표시</b>했어요. 가장 많은 건 <b>{top} 분기</b>({n}종목)
      {newer > 0 && <> · <span className="fq fresh">더 최신</span> {newer}종목(2분기 실적을 먼저 낸 기업)</>}
      {older > 0 && <> · <span className="fq stale">더 이전</span> {older}종목</>}
      {none > 0 && <> · <span className="fq stale">기준일 미상</span> {none}종목(야후가 안 줌)</>}
      <br />
      재무 숫자는 <b>분기에 한 번</b>만 바뀌고 <b>분기말 +45일 공시 → 반영</b>이라 늘 2~4개월 뒤처집니다.
      주가·시가총액은 주 1회(토요일) 갱신돼요.
    </p>
  )
}

function StockGate({ state, children }) {
  if (state === 'loading') return <div className="col-msg">불러오는 중…</div>
  if (state === 'error') return <div className="col-msg">데이터를 불러오지 못했어요</div>
  if (state === 'empty') {
    return (
      <div className="col-msg soon">🚧<br /><b>데이터 준비 중</b><br />
        <span>stock_meta 테이블 생성 + screener.py 실행 필요</span></div>
    )
  }
  return children
}

// ── A. 스크리너 ──
const SCR_PRESETS = [
  { name: '전체', f: () => true },
  { name: '저PER·흑자', f: (s) => s.per > 0 && s.per < 12 },
  { name: '저PBR', f: (s) => s.pbr > 0 && s.pbr < 1 },
  { name: '고ROE', f: (s) => s.roe > 0.15 },
  { name: '저부채', f: (s) => s.debt_to_equity != null && s.debt_to_equity < 50 },
  { name: '고성장', f: (s) => s.rev_growth > 0.2 },
  { name: '배당', f: (s) => s.div_yield > 2 },
]

function ScreenerSection() {
  const { meta, state } = useStockMeta()
  const [preset, setPreset] = useState('전체')
  const [market, setMarket] = useState('전체')
  const [sort, setSort] = useState({ key: 'marcap', asc: false })
  const [q, setQ] = useState('')

  const rows = useMemo(() => {
    if (!meta) return []
    const pf = SCR_PRESETS.find((p) => p.name === preset).f
    const k = q.trim().toLowerCase()     // 'sfa'로 쳐도 'SFA반도체'가 걸리게
    const out = meta.filter((s) => (market === '전체' || s.market === market)
      && (!k || s.name?.toLowerCase().includes(k) || s.code.includes(k)) && pf(s))
    return out.sort((a, b) => {
      const x = a[sort.key], y = b[sort.key]
      if (x == null) return 1                 // 결측은 항상 뒤로 — 정렬 방향과 무관하게
      if (y == null) return -1
      return sort.asc ? x - y : y - x
    })
  }, [meta, preset, market, sort, q])

  // 다수 종목의 재무 기준 분기 — 이것과 다른 종목만 행에 따로 표시해 눈에 띄게 한다
  const topQ = useMemo(() => {
    const c = {}
    for (const s of meta || []) if (s.fiscal_q) c[s.fiscal_q] = (c[s.fiscal_q] || 0) + 1
    return Object.entries(c).sort((a, b) => b[1] - a[1])[0]?.[0] || null
  }, [meta])
  const click = (key) => setSort((s) => ({ key, asc: s.key === key ? !s.asc : false }))
  return (
    <>
      <header>
        <h1>종목 스크리너</h1>
        <p className="lead">
          시가총액 상위 종목을 <b>재무 지표로 걸러</b> 봅니다.
          <b> 매수 추천이 아니라 "이런 특성을 가진 종목 목록"</b>이에요 — 아래 한계를 꼭 같이 읽어주세요.
        </p>
      </header>
      <StockGate state={state}>
        <section className="card">
          <div className="seg">
            {SCR_PRESETS.map((p) => (
              <button key={p.name} className={preset === p.name ? 'on' : ''}
                onClick={() => setPreset(p.name)}>{p.name}</button>
            ))}
          </div>
          <div className="seg">
            {['전체', 'KOSPI', 'KOSDAQ'].map((m) => (
              <button key={m} className={market === m ? 'on' : ''} onClick={() => setMarket(m)}>{m}</button>
            ))}
            <input className="scr-q" placeholder="종목명·코드 검색"
              value={q} onChange={(e) => setQ(e.target.value)} />
          </div>
          <FiscalNote meta={meta} />
          <p className="note">{rows.length}종목 · 열 제목을 누르면 정렬돼요 (결측값은 항상 아래로)</p>
          <div className="scr-wrap">
            <table className="stats scr">
              <thead>
                <tr>
                  <th onClick={() => click('marcap')}>종목 {sort.key === 'marcap' ? (sort.asc ? '▲' : '▼') : ''}</th>
                  {FIN_COLS.map((c) => (
                    <th key={c.key} onClick={() => click(c.key)} title={c.hint}>
                      {c.name} {sort.key === c.key ? (sort.asc ? '▲' : '▼') : ''}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {rows.slice(0, 120).map((s) => (
                  <tr key={s.code}>
                    <td className="scr-name">
                      <b>{s.name}</b>
                      <span>{s.code} · {s.market} · {won(s.marcap)}
                        {/* 모든 행에 기준일을 적는다 — '뱃지 없음 = 다수 날짜'는 화면만 봐선 알 수 없다.
                            색으로 구분: 다수와 같으면 무채색, 더 최신이면 초록, 더 이전·미상이면 노랑. */}
                        <em className={!s.fiscal_q || (topQ && s.fiscal_q < topQ) ? 'stale'
                          : topQ && s.fiscal_q > topQ ? 'fresh' : 'same'}>
                          {s.fiscal_q ? `재무 ${s.fiscal_q}` : '재무 기준일 없음'}
                        </em>
                      </span>
                    </td>
                    {FIN_COLS.map((c) => (
                      <td key={c.key}>{s[c.key] == null ? '—' : c.fmt(s[c.key])}</td>
                    ))}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          {rows.length > 120 && <p className="note">상위 120종목만 표시 중 — 필터나 검색으로 좁혀보세요.</p>}
          <p className="note owarn-inline">{STOCK_CAVEAT}</p>
        </section>
      </StockGate>
    </>
  )
}

// ── B. 포트폴리오 구성·진단 ──
const PF_LS_KEY = 'stocklab.pf.v1'
function loadPf() {
  try { return JSON.parse(localStorage.getItem(PF_LS_KEY)) || [] } catch { return [] }
}

function PortfolioSection() {
  const { meta, state } = useStockMeta()
  const [items, setItems] = useState(loadPf)     // [{code, w}]
  const [q, setQ] = useState('')
  const [prices, setPrices] = useState(null)

  useEffect(() => {
    try { localStorage.setItem(PF_LS_KEY, JSON.stringify(items)) } catch { /* 저장 불가 */ }
  }, [items])

  // 선택 종목 + 벤치마크의 월말 종가만 받는다(전 종목이면 프론트가 못 버틴다)
  useEffect(() => {
    let alive = true
    const codes = items.map((i) => i.code)
    if (!codes.length) { setPrices(null); return }
    ;(async () => {
      try {
        let all = [], from = 0
        const want = [...codes, 'KOSPI']
        for (;;) {
          const { data, error } = await supabase.from('stock_monthly').select('code,dt,close')
            .in('code', want).order('dt').order('code').range(from, from + 999)
          if (error) throw error
          all = all.concat(data || [])
          if (!data || data.length < 1000) break
          from += 1000
        }
        if (alive) setPrices(all)
      } catch { if (alive) setPrices([]) }
    })()
    return () => { alive = false }
  }, [items])

  const byCode = useMemo(() => Object.fromEntries((meta || []).map((s) => [s.code, s])), [meta])
  const total = items.reduce((a, i) => a + (i.w || 0), 0)
  const found = items.map((i) => ({ ...i, s: byCode[i.code] })).filter((i) => i.s)
  // 수집 대상(시총 상위 N)에서 빠진 종목은 조용히 없애지 말고 드러낸다 — 담아둔 게 사라지면 혼란스럽다
  const missing = items.filter((i) => !byCode[i.code])
  const k = q.trim().toLowerCase()      // 'sfa'로 쳐도 'SFA넥셀'이 걸리게
  const hits = k && meta
    ? meta.filter((s) => (s.name?.toLowerCase().includes(k) || s.code.includes(k))
        && !items.some((i) => i.code === s.code)).slice(0, 6)
    : []

  return (
    <>
      <header>
        <h1>포트폴리오</h1>
        <p className="lead">
          종목과 비중을 넣으면 <b>지금 어떤 상태인지</b> 진단하고, 그 조합이 <b>과거에 어땠는지</b> 되짚어 봅니다.
          <b> 앞으로의 수익률은 말하지 않습니다</b> — 오늘 여러 번 확인했듯 그건 이 데이터로 알 수 없어요.
        </p>
      </header>
      <StockGate state={state}>
        <section className="card">
          <h2>🧺 종목 구성</h2>
          <div className="pf-add">
            <input placeholder="종목명 또는 코드로 검색해 추가"
              value={q} onChange={(e) => setQ(e.target.value)} />
            {hits.length > 0 && (
              <div className="pf-hits">
                {hits.map((s) => (
                  <button key={s.code} onClick={() => {
                    setItems([...items, { code: s.code, w: 10 }]); setQ('')
                  }}>{s.name} <span>{s.code}</span></button>
                ))}
              </div>
            )}
          </div>
          {found.length === 0 && <p className="note">아직 담은 종목이 없어요. 위에서 검색해 추가해보세요.</p>}
          {found.map((it) => (
            <div key={it.code} className="wrow">
              <span className="wname" style={{ width: 108 }}>{it.s.name}</span>
              <input type="range" min="0" max="100" step="1" value={it.w}
                onChange={(e) => setItems(items.map((x) => x.code === it.code
                  ? { ...x, w: +e.target.value } : x))} />
              <input type="number" className="wnum" min="0" max="100" value={it.w}
                onChange={(e) => setItems(items.map((x) => x.code === it.code
                  ? { ...x, w: Math.max(0, Math.min(100, Math.round(+e.target.value) || 0)) } : x))} />
              <span className="wpct">{total ? Math.round((it.w / total) * 100) : 0}%</span>
              <button className="wdir" onClick={() => setItems(items.filter((x) => x.code !== it.code))}>삭제</button>
            </div>
          ))}
          {missing.length > 0 && (
            <div className="owarn">
              <b>수집 대상에서 빠진 종목 {missing.length}개</b> — {missing.map((m) => m.code).join(', ')}
              <br />시가총액 상위 500위 밖으로 밀려났거나 상장에 변동이 있는 종목입니다.
              재무·주가를 못 받아 <b>아래 진단·시뮬레이션에서 제외</b>됐어요.
              {' '}필요하면 <code>screener.yml</code>의 <code>SCREENER_ALWAYS</code>에 코드를 넣어 강제 포함할 수 있습니다.
              {missing.map((m) => (
                <button key={m.code} className="wdir" style={{ marginLeft: 8 }}
                  onClick={() => setItems(items.filter((x) => x.code !== m.code))}>{m.code} 삭제</button>
              ))}
            </div>
          )}
          {found.length > 0 && (
            <p className="note">
              비중은 <b>합이 100%가 되도록 자동 환산</b>되니 아무 값이나 넣어도 됩니다.
              구성은 이 브라우저에 저장돼 다음에도 그대로 열려요.
            </p>
          )}
        </section>
        {found.length > 0 && <PfDiagnosis items={found} total={total} />}
        {found.length > 0 && <PfSimulation items={found} total={total} prices={prices} />}
        {found.length > 0 && (
          <section className="card method">
            <h2>🧺 이 진단이 말할 수 있는 것 / 없는 것</h2>
            <ul>
              <li><b>말할 수 있는 것</b> — 지금 이 조합이 얼마나 한쪽에 쏠려 있는지, 재무적으로 어떤 종목들인지,
                그리고 <b>이 비중을 과거에 유지했다면</b> 수익률·낙폭이 어땠을지.</li>
              <li><b>말할 수 없는 것</b> — 앞으로의 수익률. 과거 시뮬레이션은 <b>지금 살아남은 종목</b>으로만
                계산되므로 실제보다 좋게 나옵니다(생존편향).</li>
            </ul>
            <p className="note owarn-inline">{STOCK_CAVEAT}</p>
          </section>
        )}
      </StockGate>
    </>
  )
}

function PfDiagnosis({ items, total }) {
  const wOf = (it) => (total ? it.w / total : 0)
  // 가중 평균은 값이 있는 종목끼리만 — 결측을 0으로 치면 지표가 실제보다 좋아 보인다
  const wavg = (key) => {
    let num = 0, den = 0
    for (const it of items) {
      const v = it.s[key]
      if (v == null) continue
      num += v * wOf(it); den += wOf(it)
    }
    return den > 0 ? { v: num / den, cover: den } : null
  }
  const sorted = [...items].sort((a, b) => b.w - a.w)
  const top3 = sorted.slice(0, 3).reduce((a, i) => a + wOf(i), 0) * 100
  const hhi = items.reduce((a, i) => a + Math.pow(wOf(i) * 100, 2), 0)   // 허핀달 집중도
  const eff = hhi > 0 ? 10000 / hhi : 0                                  // 실효 종목 수
  const sectors = {}
  for (const it of items) {
    const k = it.s.sector || '미분류'
    sectors[k] = (sectors[k] || 0) + wOf(it) * 100
  }
  const topSector = Object.entries(sectors).sort((a, b) => b[1] - a[1])[0]
  const risky = items.filter((i) => i.s.debt_to_equity > 200 || (i.s.op_margin != null && i.s.op_margin < 0))

  const cells = [
    ['종목 수', items.length + '개', `실효 ${eff.toFixed(1)}개`],
    ['상위 3종목', top3.toFixed(0) + '%', top3 > 70 ? '매우 집중' : top3 > 50 ? '집중' : '분산'],
    ['최대 섹터', topSector ? `${topSector[1].toFixed(0)}%` : '—', topSector ? topSector[0] : ''],
  ]
  return (
    <section className="card outlook">
      <h2>📋 현재 상태 진단</h2>
      <div className="ocells">
        {cells.map(([label, big, sub]) => (
          <div key={label}><span>{label}</span><b>{big}</b>
            <span style={{ marginTop: 4 }}>{sub}</span></div>
        ))}
      </div>
      <FiscalNote meta={items.map((i) => i.s)} />
      <table className="stats">
        <thead><tr><th>가중평균 지표</th><th>내 포트폴리오</th><th>산출 커버리지</th></tr></thead>
        <tbody>
          {FIN_COLS.map((c) => {
            const r = wavg(c.key)
            return (
              <tr key={c.key}>
                <td title={c.hint}>{c.name}</td>
                <td style={{ fontWeight: 700 }}>{r ? c.fmt(r.v) : '—'}</td>
                <td style={{ color: '#94a3b8' }}>{r ? `비중의 ${(r.cover * 100).toFixed(0)}%` : '자료 없음'}</td>
              </tr>
            )
          })}
        </tbody>
      </table>
      {risky.length > 0 && (
        <div className="owarn">
          <b>재무 부담이 큰 종목 {risky.length}개</b> — {risky.map((r) => r.s.name).join(', ')}
          <br />부채비율 200% 초과이거나 영업이익이 적자입니다. 사업 내용을 따로 확인해보세요.
        </div>
      )}
      <p className="note">
        <b>실효 종목 수</b>는 비중까지 반영한 분산 정도예요 — 10종목을 담아도 하나에 80%면 실효는 1.5개에 가깝습니다.
        <b> 커버리지</b>는 그 지표를 계산할 수 있었던 비중의 몫이고요(적자 기업은 PER이 없는 식).
      </p>
    </section>
  )
}

function PfSimulation({ items, total, prices }) {
  const [years, setYears] = useState(3)
  const sim = useMemo(() => {
    if (!prices || !prices.length) return null
    const byCode = {}
    for (const r of prices) (byCode[r.code] ||= {})[r.dt] = r.close
    const codes = items.map((i) => i.code)
    // 모든 보유 종목에 값이 있는 달만 사용 — 상장 이전 구간을 0으로 치면 안 된다
    const dts = Object.keys(byCode['KOSPI'] || {}).sort()
      .filter((d) => codes.every((c) => byCode[c]?.[d] != null))
    const use = dts.slice(-(years * 12 + 1))
    if (use.length < 13) return { thin: true, n: use.length }
    const w = Object.fromEntries(items.map((i) => [i.code, total ? i.w / total : 0]))
    let pv = 100, bv = 100, peak = 100, mdd = 0
    const series = [{ dt: use[0], pf: 100, bm: 100 }]
    const rets = []
    for (let k = 1; k < use.length; k++) {
      let r = 0                       // 매월 비중 재조정 가정(가장 단순한 기준선)
      for (const c of codes) r += w[c] * (byCode[c][use[k]] / byCode[c][use[k - 1]] - 1)
      rets.push(r)
      pv *= 1 + r
      bv *= byCode['KOSPI'][use[k]] / byCode['KOSPI'][use[k - 1]]
      peak = Math.max(peak, pv)
      mdd = Math.min(mdd, pv / peak - 1)
      series.push({ dt: use[k], pf: +pv.toFixed(1), bm: +bv.toFixed(1) })
    }
    const m = rets.reduce((a, b) => a + b, 0) / rets.length
    const sd = Math.sqrt(rets.reduce((a, b) => a + (b - m) ** 2, 0) / rets.length)
    return { series, ret: pv - 100, bench: bv - 100, mdd: mdd * 100, vol: sd * Math.sqrt(12) * 100, n: rets.length }
  }, [prices, items, total, years])

  if (!prices) return <section className="card"><h2>📈 과거 시뮬레이션</h2><p className="note">가격 불러오는 중…</p></section>
  if (!sim || sim.thin) {
    return (
      <section className="card">
        <h2>📈 과거 시뮬레이션</h2>
        <p className="note">
          모든 보유 종목에 가격이 함께 있는 달이 {sim?.n ?? 0}개월뿐이라 계산할 수 없어요.
          상장한 지 얼마 안 된 종목이 섞여 있으면 이렇게 됩니다.
        </p>
      </section>
    )
  }
  const beat = sim.ret - sim.bench
  return (
    <section className="card outlook">
      <h2>📈 과거 시뮬레이션 <span style={{ fontWeight: 400, color: '#94a3b8' }}>(지금 비중을 그때부터 유지했다면)</span></h2>
      <div className="seg">
        {[1, 3, 5, 10].map((y) => (
          <button key={y} className={years === y ? 'on' : ''} onClick={() => setYears(y)}>{y}년</button>
        ))}
      </div>
      <div className="ocells">
        <div><span>누적 수익률</span><b style={{ color: sim.ret > 0 ? '#1e8449' : '#c0392b' }}>
          {sim.ret > 0 ? '+' : ''}{sim.ret.toFixed(0)}%</b></div>
        <div><span>코스피 대비</span><b style={{ color: beat > 0 ? '#1e8449' : '#c0392b' }}>
          {beat > 0 ? '+' : ''}{beat.toFixed(0)}%p</b></div>
        <div><span>최대 낙폭</span><b style={{ color: '#c0392b' }}>{sim.mdd.toFixed(0)}%</b></div>
        <div><span>연 변동성</span><b>{sim.vol.toFixed(0)}%</b></div>
      </div>
      <ResponsiveContainer width="100%" height={230}>
        <LineChart data={sim.series} margin={{ top: 12, right: 8, left: -20, bottom: 0 }}>
          <CartesianGrid strokeDasharray="3 3" opacity={0.15} />
          <XAxis dataKey="dt" tick={{ fontSize: 10 }} minTickGap={44} />
          <YAxis domain={['auto', 'auto']} tick={{ fontSize: 10 }} width={42} />
          <Tooltip formatter={(v, n) => [v.toFixed(1), n]} wrapperStyle={{ outline: 'none' }} />
          <ReferenceLine y={100} stroke="#94a3b8" strokeDasharray="3 3" />
          <Line type="monotone" dataKey="bm" name="코스피" stroke="#94a3b8" dot={false} strokeWidth={1.4} isAnimationActive={false} />
          <Line type="monotone" dataKey="pf" name="내 포트폴리오" stroke="#d97706" dot={false} strokeWidth={2.4} isAnimationActive={false} />
        </LineChart>
      </ResponsiveContainer>
      <div className="owarn">
        <b>이건 예측이 아니라 되짚기입니다.</b> 매월 지금 비중으로 재조정했다고 가정했고,
        세금·거래비용·배당을 넣지 않았습니다. 무엇보다 <b>지금 살아남은 종목</b>으로만 계산한 값이라
        실제 성적보다 좋게 나옵니다({sim.n}개월 기준).
      </div>
    </section>
  )
}

function Glossary() {
  const items = [
    ['공포 / 탐욕', '시장 참여자들의 심리. 공포=다들 팔고 싶어 함(가격↓), 탐욕=다들 사고 싶어 함(가격↑).'],
    ['S(t) 심리점수', '우리가 만든 0~100 점수. VIX·시장 흐름·참여 폭 등을 합쳐 계산해요.'],
    ['이후 20일', '그날로부터 거래일 20일(약 한 달) 뒤.'],
    ['승률', '그 상황에서 20일 뒤 "이익이었던" 날의 비율.'],
    ['역발상', '남들이 공포일 때 사고, 탐욕일 때 조심하는 접근.'],
  ]
  return (
    <section className="card glossary">
      <h2>📖 용어 & 읽는 법</h2>
      <dl>
        {items.map(([t, d]) => (
          <div key={t}><dt>{t}</dt><dd>{d}</dd></div>
        ))}
      </dl>
    </section>
  )
}

function Setup() {
  return (
    <div className="center setup">
      <h2>🔑 anon 키를 넣어주세요</h2>
      <p>
        <code>web/.env.local</code> 의 <code>VITE_SUPABASE_ANON_KEY</code> 를<br />
        Supabase → Settings → API 의 <b>anon</b> 키로 교체하고 저장하면<br />
        자동으로 화면이 켜집니다.
      </p>
    </div>
  )
}
