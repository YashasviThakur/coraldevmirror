import { useEffect, useState } from 'react'
import { RefreshCw, Flame, Award, TrendingUp, CheckCircle, XCircle } from 'lucide-react'
import { RadialBarChart, RadialBar, Tooltip, ResponsiveContainer, BarChart, Bar, XAxis, YAxis, CartesianGrid } from 'recharts'
import PageShell from '../components/PageShell'
import LoadingSpinner from '../components/LoadingSpinner'
import StatCard from '../components/StatCard'
import { api, DSAData, getUserId } from '../api/client'

const DEMO: DSAData = {
  leetcode: {
    username: 'yashasvithakur2005',
    total_solved: 11,
    easy: 5,
    medium: 4,
    hard: 2,
    easy_total: 814,
    medium_total: 1715,
    hard_total: 741,
    streak: 2,
    acceptance_rate: 68.4,
    recent: [
      { title: 'Two Sum',               difficulty: 'Easy',   date: '2026-05-27' },
      { title: 'Best Time to Buy',      difficulty: 'Easy',   date: '2026-05-27' },
      { title: 'Valid Parentheses',     difficulty: 'Easy',   date: '2026-05-26' },
      { title: 'Longest Substring',     difficulty: 'Medium', date: '2026-05-25' },
      { title: 'Container With Water',  difficulty: 'Medium', date: '2026-05-24' },
    ],
  },
  codeforces: {
    handle: 'yashasvithakur2005',
    rating: 1200,
    max_rating: 1234,
    rank: 'Pupil',
    solved: 23,
    recent: [
      { problem: 'Theatre Square',  verdict: 'AC', rating: 1000, date: '2026-05-26' },
      { problem: 'Watermelon',      verdict: 'AC', rating: 800,  date: '2026-05-25' },
      { problem: 'Stones',          verdict: 'WA', rating: 1100, date: '2026-05-24' },
      { problem: 'Queue at School', verdict: 'AC', rating: 1200, date: '2026-05-23' },
      { problem: 'HQ9+',            verdict: 'AC', rating: 1000, date: '2026-05-22' },
    ],
  },
}

const diffColor: Record<string, string> = {
  Easy:   'text-dm-green',
  Medium: 'text-dm-amber',
  Hard:   'text-red-400',
}

const diffBg: Record<string, string> = {
  Easy:   'bg-dm-green/10 border-dm-green/30',
  Medium: 'bg-dm-amber/10 border-dm-amber/30',
  Hard:   'bg-red-500/10 border-red-400/30',
}

export default function DSAProgress() {
  const [data, setData] = useState<DSAData | null>(null)
  const [loading, setLoading] = useState(true)

  async function load() {
    setLoading(true)
    try {
      const userId = getUserId()
      const d = await api.dsa(userId ?? undefined)
      setData(d)
    } catch {
      setData(DEMO)
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => { load() }, [])

  const d = data ?? DEMO

  const easyTotal   = d.leetcode.easy_total   || 814
  const mediumTotal = d.leetcode.medium_total || 1715
  const hardTotal   = d.leetcode.hard_total   || 741
  const radialData = [
    { name: 'Hard',   value: (d.leetcode.hard   / hardTotal)   * 100, fill: '#EF4444' },
    { name: 'Medium', value: (d.leetcode.medium / mediumTotal) * 100, fill: '#F59E0B' },
    { name: 'Easy',   value: (d.leetcode.easy   / easyTotal)   * 100, fill: '#10B981' },
  ]

  const cfBarData = d.codeforces.recent.map(r => ({
    name: r.problem.slice(0, 10),
    rating: r.rating,
    color: r.verdict === 'AC' ? '#10B981' : '#EF4444',
  }))

  return (
    <PageShell
      title="DSA Progress"
      subtitle={`LeetCode · ${d.leetcode.username}   ·   Codeforces · ${d.codeforces.handle}`}
      actions={
        <button onClick={load} disabled={loading} className="dm-btn-ghost flex items-center gap-2 text-sm">
          <RefreshCw size={14} className={loading ? 'animate-spin' : ''} /> Refresh
        </button>
      }
    >
      {loading ? <LoadingSpinner fullPage label="Fetching DSA stats..." /> : !d.leetcode.username && !d.codeforces.handle ? (
        <div className="flex flex-col items-center justify-center py-24 gap-4 text-center">
          <Award size={40} className="text-dm-muted" />
          <h3 className="font-head font-bold text-lg text-dm-text">No handles configured</h3>
          <p className="text-sm text-dm-muted max-w-xs">Open the <strong>Dashboard</strong> and click the account icon to set your LeetCode username and Codeforces handle.</p>
        </div>
      ) : (
        <div className="space-y-6">
          {/* Stats */}
          <div className="grid grid-cols-2 lg:grid-cols-4 gap-4">
            <StatCard label="LeetCode Solved" value={d.leetcode.total_solved}       sub="All time"           icon={CheckCircle} accent="green"  />
            <StatCard label="Current Streak"  value={`${d.leetcode.streak}d`}       sub="Keep it going!"     icon={Flame}       accent="amber"  />
            <StatCard label="CF Rating"        value={d.codeforces.rating}           sub={d.codeforces.rank}  icon={Award}       accent="cyan"   />
            <StatCard label="Acceptance Rate"  value={`${d.leetcode.acceptance_rate}%`} sub="LeetCode"       icon={TrendingUp}  accent="purple" />
          </div>

          <div className="grid lg:grid-cols-2 gap-6">
            {/* LeetCode breakdown */}
            <div className="dm-card p-5">
              <div className="dm-label mb-4">LeetCode Breakdown</div>
              <div className="flex items-center gap-6">
                <div className="w-32 h-32 shrink-0">
                  <ResponsiveContainer width="100%" height="100%">
                    <RadialBarChart cx="50%" cy="50%" innerRadius="40%" outerRadius="95%" data={radialData} startAngle={90} endAngle={-270}>
                      <RadialBar dataKey="value" cornerRadius={4} />
                    </RadialBarChart>
                  </ResponsiveContainer>
                </div>
                <div className="flex-1 space-y-3">
                  {[
                    { label: 'Easy',   val: d.leetcode.easy,   tot: easyTotal,   color: 'bg-dm-green',  text: 'text-dm-green' },
                    { label: 'Medium', val: d.leetcode.medium, tot: mediumTotal, color: 'bg-dm-amber',  text: 'text-dm-amber' },
                    { label: 'Hard',   val: d.leetcode.hard,   tot: hardTotal,   color: 'bg-red-500',   text: 'text-red-400' },
                  ].map(({ label, val, tot, color, text }) => (
                    <div key={label}>
                      <div className="flex justify-between text-xs mb-1">
                        <span className={text + ' font-medium'}>{label}</span>
                        <span className="text-dm-muted font-mono">{val} / {tot}</span>
                      </div>
                      <div className="h-2 bg-dm-border rounded-full overflow-hidden">
                        <div className={`h-full ${color} rounded-full`} style={{ width: `${(val / tot) * 100}%` }} />
                      </div>
                    </div>
                  ))}
                </div>
              </div>

              <div className="mt-5 border-t border-dm-border pt-4">
                <div className="dm-label mb-3">Recent Submissions</div>
                <div className="space-y-2">
                  {d.leetcode.recent.map((p, i) => (
                    <div key={i} className="flex items-center justify-between">
                      <span className="text-xs text-dm-text">{p.title}</span>
                      <div className="flex items-center gap-2">
                        <span className={`dm-badge ${diffBg[p.difficulty]} ${diffColor[p.difficulty]} text-[10px]`}>{p.difficulty}</span>
                        <span className="text-[10px] text-dm-muted font-mono">{p.date}</span>
                      </div>
                    </div>
                  ))}
                </div>
              </div>
            </div>

            {/* Codeforces */}
            <div className="dm-card p-5">
              <div className="dm-label mb-4">Codeforces Rating History</div>
              <div className="flex items-center gap-4 mb-5">
                <div className="text-center">
                  <div className="font-head font-bold text-3xl text-dm-cyan">{d.codeforces.rating}</div>
                  <div className="text-xs text-dm-muted">Current</div>
                </div>
                <div className="text-center">
                  <div className="font-head font-bold text-xl text-dm-muted">{d.codeforces.max_rating}</div>
                  <div className="text-xs text-dm-muted">Peak</div>
                </div>
                <div className="ml-auto text-center">
                  <div className="dm-badge-cyan px-3 py-1 text-sm font-semibold">{d.codeforces.rank}</div>
                  <div className="text-xs text-dm-muted mt-1">{d.codeforces.solved} solved</div>
                </div>
              </div>

              <div className="h-36 mb-5">
                <ResponsiveContainer width="100%" height="100%">
                  <BarChart data={cfBarData} margin={{ top: 0, right: 0, bottom: 0, left: -20 }}>
                    <CartesianGrid strokeDasharray="3 3" stroke="#1E1E2D" />
                    <XAxis dataKey="name" tick={{ fill: '#6B7280', fontSize: 10 }} />
                    <YAxis tick={{ fill: '#6B7280', fontSize: 10 }} />
                    <Tooltip
                      contentStyle={{ background: '#16161F', border: '1px solid #1E1E2D', borderRadius: '8px', fontSize: '12px' }}
                      labelStyle={{ color: '#E2E8F0' }}
                      itemStyle={{ color: '#A78BFA' }}
                    />
                    <Bar dataKey="rating" radius={[4, 4, 0, 0]} fill="#7C3AED" />
                  </BarChart>
                </ResponsiveContainer>
              </div>

              <div className="border-t border-dm-border pt-4">
                <div className="dm-label mb-3">Recent Submissions</div>
                <div className="space-y-2">
                  {d.codeforces.recent.map((s, i) => (
                    <div key={i} className="flex items-center justify-between">
                      <div className="flex items-center gap-2">
                        {s.verdict === 'AC'
                          ? <CheckCircle size={12} className="text-dm-green shrink-0" />
                          : <XCircle    size={12} className="text-red-400 shrink-0" />
                        }
                        <span className="text-xs text-dm-text">{s.problem}</span>
                      </div>
                      <div className="flex items-center gap-2">
                        <span className="text-[10px] text-dm-muted font-mono">#{s.rating}</span>
                        <span className="text-[10px] text-dm-muted font-mono">{s.date}</span>
                      </div>
                    </div>
                  ))}
                </div>
              </div>
            </div>
          </div>
        </div>
      )}
    </PageShell>
  )
}
