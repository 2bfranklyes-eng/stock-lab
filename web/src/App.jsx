import { useEffect, useState } from 'react'
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
const I_SERIES = [
  { key: 'i_score', name: '물가(종합)', color: '#d97706', width: 2.2 },
  { key: 'c_be', name: '기대인플레', color: '#2a78d6', width: 1.3 },
  { key: 'c_energy', name: '에너지', color: '#008300', width: 1.3 },
  { key: 'c_comm', name: '원자재', color: '#d55181', width: 1.3 },
  { key: 'c_metal', name: '산업금속', color: '#4a3aa7', width: 1.3 },
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
  const comp = market === 'US'
    ? [['c1', '연준자산'], ['c2', '재무부계정'], ['c3', '역레포']]
    : [['c1', 'M2증가율'], ['c2', '외국인'], ['c3', '개인']]
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
  <>실탄이 <b>풍부</b>할 때 순풍인지, <b>고갈</b>일 때 바닥인지. (실탄은 느린 배경 지표라 참고용)</>
)
// 실탄 차트 구간 프리셋 — 미국=주간·한국=월간이라 슬라이스 '행 수'가 다름
const F_RANGES_US = [{ label: '1년', days: 52 }, { label: '3년', days: 156 }, { label: '5년', days: 260 }, { label: '전체', days: Infinity }]
const F_RANGES_KR = [{ label: '2년', days: 24 }, { label: '5년', days: 60 }, { label: '10년', days: 120 }, { label: '전체', days: Infinity }]

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
}
const shortDate = (dt) => { const [y, m] = dt.split('-'); return `${y.slice(2)}.${+m}` }

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
]

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
function ChartTooltip({ active, payload, label, config, market, mainKey }) {
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
            <span className="tip-val">{rawStr && <b>{rawStr}</b>}<em>{Math.round(e.value)}</em></span>
          </div>
        )
      })}
      {anyRaw && <div className="tip-foot">굵은 값 = 실제 수치 · 옅은 값 = 점수(0~100)</div>}
    </div>
  )
}

// 공용 추이 차트: 종합선 + 성분선 + 구간선택 + 이벤트선 + 커스텀 범례.
//   config[0] = 종합(범례 맨 앞, z축 맨 위). mainKey = 종합 dataKey.
function TrendChart({ series, config, market, title, refLines, note, mainKey, ranges = RANGES, defaultRange = 756 }) {
  const [range, setRange] = useState(defaultRange)   // 기본 3년(또는 지정값)
  const [hidden, setHidden] = useState(() => new Set())
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
      <ResponsiveContainer width="100%" height={248}>
        <LineChart data={shown} margin={{ top: 18, right: 8, left: -22, bottom: 0 }}>
          <CartesianGrid strokeDasharray="3 3" opacity={0.15} />
          <XAxis dataKey="dt" tick={{ fontSize: 10 }} minTickGap={48} />
          <YAxis domain={[0, 100]} tick={{ fontSize: 10 }} />
          <Tooltip content={(props) => <ChartTooltip {...props} config={config} market={market} mainKey={mainKey} />}
            wrapperStyle={{ outline: 'none' }} />
          {refLines.map((r) => (
            <ReferenceLine key={r.y} y={r.y} stroke={r.color} strokeDasharray="4 4" />
          ))}
          {events.map((e) => (
            <ReferenceLine key={e.dt + e.label} x={e.x} stroke="#b0b4ba" strokeDasharray="2 3"
              label={{ value: e.emoji, position: 'top', fontSize: 11 }} />
          ))}
          {drawOrder.map((s) => (
            <Line key={s.key} type="monotone" dataKey={s.key} name={s.name}
              stroke={s.color} dot={false} strokeWidth={s.width}
              strokeOpacity={s.key === mainKey ? 1 : 0.85}
              hide={hidden.has(s.key)} isAnimationActive={false} />
          ))}
        </LineChart>
      </ResponsiveContainer>
      <div className="chart-legend">
        {config.map((s) => (
          <button key={s.key} className={hidden.has(s.key) ? 'off' : ''} onClick={() => toggle(s.key)}>
            <span className="swatch" style={{ background: s.color, height: s.key === mainKey ? 4 : 2 }} />
            {s.name}
          </button>
        ))}
      </div>
      <p className="note">{note}</p>
      {events.length > 0 && (
        <p className="note events">
          <b>회색 세로선 = 굵직한 사건:</b>{' '}
          {events.map((e) => (
            <span key={e.dt + e.label} style={{ marginRight: 10, whiteSpace: 'nowrap' }}>
              {e.emoji} {e.label}<span style={{ color: '#9aa0a6' }}> ({shortDate(e.dt)})</span>
            </span>
          ))}
        </p>
      )}
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

function StatsCard({ stats, order = STAT_ORDER, note = SENT_STATS_NOTE }) {
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
        <thead><tr><th>밴드</th><th>일수</th><th>이후{h}일</th><th>승률</th></tr></thead>
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

// ── 물가 섹션 (유동성과 동일 구조, 원자재료 수치 카드는 생략) ──
function InflationBody({ latest, series, stats, market }) {
  const b = infBandOf(latest.i_score)
  return (
    <>
      <p className="col-date">{latest.dt} 기준</p>
      <Gauge value={latest.i_score} band={b} lowLabel="저물가" highLabel="고물가" desc={I_BAND_DESC[b.name]} />
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
            .select('dt,i_score,band,c_be,c_energy,c_comm,c_metal')
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
    ['📈 기대인플레', '시장이 반영한 물가 — 미국 물가연동채(TIP)÷국채(IEF), 한국 원/달러(수입물가)'],
    ['🛢️ 에너지', '유가가 오를수록 물가↑ (USO)'],
    ['🌾 원자재', '원자재 바스켓이 오를수록 물가↑ (DBC)'],
    ['🔩 산업금속', '구리 등 실물 수요가 강할수록 물가↑ (DBB)'],
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
      <TrendChart
        series={series} config={fSeries(market)} market={market} mainKey="f_score"
        title="F(t) 실탄 추이"
        ranges={market === 'US' ? F_RANGES_US : F_RANGES_KR} defaultRange={Infinity}
        refLines={[{ y: 80, color: '#1e8449' }, { y: 20, color: '#c0392b' }]}
        note={<>굵은 <b style={{ color: '#d97706' }}>주황</b>이 종합 실탄, 얇은 3선은 성분(각 0~100, 높을수록 유입). {monthly && <b>한국은 월간 데이터예요.</b>}</>}
      />
      <StatsCard stats={stats} order={F_STAT_ORDER} note={FUEL_STATS_NOTE} />
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
          .select('dt,f_score,band,c1,c2,c3,raw1,raw2,freq')
          .eq('market', market).order('dt', { ascending: true })
        if (error) throw error
        if (!alive) return
        if (!data || data.length === 0) { setState('empty'); return }
        setSeries(data); setLatest(data[data.length - 1]); setState('ok')
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
        <li><b>🇰🇷 한국 (월간)</b> — M2 증가율 + 외국인 순매수 + 개인 순매수. 돈의 양 + 실제 수급.</li>
      </ul>
      <p className="note">
        각 재료를 <b>과거 대비 몇 %ile</b>인지로 0~100 환산 → 평균 → 평활.
        <b> ⚠️ 한국은 일간 예탁금·외국인 데이터 접근이 막혀 월간 ECOS(통화량·투자자 순매수)로 대체</b>해요 — 미국(주간)보다 느립니다.
      </p>
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
