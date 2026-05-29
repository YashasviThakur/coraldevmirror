import { useEffect, useState } from 'react'
import { Target, Calendar, Youtube, RefreshCw, Clock, ChevronRight, Zap } from 'lucide-react'
import PageShell from '../components/PageShell'
import AIReport from '../components/AIReport'
import LoadingSpinner from '../components/LoadingSpinner'
import { api, FocusData, getUserId } from '../api/client'

const DEMO: FocusData = {
  recommendation: `Based on everything I see, your #1 focus today is:

  Solve one LeetCode Medium problem.

Here's why this is the right move today:
  → You have a 2-day streak going — protect it.
  → You solved only Easy problems yesterday — Medium is the next natural step.
  → Your Google Calendar shows a free evening slot at 8 PM.
  → No urgent internship emails require action today.

Suggested problem type: Arrays / Sliding Window — your acceptance rate there is strong.

After that, 30 min on your AI-voice-detection-demo-UI repo would be bonus points.

You've got this.`,
  priority_task: 'Solve 1 LeetCode Medium (Sliding Window)',
  reasoning: '2-day streak + free evening slot + Medium skills gap',
  calendar_today: [
    { title: 'DSA Practice',           time: '8:00 PM', duration: '1h' },
    { title: 'System Design Review',   time: '10:00 PM', duration: '30m' },
  ],
  youtube_watched: [
    { title: 'Dynamic Programming - NeetCode', channel: 'NeetCode',      duration: '45m' },
    { title: 'Git Advanced Tips',              channel: 'Fireship',      duration: '12m' },
    { title: 'FastAPI Full Course',            channel: 'Tech With Tim', duration: '1h 20m' },
  ],
}

export default function FocusToday() {
  const [data, setData] = useState<FocusData | null>(null)
  const [loading, setLoading] = useState(true)

  async function load() {
    setLoading(true)
    try { setData(await api.focus(getUserId() ?? undefined)) }
    catch { setData(DEMO) }
    finally { setLoading(false) }
  }

  useEffect(() => { load() }, [])

  const d = data ?? DEMO
  const today = new Date().toLocaleDateString('en-US', { weekday: 'long', month: 'long', day: 'numeric' })

  return (
    <PageShell
      title="Focus Today"
      subtitle={today}
      actions={
        <button onClick={load} disabled={loading} className="dm-btn-ghost flex items-center gap-2 text-sm">
          <RefreshCw size={14} className={loading ? 'animate-spin' : ''} /> Refresh
        </button>
      }
    >
      {loading ? <LoadingSpinner fullPage label="Analysing your data..." /> : (
        <div className="space-y-6">
          {/* Priority card */}
          <div className="border-gradient rounded-xl p-6 bg-dm-surface relative overflow-hidden">
            <div className="absolute inset-0 bg-card-glow pointer-events-none" />
            <div className="relative">
              <div className="flex items-center gap-2 mb-3">
                <Zap size={16} className="text-dm-purple-ll" />
                <span className="dm-label">Top Priority Today</span>
              </div>
              <h2 className="font-head font-bold text-2xl text-dm-text mb-2">{d.priority_task}</h2>
              <p className="text-sm text-dm-muted">{d.reasoning}</p>
            </div>
          </div>

          <div className="grid lg:grid-cols-3 gap-6">
            {/* AI recommendation */}
            <div className="lg:col-span-2 dm-card overflow-hidden">
              <div className="flex items-center gap-2 px-5 py-4 border-b border-dm-border bg-dm-surface-2/60">
                <Target size={15} className="text-dm-purple-ll" />
                <span className="text-sm font-semibold text-dm-text">AI Recommendation</span>
              </div>
              <div className="p-6">
                <AIReport content={d.recommendation} typingSpeed={5} />
              </div>
            </div>

            {/* Right column */}
            <div className="space-y-4">
              {/* Calendar */}
              <div className="dm-card p-4">
                <div className="flex items-center gap-2 mb-3">
                  <Calendar size={14} className="text-dm-green" />
                  <span className="dm-label">Today's Sessions</span>
                </div>
                {d.calendar_today.length === 0 ? (
                  <p className="text-xs text-dm-muted">No sessions scheduled today.</p>
                ) : (
                  <div className="space-y-2">
                    {d.calendar_today.map((e, i) => (
                      <div key={i} className="flex items-center gap-3 p-2.5 rounded-lg bg-dm-surface-2">
                        <div className="w-1 h-8 rounded-full bg-dm-green shrink-0" />
                        <div className="flex-1 min-w-0">
                          <div className="text-xs font-medium text-dm-text truncate">{e.title}</div>
                          <div className="flex items-center gap-1.5 text-[10px] text-dm-muted font-mono mt-0.5">
                            <Clock size={9} /> {e.time} · {e.duration}
                          </div>
                        </div>
                        <ChevronRight size={12} className="text-dm-dim shrink-0" />
                      </div>
                    ))}
                  </div>
                )}
              </div>

              {/* YouTube */}
              <div className="dm-card p-4">
                <div className="flex items-center gap-2 mb-3">
                  <Youtube size={14} className="text-red-400" />
                  <span className="dm-label">YouTube Today</span>
                </div>
                <div className="space-y-2">
                  {d.youtube_watched.map((v, i) => (
                    <div key={i} className="p-2.5 rounded-lg bg-dm-surface-2">
                      <div className="text-xs font-medium text-dm-text leading-snug mb-0.5 line-clamp-1">{v.title}</div>
                      <div className="flex items-center gap-2 text-[10px] text-dm-muted font-mono">
                        <span className="text-red-400">{v.channel}</span>
                        <span>·</span>
                        <span>{v.duration}</span>
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
