import { ElementType, useEffect, useState, useCallback, useRef } from 'react'
import { useNavigate } from 'react-router-dom'
import {
  Github, Code2, Trophy, Calendar, RefreshCw,
  Flame, Star, TrendingUp, LogIn, Settings2,
  CheckCircle2, XCircle, ChevronRight,
} from 'lucide-react'
import clsx from 'clsx'
import PageShell from '../components/PageShell'
import LoadingSpinner from '../components/LoadingSpinner'
import { api, GitHubData, LeetCodeData, CodeForcesData, CalendarData, UserProfile } from '../api/client'
import { useUserId } from '../hooks/useUserId'

// -- GitHub contribution grid ---------------------------------------------------
function GitHubGrid({ grid }: { grid: number[][] | null | undefined }) {
  const safeGrid = Array.isArray(grid) && grid.length > 0 ? grid : null

  if (!safeGrid) {
    return (
      <div className="flex items-center justify-center h-16 text-xs text-dm-muted">
        No contribution data available
      </div>
    )
  }

  const allValues = safeGrid.flatMap(c => (Array.isArray(c) ? c : []))
  const maxCount  = allValues.length > 0 ? Math.max(...allValues, 1) : 1

  const getColor = (n: number) => {
    if (n === 0) return 'bg-zinc-800/80'
    const t = n / maxCount
    if (t < 0.25) return 'bg-green-900'
    if (t < 0.5)  return 'bg-green-700'
    if (t < 0.75) return 'bg-green-500'
    return 'bg-green-400'
  }

  return (
    <div className="flex gap-0.5 overflow-hidden w-full">
      {safeGrid.map((col, ci) => (
        <div key={ci} className="flex flex-col gap-0.5">
          {(Array.isArray(col) ? col : []).map((count, di) => (
            <div
              key={di}
              title={`${count} commits`}
              className={`w-2 h-2 rounded-sm ${getColor(count)} transition-colors duration-200`}
            />
          ))}
        </div>
      ))}
    </div>
  )
}

// -- CF rank ? colour mapping ---------------------------------------------------
const CF_RANK_COLORS: Record<string, string> = {
  'newbie':          'text-zinc-400',
  'pupil':           'text-dm-green',
  'specialist':      'text-dm-cyan',
  'expert':          'text-blue-400',
  'candidate master':'text-dm-purple-ll',
  'master':          'text-dm-amber',
  'international master': 'text-orange-400',
  'grandmaster':     'text-red-500',
  'international grandmaster': 'text-red-600',
  'legendary grandmaster': 'text-red-700',
}
function cfRankColor(rank: string) {
  return CF_RANK_COLORS[rank.toLowerCase()] ?? 'text-dm-muted'
}

// -- Inline goal input with debounced save -------------------------------------
function GoalInput({
  label, value, onChange,
}: { label: string; value: string; onChange: (v: string) => void }) {
  return (
    <div className="flex-1 min-w-0">
      <label className="dm-label block mb-1.5">{label}</label>
      <input
        type="text"
        value={value}
        onChange={e => onChange(e.target.value)}
        placeholder={`e.g. Crack ${label === 'Focus Goal 1' ? 'LeetCode 150' : label === 'Focus Goal 2' ? 'CF 1600' : 'GSoC 2026'}`}
        className="dm-input text-sm h-9 text-dm-text"
      />
    </div>
  )
}

// -- Empty state card -----------------------------------------------------------
function EmptyState({ icon: Icon, title, desc, action, onAction }: {
  icon: ElementType; title: string; desc: string; action?: string; onAction?: () => void
}) {
  return (
    <div className="flex flex-col items-center justify-center h-full min-h-[120px] gap-3 py-6">
      <div className="w-10 h-10 rounded-xl bg-dm-surface-2 flex items-center justify-center">
        <Icon size={18} className="text-dm-muted" />
      </div>
      <div className="text-center">
        <div className="text-sm font-medium text-dm-text">{title}</div>
        <div className="text-xs text-dm-muted mt-0.5">{desc}</div>
      </div>
      {action && (
        <button onClick={onAction} className="dm-btn-ghost text-xs flex items-center gap-1.5">
          {action} <ChevronRight size={11} />
        </button>
      )}
    </div>
  )
}

// -- Main Dashboard -------------------------------------------------------------
export default function Dashboard() {
  const navigate  = useNavigate()
  const userId    = useUserId()

  const [profile,    setProfile]    = useState<UserProfile | null>(null)
  const [github,     setGithub]     = useState<GitHubData | null>(null)
  const [leetcode,   setLeetcode]   = useState<LeetCodeData | null>(null)
  const [codeforces, setCodeforces] = useState<CodeForcesData | null>(null)
  const [calendar,   setCalendar]   = useState<CalendarData | null>(null)
  const [loading,    setLoading]    = useState(true)
  const [refreshing, setRefreshing] = useState(false)
  const [savingGoals, setSavingGoals] = useState(false)

  const [goal1, setGoal1] = useState('')
  const [goal2, setGoal2] = useState('')
  const [goal3, setGoal3] = useState('')
  const saveTimer = useRef<ReturnType<typeof setTimeout>>()

  // Settings panel for handles / github username
  const [showSettings, setShowSettings] = useState(false)
  const [cfHandle,   setCfHandle]   = useState('')
  const [lcHandle,   setLcHandle]   = useState('')
  const [ghUsername, setGhUsername] = useState('')
  const [savingHandles, setSavingHandles] = useState(false)

  const loadProfile = useCallback(async (uid: number) => {
    try {
      const p = await api.getUser(uid)
      setProfile(p)
      setGoal1(p.goal_1)
      setGoal2(p.goal_2)
      setGoal3(p.goal_3)
      setCfHandle(p.codeforces_handle ?? '')
      setLcHandle(p.leetcode_username ?? '')
      setGhUsername(p.github_username ?? '')
    } catch { /* silently ignore */ }
  }, [])

  const loadData = useCallback(async (uid: number) => {
    setLoading(true)
    await loadProfile(uid)
    await Promise.allSettled([
      api.github(uid).then(setGithub).catch(() => null),
      api.leetcode(uid).then(setLeetcode).catch(() => null),
      api.codeforces(uid).then(setCodeforces).catch(() => null),
      api.calendar(uid).then(setCalendar).catch(() => null),
    ])
    setLoading(false)
  }, [loadProfile])

  useEffect(() => {
    if (userId) loadData(userId)
    else setLoading(false)
  }, [userId, loadData])

  // Debounced goal save
  const handleGoalChange = (field: 'goal_1' | 'goal_2' | 'goal_3', value: string) => {
    if (field === 'goal_1') setGoal1(value)
    if (field === 'goal_2') setGoal2(value)
    if (field === 'goal_3') setGoal3(value)

    if (!userId) return
    clearTimeout(saveTimer.current)
    saveTimer.current = setTimeout(async () => {
      setSavingGoals(true)
      try {
        await api.updateGoals(userId, {
          goal_1: field === 'goal_1' ? value : goal1,
          goal_2: field === 'goal_2' ? value : goal2,
          goal_3: field === 'goal_3' ? value : goal3,
        })
      } finally {
        setSavingGoals(false)
      }
    }, 900)
  }

  async function handleRefresh() {
    if (!userId) return
    setRefreshing(true)
    await loadData(userId)
    setRefreshing(false)
  }

  async function handleSaveHandles() {
    if (!userId) return
    setSavingHandles(true)
    try {
      await api.updateHandles(userId, { codeforces_handle: cfHandle, leetcode_username: lcHandle })
      if (ghUsername.trim()) await api.updateGithubUsername(userId, ghUsername.trim())
      await loadData(userId)
      setShowSettings(false)
    } finally {
      setSavingHandles(false)
    }
  }

  const now      = new Date()
  const greeting = now.getHours() < 12 ? 'Good morning' : now.getHours() < 18 ? 'Good afternoon' : 'Good evening'
  const userLabel = profile?.name ?? (profile?.email ? profile.email.split('@')[0] : `User #${userId}`)

  // -- Not logged in state ------------------------------------------------------
  if (!loading && !userId) {
    return (
      <div className="min-h-screen bg-dm-bg flex items-center justify-center px-6">
        <div className="text-center max-w-sm">
          <div className="w-16 h-16 rounded-2xl bg-dm-purple/15 flex items-center justify-center mx-auto mb-6">
            <LogIn size={28} className="text-dm-purple-ll" />
          </div>
          <h2 className="font-head font-bold text-2xl text-dm-text mb-3">Sign in to DevMirror</h2>
          <p className="text-dm-muted text-sm mb-6">Connect your developer accounts to unlock your personalised bento dashboard.</p>
          <button onClick={() => navigate('/login')} className="dm-btn-primary flex items-center gap-2 mx-auto">
            Sign in with Google <ChevronRight size={14} />
          </button>
        </div>
      </div>
    )
  }

  return (
    <PageShell
      title="Dashboard"
      subtitle={`${greeting}, ${userLabel} · ${now.toLocaleDateString('en-US', { weekday: 'long', month: 'long', day: 'numeric' })}`}
      actions={
        <div className="flex items-center gap-2">
          <span className="text-xs font-mono px-2 py-1 rounded border border-dm-purple/40 text-dm-purple-ll bg-dm-purple-dim">
            ⚡ Powered by Coral SQL
          </span>
          <button onClick={handleRefresh} disabled={refreshing || loading} className="dm-btn-ghost flex items-center gap-2 text-sm">
            <RefreshCw size={14} className={refreshing ? 'animate-spin' : ''} /> Refresh
          </button>
        </div>
      }
    >
      {/* Settings panel */}
      {showSettings && (
        <div className="dm-card p-6 mb-6 border-dm-purple/25 bg-dm-purple-dim">
          <div className="dm-label mb-4">Connect Your Accounts</div>
          <div className="grid md:grid-cols-3 gap-4 mb-5">
            <div>
              <label className="dm-label block mb-1.5">LeetCode Username</label>
              <input value={lcHandle} onChange={e => setLcHandle(e.target.value)} placeholder="your-lc-username" className="dm-input text-sm h-9" />
            </div>
            <div>
              <label className="dm-label block mb-1.5">Codeforces Handle</label>
              <input value={cfHandle} onChange={e => setCfHandle(e.target.value)} placeholder="your-cf-handle" className="dm-input text-sm h-9" />
            </div>
            <div>
              <label className="dm-label block mb-1.5">GitHub Username</label>
              <input value={ghUsername} onChange={e => setGhUsername(e.target.value)} type="text" placeholder="e.g. torvalds" className="dm-input text-sm h-9" />
            </div>
          </div>
          <div className="flex gap-3">
            <button onClick={handleSaveHandles} disabled={savingHandles} className="dm-btn-primary text-sm flex items-center gap-2">
              {savingHandles ? <RefreshCw size={13} className="animate-spin" /> : null}
              Save &amp; Refresh
            </button>
            <button onClick={() => setShowSettings(false)} className="dm-btn-ghost text-sm">Cancel</button>
          </div>
        </div>
      )}

      {/* -- Goals header row -- */}
      <div className="dm-card p-5 mb-5">
        <div className="flex items-center gap-3 mb-4">
          <div className="w-8 h-8 rounded-lg bg-dm-purple flex items-center justify-center shadow-glow-sm">
            <span className="text-white font-mono font-bold text-sm">D</span>
          </div>
          <span className="font-head font-bold text-dm-text">DevMirror</span>
          <span className="dm-badge-purple">Focus Goals</span>
          <Star size={13} className="text-dm-amber ml-auto" />
        </div>
        <div className="flex gap-4 flex-wrap md:flex-nowrap">
          <GoalInput label="Focus Goal 1" value={goal1} onChange={v => handleGoalChange('goal_1', v)} />
          <GoalInput label="Focus Goal 2" value={goal2} onChange={v => handleGoalChange('goal_2', v)} />
          <GoalInput label="Focus Goal 3" value={goal3} onChange={v => handleGoalChange('goal_3', v)} />
        </div>
      </div>

      {loading ? (
        <LoadingSpinner fullPage label="Fetching your developer data..." />
      ) : (
        /* -- Bento grid -- */
        <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-5">

          {/* GitHub contribution grid ? spans 2 cols */}
          <div className="md:col-span-2 dm-card p-5">
            <div className="flex items-center gap-2 mb-4">
              <Github size={15} className="text-white" />
              <span className="text-sm font-semibold text-dm-text">GitHub Activity</span>
              {github && (
                <>
                  <span className="dm-badge-green ml-1 text-[10px]">{github.commits_week} this week</span>
                  <span className="text-xs text-dm-muted ml-auto font-mono">{github.username}</span>
                </>
              )}
            </div>

            {github ? (
              <>
                <div className="overflow-x-auto pb-1">
                  <GitHubGrid grid={github.contribution_grid} />
                </div>
                <div className="flex items-center gap-5 mt-4 pt-4 border-t border-dm-border text-xs text-dm-muted">
                  <span><span className="text-dm-text font-mono">{github.repos}</span> repos</span>
                  <span><span className="text-dm-text font-mono">{github.public_repos}</span> public</span>
                  <span><span className="text-dm-text font-mono">{github.followers}</span> followers</span>
                  <span className="ml-auto text-[10px]">
                    Top: <span className="text-dm-purple-ll font-mono">{github.top_repo}</span>
                  </span>
                </div>
                {(github.languages ?? []).length > 0 && (
                  <div className="flex gap-1.5 flex-wrap mt-3">
                    {(github.languages ?? []).map(l => (
                      <span key={l} className="dm-badge-purple text-[10px]">{l}</span>
                    ))}
                  </div>
                )}
              </>
            ) : (
              <EmptyState
                icon={Github}
                title="GitHub not connected"
                desc="Add a GitHub PAT in Accounts settings"
                action="Open settings"
                onAction={() => setShowSettings(true)}
              />
            )}
          </div>

          {/* Codeforces */}
          <div className="dm-card p-5">
            <div className="flex items-center gap-2 mb-5">
              <Trophy size={15} className="text-dm-cyan" />
              <span className="text-sm font-semibold text-dm-text">Codeforces</span>
              {codeforces && (
                <span className={clsx('dm-badge ml-auto text-[10px] border', cfRankColor(codeforces.rank))}>
                  {codeforces.rank}
                </span>
              )}
            </div>

            {codeforces ? (
              <div className="space-y-4">
                <div className="grid grid-cols-3 gap-3 text-center">
                  <div>
                    <div className="font-head font-bold text-2xl text-dm-cyan">{codeforces.rating}</div>
                    <div className="text-[10px] text-dm-muted">Current</div>
                  </div>
                  <div>
                    <div className="font-head font-bold text-xl text-dm-muted">{codeforces.max_rating}</div>
                    <div className="text-[10px] text-dm-muted">Peak</div>
                  </div>
                  <div>
                    <div className="font-head font-bold text-xl text-dm-text">{codeforces.solved}</div>
                    <div className="text-[10px] text-dm-muted">Solved</div>
                  </div>
                </div>

                {(codeforces.recent ?? []).length > 0 && (
                  <div className="space-y-1.5 border-t border-dm-border pt-3">
                    {(codeforces.recent ?? []).slice(0, 4).map((s, i) => (
                      <div key={i} className="flex items-center gap-2">
                        {s.verdict === 'OK'
                          ? <CheckCircle2 size={11} className="text-dm-green shrink-0" />
                          : <XCircle     size={11} className="text-red-400 shrink-0" />
                        }
                        <span className="text-xs text-dm-text truncate flex-1">{s.problem}</span>
                        <span className="text-[10px] text-dm-muted font-mono shrink-0">#{s.rating}</span>
                      </div>
                    ))}
                  </div>
                )}
              </div>
            ) : (
              <EmptyState
                icon={Trophy}
                title="Codeforces not connected"
                desc="Set your handle in Accounts settings"
                action="Open settings"
                onAction={() => setShowSettings(true)}
              />
            )}
          </div>

          {/* LeetCode progress */}
          <div className="dm-card p-5">
            <div className="flex items-center gap-2 mb-5">
              <Code2 size={15} className="text-dm-amber" />
              <span className="text-sm font-semibold text-dm-text">LeetCode</span>
              {leetcode && leetcode.streak > 0 && (
                <span className="ml-auto flex items-center gap-1 dm-badge bg-dm-amber/10 border-dm-amber/30 text-dm-amber text-[10px]">
                  <Flame size={9} /> {leetcode.streak}d streak
                </span>
              )}
            </div>

            {leetcode ? (
              <div className="space-y-4">
                <div className="text-center">
                  <div className="font-head font-bold text-3xl text-dm-amber">{leetcode.total_solved}</div>
                  <div className="text-xs text-dm-muted">problems solved</div>
                </div>

                <div className="space-y-2.5">
                  {[
                    { label: 'Easy',   val: leetcode.easy,   max: leetcode.total_solved || 1, color: 'bg-dm-green',  text: 'text-dm-green' },
                    { label: 'Medium', val: leetcode.medium, max: leetcode.total_solved || 1, color: 'bg-dm-amber',  text: 'text-dm-amber' },
                    { label: 'Hard',   val: leetcode.hard,   max: leetcode.total_solved || 1, color: 'bg-red-500',   text: 'text-red-400'  },
                  ].map(({ label, val, max, color, text }) => (
                    <div key={label}>
                      <div className="flex justify-between text-xs mb-1">
                        <span className={clsx(text, 'font-medium')}>{label}</span>
                        <span className="text-dm-muted font-mono">{val}</span>
                      </div>
                      <div className="h-1.5 bg-dm-border rounded-full overflow-hidden">
                        <div
                          className={`h-full ${color} rounded-full transition-all duration-700`}
                          style={{ width: `${(val / max) * 100}%` }}
                        />
                      </div>
                    </div>
                  ))}
                </div>

                <div className="flex items-center justify-between pt-2 border-t border-dm-border text-xs text-dm-muted">
                  <span>{leetcode.total_active_days} active days</span>
                  <span className="font-mono text-dm-text">{leetcode.username}</span>
                </div>
              </div>
            ) : (
              <EmptyState
                icon={Code2}
                title="LeetCode not connected"
                desc="Set your username in Accounts settings"
                action="Open settings"
                onAction={() => setShowSettings(true)}
              />
            )}
          </div>

          {/* Google Calendar */}
          <div className="dm-card p-5">
            <div className="flex items-center gap-2 mb-5">
              <Calendar size={15} className="text-dm-green" />
              <span className="text-sm font-semibold text-dm-text">Upcoming Events</span>
              {calendar && (
                <span className="ml-auto dm-badge-green text-[10px]">{calendar.events.length} events</span>
              )}
            </div>

            {calendar && calendar.events.length > 0 ? (
              <div className="space-y-2.5">
                {calendar.events.slice(0, 5).map(ev => {
                  const start = new Date(ev.start)
                  return (
                    <div key={ev.id} className="flex items-start gap-3">
                      <div className="w-1 h-1 rounded-full bg-dm-green mt-1.5 shrink-0" />
                      <div className="flex-1 min-w-0">
                        <div className="text-xs font-medium text-dm-text truncate">{ev.summary}</div>
                        <div className="text-[10px] text-dm-muted font-mono mt-0.5">
                          {start.toLocaleDateString('en-US', { weekday: 'short', month: 'short', day: 'numeric' })}
                          {' · '}
                          {start.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}
                        </div>
                      </div>
                    </div>
                  )
                })}
                {calendar.events.length > 5 && (
                  <div className="text-xs text-dm-muted font-mono pt-1">
                    +{calendar.events.length - 5} more events
                  </div>
                )}
              </div>
            ) : (
              <EmptyState
                icon={Calendar}
                title={calendar ? 'No upcoming events' : 'Calendar not connected'}
                desc={calendar ? 'Ask the AI Coach to schedule tasks for you' : 'Sign in with Google to see events'}
                action="Open AI Coach"
                onAction={() => navigate('/coach')}
              />
            )}
          </div>

          {/* Quick navigation row ? spans full width */}
          <div className="md:col-span-2 xl:col-span-3">
            <div className="dm-label mb-3">Quick Access</div>
            <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
              {[
                { to: '/gmail',         icon: TrendingUp,  label: 'Gmail Radar',   badge: 'Opportunities', accent: 'text-red-400',    bg: 'bg-red-500/10'    },
                { to: '/youtube',       icon: TrendingUp,  label: 'YouTube',        badge: 'Watch History', accent: 'text-red-500',    bg: 'bg-red-500/10'    },
                { to: '/coach',         icon: TrendingUp,  label: 'AI Coach',       badge: 'Cohere',        accent: 'text-dm-purple-ll', bg: 'bg-dm-purple/15' },
                { to: '/growth-report', icon: TrendingUp,  label: 'Growth Report',  badge: 'Daily AI',      accent: 'text-dm-amber',   bg: 'bg-dm-amber/10'   },
              ].map(({ to, label, badge, accent, bg }) => (
                <button
                  key={to}
                  onClick={() => navigate(to)}
                  className="dm-card p-4 text-left hover:border-dm-purple/30 hover:-translate-y-0.5 hover:shadow-glow-sm transition-all duration-200 group"
                >
                  <div className={clsx('inline-flex items-center gap-1.5 dm-badge mb-3 border text-[10px]', bg, accent === 'text-dm-purple-ll' ? 'border-dm-purple/30' : 'border-transparent')}>
                    {badge}
                  </div>
                  <div className="flex items-center justify-between">
                    <span className="text-sm font-semibold text-dm-text">{label}</span>
                    <ChevronRight size={13} className="text-dm-muted group-hover:text-dm-text group-hover:translate-x-0.5 transition-all duration-150" />
                  </div>
                </button>
              ))}
            </div>
          </div>
        </div>
      )}
    </PageShell>
  )
}
