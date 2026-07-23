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
// 그리기 순서: 성분 4개 먼저, 종합(SERIES[0])을 마지막에 → z축 맨 위
const DRAW_ORDER = [...SERIES.slice(1), SERIES[0]]

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

export default function App() {
  if (!hasKey) return <Setup />
  return (
    <div className="wrap">
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
    </div>
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

function MarketBody({ latest, series, stats, market }) {
  const b = bandOf(latest.s_score)
  // 표시 구간(기본 3년) — series 끝에서 N개만 잘라 보여줌.
  const [range, setRange] = useState(756)
  const shown = range === Infinity ? series : series.slice(-range)
  // 이 시장에 해당하고 '보이는 구간' 안에 드는 이벤트만 → 실제 거래일에 스냅
  const events = eventsFor(market, shown)
  // 범례 클릭으로 각 선 켜고/끄기. 기본은 전부 표시(요청대로 5개 선 다 보임).
  const [hidden, setHidden] = useState(() => new Set())
  const toggle = (k) => setHidden((h) => {
    const n = new Set(h)
    if (n.has(k)) n.delete(k); else n.add(k)
    return n
  })
  return (
    <>
      <p className="col-date">{latest.dt} 기준</p>

      <section className="gauge" style={{ '--c': b.color }}>
        <div className="score">{Math.round(latest.s_score)}</div>
        <div className="band">{b.name}</div>
        <div className="scale"><span>0 · 공포</span><span>탐욕 · 100</span></div>
        <div className="bar"><div className="fill" style={{ width: `${latest.s_score}%` }} /></div>
        <p className="gauge-note">{BAND_DESC[b.name]}</p>
      </section>

      <section className="card">
        <h2>S(t) 심리점수 추이</h2>
        <div className="seg">
          {RANGES.map((r) => (
            <button key={r.label} className={range === r.days ? 'on' : ''}
              onClick={() => setRange(r.days)}>{r.label}</button>
          ))}
        </div>
        <ResponsiveContainer width="100%" height={248}>
          <LineChart data={shown} margin={{ top: 18, right: 8, left: -22, bottom: 0 }}>
            <CartesianGrid strokeDasharray="3 3" opacity={0.15} />
            <XAxis dataKey="dt" tick={{ fontSize: 10 }} minTickGap={48} />
            <YAxis domain={[0, 100]} tick={{ fontSize: 10 }} />
            <Tooltip formatter={(v, name) => [Math.round(v), name]} />
            <ReferenceLine y={80} stroke="#c0392b" strokeDasharray="4 4" />
            <ReferenceLine y={20} stroke="#2471a3" strokeDasharray="4 4" />
            {events.map((e) => (
              <ReferenceLine
                key={e.dt + e.label} x={e.x} stroke="#b0b4ba" strokeDasharray="2 3"
                label={{ value: e.emoji, position: 'top', fontSize: 11 }}
              />
            ))}
            {DRAW_ORDER.map((s) => (
              <Line
                key={s.key} type="monotone" dataKey={s.key} name={s.name}
                stroke={s.color} dot={false} strokeWidth={s.width}
                strokeOpacity={s.key === 's_score' ? 1 : 0.85}
                hide={hidden.has(s.key)} isAnimationActive={false}
              />
            ))}
          </LineChart>
        </ResponsiveContainer>
        {/* 직접 만든 범례: SERIES 순서 그대로(종합이 맨 앞). 클릭하면 해당 선 켜고/끄기. */}
        <div className="chart-legend">
          {SERIES.map((s) => (
            <button key={s.key} className={hidden.has(s.key) ? 'off' : ''} onClick={() => toggle(s.key)}>
              <span className="swatch" style={{ background: s.color, height: s.key === 's_score' ? 4 : 2 }} />
              {s.name}
            </button>
          ))}
        </div>
        <p className="note">
          굵은 <b style={{ color: '#d97706' }}>주황</b>이 종합 심리점수, 얇은 4선은 그걸 이루는 성분(각 0~100,
          높을수록 탐욕 쪽). <b>범례를 누르면</b> 선을 켜고 끌 수 있어요.
        </p>
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

      <StatsCard stats={stats} />
    </>
  )
}

function StatsCard({ stats }) {
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
          {STAT_ORDER.map((bd) => {
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
      <p className="note">
        <b>극단공포</b> 뒤 반등이 뚜렷(역발상 엣지), <b>극단탐욕</b>은 밋밋. 20거래일 ≈ 1달. (표본 적어 참고용)
      </p>
    </section>
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
