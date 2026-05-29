import { useEffect, useState } from 'react'
import {
  Mail, RefreshCw, AlertCircle, ExternalLink, Tag, LogIn, Filter, ChevronRight,
} from 'lucide-react'
import clsx from 'clsx'
import PageShell from '../components/PageShell'
import LoadingSpinner from '../components/LoadingSpinner'
import { api, GmailData, GmailEmail } from '../api/client'
import { useUserId } from '../hooks/useUserId'
import { useNavigate } from 'react-router-dom'

const catStyle: Record<string, { label: string; cls: string }> = {
  internship:  { label: 'Internship',  cls: 'bg-[rgba(26,26,20,0.08)] border-dm-border text-dm-purple-ll' },
  hackathon:   { label: 'Hackathon',   cls: 'bg-[rgba(15,82,128,0.08)] border-dm-border text-dm-cyan'     },
  scholarship: { label: 'Scholarship', cls: 'bg-[rgba(146,64,14,0.08)] border-dm-border text-dm-amber'    },
  other:       { label: 'Other',       cls: 'bg-dm-surface-2 border-dm-border text-dm-muted'              },
}

const CATS = ['all', 'internship', 'hackathon', 'scholarship'] as const
type Cat = typeof CATS[number]

function decodeHtml(html: string): string {
  const txt = document.createElement('textarea')
  txt.innerHTML = html
  return txt.value
}

function formatDate(raw: string): string {
  if (!raw) return ''
  try { return new Date(raw).toLocaleDateString('en-US', { month: 'short', day: 'numeric', year: 'numeric' }) }
  catch { return raw }
}

export default function Gmail() {
  const navigate = useNavigate()
  const userId   = useUserId()

  const [data,     setData]     = useState<GmailData | null>(null)
  const [loading,  setLoading]  = useState(false)
  const [error,    setError]    = useState('')
  const [selected, setSelected] = useState<string | null>(null)
  const [filter,   setFilter]   = useState<Cat>('all')

  async function load() {
    if (!userId) return
    setLoading(true)
    setError('')
    try {
      const d = await api.gmail(userId)
      setData(d)
      if (d.emails.length > 0) setSelected(d.emails[0].id)
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : 'Failed to fetch Gmail data')
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => { if (userId) load() }, [userId])

  if (!userId) {
    return (
      <div className="min-h-screen bg-dm-bg flex items-center justify-center px-6">
        <div className="text-center max-w-sm">
          <div className="w-14 h-14 rounded-2xl bg-red-500/10 flex items-center justify-center mx-auto mb-5">
            <LogIn size={24} className="text-red-400" />
          </div>
          <h2 className="font-head font-bold text-xl text-dm-text mb-2">Sign in required</h2>
          <p className="text-dm-muted text-sm mb-5">Connect your Google account to see your Gmail opportunities.</p>
          <button onClick={() => navigate('/login')} className="dm-btn-primary flex items-center gap-2 mx-auto text-sm">
            Sign in <ChevronRight size={13} />
          </button>
        </div>
      </div>
    )
  }

  const emails   = data?.emails ?? []
  const filtered: GmailEmail[] = filter === 'all' ? emails : emails.filter(e => e.category === filter)
  const active   = emails.find(e => e.id === selected) ?? emails[0] ?? null

  return (
    <PageShell
      title="Gmail Radar"
      subtitle={data ? data.summary : 'Filtered view · internship, hackathon, and recruitment emails only'}
      actions={
        <button onClick={load} disabled={loading} className="dm-btn-ghost flex items-center gap-2 text-sm">
          <RefreshCw size={14} className={loading ? 'animate-spin' : ''} /> Refresh
        </button>
      }
    >
      {loading ? (
        <LoadingSpinner fullPage label="Scanning Gmail for developer opportunities..." />
      ) : error ? (
        <div className="dm-card p-8 text-center">
          <div className="w-12 h-12 rounded-xl bg-red-500/10 flex items-center justify-center mx-auto mb-4">
            <Mail size={20} className="text-red-400" />
          </div>
          <div className="font-semibold text-dm-text mb-2">Gmail not accessible</div>
          <div className="text-sm text-dm-muted mb-5 max-w-sm mx-auto">{error}</div>
          <button onClick={() => navigate('/login')} className="dm-btn-primary text-sm mx-auto flex items-center gap-2">
            Re-authenticate Google <ChevronRight size={13} />
          </button>
        </div>
      ) : (
        <div className="space-y-5">
          {/* Filter chips */}
          <div className="flex items-center gap-2 flex-wrap">
            <Filter size={13} className="text-dm-muted" />
            {CATS.map(c => (
              <button
                key={c}
                onClick={() => setFilter(c)}
                className={clsx(
                  'px-4 py-1.5 rounded-full text-xs font-medium border transition-all duration-150',
                  filter === c
                    ? 'bg-dm-purple border-dm-purple text-white shadow-glow-sm'
                    : 'bg-transparent border-dm-border text-dm-muted hover:border-dm-purple/40 hover:text-dm-text',
                )}
              >
                {c.charAt(0).toUpperCase() + c.slice(1)}
                {c !== 'all' && (
                  <span className="ml-1.5 text-[10px] opacity-70">
                    {emails.filter(e => e.category === c).length}
                  </span>
                )}
              </button>
            ))}
          </div>

          {filtered.length === 0 ? (
            <div className="dm-card p-12 text-center">
              <Mail size={32} className="text-dm-muted mx-auto mb-4" />
              <div className="font-semibold text-dm-text mb-1">No emails in this category</div>
              <div className="text-sm text-dm-muted">
                {emails.length === 0
                  ? 'No developer opportunity emails found matching the filter query.'
                  : 'Try switching to All to see all results.'}
              </div>
            </div>
          ) : (
            <div className="grid lg:grid-cols-5 gap-5">
              {/* Email list */}
              <div className="lg:col-span-2 space-y-2">
                {filtered.map(email => (
                  <button
                    key={email.id}
                    onClick={() => setSelected(email.id)}
                    className={clsx(
                      'w-full text-left dm-card p-4 transition-all duration-150',
                      selected === email.id
                        ? 'border-dm-purple/40 shadow-glow-sm bg-dm-surface-2'
                        : 'hover:border-dm-border/80 hover:bg-dm-surface-2/50',
                    )}
                  >
                    <div className="flex items-start justify-between gap-2 mb-1.5">
                      <div className="flex items-center gap-1.5 min-w-0">
                        {email.action_required && (
                          <AlertCircle size={11} className="text-dm-amber shrink-0" />
                        )}
                        <span className="text-xs font-semibold text-dm-text truncate">{decodeHtml(email.subject)}</span>
                      </div>
                      <span className={clsx('dm-badge shrink-0 text-[10px]', catStyle[email.category].cls)}>
                        {catStyle[email.category].label}
                      </span>
                    </div>
                    <div className="text-[10px] text-dm-muted font-mono mb-1.5 truncate">{email.from}</div>
                    <div className="text-xs text-dm-muted line-clamp-2 leading-relaxed">{decodeHtml(email.snippet)}</div>
                    <div className="text-[10px] text-dm-dim font-mono mt-2">{formatDate(email.date)}</div>
                  </button>
                ))}
              </div>

              {/* Email detail */}
              {active && (
                <div className="lg:col-span-3 dm-card overflow-hidden">
                  {/* Header */}
                  <div className="px-5 py-4 border-b border-dm-border bg-dm-surface-2/60 flex items-start justify-between gap-3">
                    <div className="flex items-center gap-2 min-w-0">
                      <Mail size={14} className="text-dm-muted shrink-0" />
                      <span className="text-sm font-semibold text-dm-text truncate">{decodeHtml(active.subject)}</span>
                    </div>
                    <div className="flex items-center gap-2 shrink-0">
                      <span className={clsx('dm-badge text-xs', catStyle[active.category].cls)}>
                        <Tag size={9} className="inline mr-1" />
                        {catStyle[active.category].label}
                      </span>
                      {active.action_required && (
                        <span className="dm-badge bg-dm-amber/10 border-dm-amber/30 text-dm-amber text-xs">
                          <AlertCircle size={9} className="inline mr-1" />Action
                        </span>
                      )}
                    </div>
                  </div>

                  <div className="p-5 space-y-5">
                    {/* Meta */}
                    <div className="flex flex-wrap gap-x-6 gap-y-1 text-xs font-mono">
                      <span className="text-dm-muted">From: <span className="text-dm-text">{active.from}</span></span>
                      <span className="text-dm-muted">Date: <span className="text-dm-text">{formatDate(active.date)}</span></span>
                    </div>

                    {/* Snippet */}
                    <div className="p-4 rounded-lg bg-dm-surface-2 border border-dm-border text-sm text-dm-text leading-relaxed italic">
                      "{decodeHtml(active.snippet)}"
                    </div>

                    {/* AI summary (if available) */}
                    {active.ai_summary && (
                      <div>
                        <div className="flex items-center gap-2 mb-3">
                          <div className="w-2 h-2 rounded-full bg-dm-purple animate-pulse-slow" />
                          <span className="dm-label">AI Summary</span>
                        </div>
                        <div className="p-4 rounded-lg bg-dm-purple-dim border border-dm-purple/20 text-sm text-dm-text leading-relaxed">
                          {active.ai_summary}
                        </div>
                      </div>
                    )}

                    {/* CTA */}
                    <div className="flex gap-3 pt-1">
                      <a
                        href={active.gmail_link}
                        target="_blank"
                        rel="noopener noreferrer"
                        className="dm-btn-primary text-sm flex items-center gap-2"
                      >
                        <ExternalLink size={13} /> Open in Gmail
                      </a>
                      {active.action_required && (
                        <span className="flex items-center gap-1.5 text-xs text-dm-amber font-medium">
                          <AlertCircle size={12} /> Action required
                        </span>
                      )}
                    </div>
                  </div>
                </div>
              )}
            </div>
          )}
        </div>
      )}
    </PageShell>
  )
}
