import { useEffect, useState, useRef } from 'react'
import { CalendarDays, RefreshCw, Send, Plus, Clock, Sparkles } from 'lucide-react'
import PageShell from '../components/PageShell'
import LoadingSpinner from '../components/LoadingSpinner'
import { api, CalendarEvent, getUserId } from '../api/client'

function formatDate(iso: string) {
  try {
    return new Date(iso).toLocaleDateString('en-US', { weekday: 'short', month: 'short', day: 'numeric' })
  } catch { return iso.slice(0, 10) }
}

function formatTime(iso: string) {
  if (!iso.includes('T')) return 'All day'
  try {
    return new Date(iso).toLocaleTimeString('en-US', { hour: '2-digit', minute: '2-digit' })
  } catch { return '' }
}

function groupByDate(events: CalendarEvent[]) {
  const map: Record<string, CalendarEvent[]> = {}
  for (const ev of events) {
    const key = (ev.start || '').slice(0, 10)
    if (!map[key]) map[key] = []
    map[key].push(ev)
  }
  return map
}

const COLORS = [
  'border-[rgba(26,26,20,0.5)] bg-[rgba(26,26,20,0.04)]',
  'border-[rgba(15,82,128,0.5)] bg-[rgba(15,82,128,0.04)]',
  'border-[rgba(26,92,58,0.5)]  bg-[rgba(26,92,58,0.04)]',
  'border-[rgba(146,64,14,0.5)] bg-[rgba(146,64,14,0.04)]',
]

export default function Calendar() {
  const userId = getUserId()
  const [events, setEvents] = useState<CalendarEvent[]>([])
  const [loading, setLoading] = useState(true)
  const [chatInput, setChatInput] = useState('')
  const [chatLoading, setChatLoading] = useState(false)
  const [messages, setMessages] = useState<{ role: 'user' | 'ai'; text: string }[]>([
    { role: 'ai', text: 'Hi! Tell me what to schedule — e.g. "Plan 3 DSA sessions this week" or "Block 2 hours for project work tomorrow evening".' },
  ])
  const bottomRef = useRef<HTMLDivElement>(null)

  async function loadEvents() {
    if (!userId) return
    setLoading(true)
    try {
      const data = await api.calendar(userId)
      setEvents(data.events)
    } catch {
      setEvents([])
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => { loadEvents() }, [userId])

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [messages])

  async function handleSend() {
    if (!chatInput.trim() || !userId || chatLoading) return
    const question = chatInput.trim()
    setChatInput('')
    setMessages(m => [...m, { role: 'user', text: question }])
    setChatLoading(true)
    try {
      const res = await api.ask(userId, question)
      setMessages(m => [...m, { role: 'ai', text: res.response }])
      if (res.is_schedule && res.scheduled_events.length > 0) {
        // Optimistically add new events to the list immediately
        setEvents(prev => {
          const newEvs: CalendarEvent[] = res.scheduled_events.map(ev => ({
            id:          ev.id || crypto.randomUUID(),
            summary:     ev.summary,
            description: '',
            start:       ev.start,
            end:         ev.end,
          }))
          return [...prev, ...newEvs].sort((a, b) => a.start.localeCompare(b.start))
        })
        // Background sync after 3 s to get the authoritative Google Calendar data
        setTimeout(() => loadEvents(), 3000)
      }
    } catch (e: unknown) {
      setMessages(m => [...m, { role: 'ai', text: `Error: ${e instanceof Error ? e.message : 'Something went wrong.'}` }])
    } finally {
      setChatLoading(false)
    }
  }

  const grouped = groupByDate(events)
  const dateKeys = Object.keys(grouped).sort()

  return (
    <PageShell
      title="Calendar"
      subtitle="AI-powered schedule planning · Google Calendar"
      actions={
        <button onClick={loadEvents} disabled={loading} className="dm-btn-ghost flex items-center gap-2 text-sm">
          <RefreshCw size={14} className={loading ? 'animate-spin' : ''} /> Refresh
        </button>
      }
    >
      {!userId ? (
        <div className="flex flex-col items-center justify-center py-24 gap-4 text-center">
          <CalendarDays size={40} className="text-dm-muted" />
          <h3 className="font-head font-bold text-lg text-dm-text">Sign in to view your calendar</h3>
        </div>
      ) : (
        <div className="grid lg:grid-cols-2 gap-6">
          {/* Events list */}
          <div className="space-y-4">
            <div className="flex items-center gap-2 mb-1">
              <CalendarDays size={15} className="text-dm-cyan" />
              <span className="dm-label">Upcoming Events</span>
            </div>

            {loading ? (
              <LoadingSpinner label="Loading calendar..." />
            ) : dateKeys.length === 0 ? (
              <div className="dm-card p-8 text-center">
                <p className="text-sm text-dm-muted">No upcoming events. Ask the AI to schedule some!</p>
              </div>
            ) : (
              dateKeys.map(date => (
                <div key={date}>
                  <div className="text-xs font-semibold text-dm-muted font-mono mb-2 px-1">{formatDate(date)}</div>
                  <div className="space-y-2">
                    {grouped[date].map((ev, i) => (
                      <div
                        key={ev.id}
                        className={`dm-card p-3 border-l-2 ${COLORS[i % COLORS.length]}`}
                      >
                        <div className="flex items-start justify-between gap-2">
                          <div className="flex-1 min-w-0">
                            <div className="text-sm font-medium text-dm-text truncate">{ev.summary}</div>
                            {ev.description && (
                              <div className="text-xs text-dm-muted mt-0.5 line-clamp-1">{ev.description}</div>
                            )}
                          </div>
                          <div className="flex items-center gap-1 text-[10px] text-dm-muted font-mono shrink-0">
                            <Clock size={9} />
                            {formatTime(ev.start)}
                          </div>
                        </div>
                      </div>
                    ))}
                  </div>
                </div>
              ))
            )}
          </div>

          {/* AI planning chat */}
          <div className="dm-card flex flex-col overflow-hidden" style={{ height: '600px' }}>
            <div className="flex items-center gap-2 px-4 py-3 border-b border-dm-border bg-dm-surface-2/60 shrink-0">
              <div className="w-2 h-2 rounded-full bg-dm-purple animate-pulse-slow" />
              <Sparkles size={13} className="text-dm-purple-ll" />
              <span className="text-sm font-semibold text-dm-text">AI Planner</span>
              <span className="text-[10px] text-dm-muted ml-auto">Powered by Cohere</span>
            </div>

            {/* Messages */}
            <div className="flex-1 overflow-y-auto px-4 py-3 space-y-3">
              {messages.map((msg, i) => (
                <div key={i} className={`flex ${msg.role === 'user' ? 'justify-end' : 'justify-start'}`}>
                  <div className={`max-w-[85%] rounded-xl px-3 py-2 text-sm leading-relaxed ${
                    msg.role === 'user'
                      ? 'bg-[rgba(26,26,20,0.1)] text-dm-text border border-dm-border'
                      : 'bg-dm-surface-2 text-dm-text border border-dm-border'
                  }`}>
                    {msg.text}
                  </div>
                </div>
              ))}
              {chatLoading && (
                <div className="flex justify-start">
                  <div className="bg-dm-surface-2 border border-dm-border rounded-xl px-3 py-2">
                    <div className="flex gap-1">
                      <div className="w-1.5 h-1.5 rounded-full bg-dm-purple animate-bounce" style={{ animationDelay: '0ms' }} />
                      <div className="w-1.5 h-1.5 rounded-full bg-dm-purple animate-bounce" style={{ animationDelay: '150ms' }} />
                      <div className="w-1.5 h-1.5 rounded-full bg-dm-purple animate-bounce" style={{ animationDelay: '300ms' }} />
                    </div>
                  </div>
                </div>
              )}
              <div ref={bottomRef} />
            </div>

            {/* Quick prompts */}
            <div className="px-4 py-2 border-t border-dm-border bg-dm-surface-2/40 shrink-0">
              <div className="flex gap-2 overflow-x-auto pb-1 scrollbar-hide">
                {[
                  'Plan 3 DSA sessions this week',
                  'Block 2h for project work tomorrow',
                  'Schedule daily 30min review at 9pm',
                ].map(prompt => (
                  <button
                    key={prompt}
                    onClick={() => setChatInput(prompt)}
                    className="shrink-0 text-[10px] px-2.5 py-1 rounded-full border border-dm-border text-dm-muted hover:bg-dm-surface-3 transition-colors"
                  >
                    <Plus size={8} className="inline mr-1" />{prompt}
                  </button>
                ))}
              </div>
            </div>

            {/* Input */}
            <div className="px-4 py-3 border-t border-dm-border shrink-0">
              <div className="flex gap-2">
                <input
                  value={chatInput}
                  onChange={e => setChatInput(e.target.value)}
                  onKeyDown={e => e.key === 'Enter' && !e.shiftKey && handleSend()}
                  placeholder="Tell AI what to schedule..."
                  className="flex-1 bg-dm-surface-2 border border-dm-border rounded-lg px-3 py-2 text-sm text-dm-text placeholder:text-dm-dim focus:outline-none focus:border-dm-border transition-colors"
                />
                <button
                  onClick={handleSend}
                  disabled={!chatInput.trim() || chatLoading}
                  className="w-9 h-9 rounded-lg bg-dm-purple flex items-center justify-center hover:bg-dm-purple-l transition-colors disabled:opacity-40"
                >
                  <Send size={14} className="text-white" />
                </button>
              </div>
            </div>
          </div>
        </div>
      )}
    </PageShell>
  )
}
