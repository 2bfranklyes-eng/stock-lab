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
  극단공포: '다들 겁에 질린 상태. 역사적으로는 반등이 잦았던 구간이에요.',
  공포: '시장이 움츠러든 분위기.',
  중립: '뚜렷한 쏠림 없이 평범한 상태.',
  탐욕: '시장이 달아오른 분위기.',
  극단탐욕: '과열 상태. 역사적으로는 조정이 뒤따르기도 했어요.',
}

const STAT_ORDER = ['극단공포', '공포', '중립', '탐욕', '극단탐욕', '전체']

export default function App() {
  const [series, setSeries] = useState([])
  const [latest, setLatest] = useState(null)
  const [stats, setStats] = useState([])
  const [err, setErr] = useState(null)
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    if (!hasKey) { setLoading(false); return }
    ;(async () => {
      try {
        const { data, error } = await supabase
          .from('sentiment_daily')
          .select('dt,s_score,band')
          .eq('market', 'US')
          .order('dt', { ascending: false })
          .limit(800)
        if (error) throw error
        const rows = data.slice().reverse()
        setSeries(rows)
        setLatest(rows[rows.length - 1])
      } catch (e) {
        setErr(e.message || String(e))
      } finally {
        setLoading(false)
      }
      try {
        const { data: bt } = await supabase.from('backtest_stats').select('*').eq('market', 'US')
        if (bt) setStats(bt)
      } catch { /* 아직 없음 */ }
    })()
  }, [])

  if (!hasKey) return <Setup />
  if (loading) return <div className="center">불러오는 중…</div>
  if (err) return <div className="center err">에러: {err}</div>
  if (!latest) return <div className="center">데이터 없음 — sentiment.py 를 실행했나요?</div>

  const b = bandOf(latest.s_score)
  return (
    <div className="wrap">
      <header>
        <h1>시장 심리<span className="mkt">US</span></h1>
        <p className="date">{latest.dt} 기준</p>
      </header>

      <p className="lead">
        미국 주식시장이 지금 <b>겁먹었는지(공포)</b> 아니면 <b>들떴는지(탐욕)</b> 를
        하나의 점수(0~100)로 보여줍니다. 회사 실적이 아니라 <b>시장의 분위기(심리)</b> 를 재요.
      </p>

      <section className="gauge" style={{ '--c': b.color }}>
        <div className="score">{Math.round(latest.s_score)}</div>
        <div className="band">{b.name}</div>
        <div className="scale"><span>0 · 공포</span><span>탐욕 · 100</span></div>
        <div className="bar"><div className="fill" style={{ width: `${latest.s_score}%` }} /></div>
        <p className="gauge-note">
          {BAND_DESC[b.name]}<br />
          숫자가 <b>낮을수록 공포</b>, <b>높을수록 탐욕</b>이에요. 20 이하·80 이상(극단)일 때 특히 신호가 강해요.
          <br /><span className="warn">※ '지금 사라/팔라'가 아니라 분위기 측정입니다.</span>
        </p>
      </section>

      <section className="card">
        <h2>S(t) 심리점수 추이 (최근 약 3년)</h2>
        <p className="cap">
          주황선이 심리점수예요. <b>아래로 갈수록 공포</b>(주로 폭락 때), <b>위로 갈수록 탐욕</b>(과열).
          파란 점선(20)·빨간 점선(80)은 극단 경계선.
        </p>
        <ResponsiveContainer width="100%" height={280}>
          <LineChart data={series} margin={{ top: 10, right: 12, left: -18, bottom: 0 }}>
            <CartesianGrid strokeDasharray="3 3" opacity={0.15} />
            <XAxis dataKey="dt" tick={{ fontSize: 11 }} minTickGap={64} />
            <YAxis domain={[0, 100]} tick={{ fontSize: 11 }} />
            <Tooltip />
            <ReferenceLine y={80} stroke="#c0392b" strokeDasharray="4 4" />
            <ReferenceLine y={20} stroke="#2471a3" strokeDasharray="4 4" />
            <Line type="monotone" dataKey="s_score" stroke="#d97706" dot={false} strokeWidth={1.6} />
          </LineChart>
        </ResponsiveContainer>
      </section>

      <StatsCard stats={stats} />
      <Glossary />
    </div>
  )
}

function StatsCard({ stats }) {
  if (!stats || stats.length === 0) return null
  const byBand = Object.fromEntries(stats.map((s) => [s.band, s]))
  return (
    <section className="card">
      <h2>밴드별 '이후 20일' 수익률 — 심리가 반전을 예고할까?</h2>
      <p className="cap">
        "그때 그 심리 상태에서 샀다면 20일(약 한 달) 뒤 어땠나"를 과거 데이터로 계산한 표예요.
      </p>
      <table className="stats">
        <thead>
          <tr><th>심리 밴드</th><th>일수</th><th>이후 20일</th><th>승률</th></tr>
        </thead>
        <tbody>
          {STAT_ORDER.map((bd) => {
            const s = byBand[bd]
            if (!s) return null
            const v = s.fwd20
            const color = v > 2 ? '#1e8449' : v < 0 ? '#c0392b' : 'inherit'
            return (
              <tr key={bd} className={bd === '전체' ? 'base' : ''}>
                <td>{bd}</td>
                <td>{s.n}</td>
                <td style={{ color, fontWeight: v > 2 || v < 0 ? 700 : 400 }}>
                  {v > 0 ? '+' : ''}{v}%
                </td>
                <td>{s.hit20}%</td>
              </tr>
            )
          })}
        </tbody>
      </table>
      <p className="note">
        <b>읽는 법</b> — '극단공포 +5.44%'는 시장이 극도로 겁먹은 날 샀으면 20일 뒤 평균 +5.44%,
        그중 84.9%가 이익이었다는 뜻. 반대로 '극단탐욕'은 밋밋했어요.
        즉 <b>공포에 사고 탐욕에 조심</b>하는 게 통했다는 신호. (단 표본이 적어 참고용)
      </p>
    </section>
  )
}

function Glossary() {
  const items = [
    ['공포 / 탐욕', '시장 참여자들의 심리. 공포=다들 팔고 싶어 함(가격↓), 탐욕=다들 사고 싶어 함(가격↑).'],
    ['S(t) 심리점수', '우리가 만든 0~100 점수. VIX(공포지수)·시장 흐름·참여 폭 등을 합쳐 계산해요.'],
    ['이후 20일', '그날로부터 거래일 20일(약 한 달) 뒤.'],
    ['승률', '그 상황에서 20일 뒤 "이익이었던" 날의 비율.'],
    ['역발상', '남들이 공포일 때 사고, 탐욕일 때 조심하는 접근. 이 데이터가 그게 통했음을 보여줘요.'],
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
