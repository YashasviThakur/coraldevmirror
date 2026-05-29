import { useState, useCallback, useRef, useEffect } from 'react'
import { Youtube, Upload, FileJson, RefreshCw, ThumbsUp, Info, ExternalLink, ChevronRight } from 'lucide-react'
import clsx from 'clsx'
import PageShell from '../components/PageShell'
import LoadingSpinner from '../components/LoadingSpinner'
import { api, YouTubeAnalysis, YouTubeLikedData } from '../api/client'
import { useUserId } from '../hooks/useUserId'
import { useNavigate } from 'react-router-dom'

const CATEGORY_COLORS: Record<string, string> = {
  'Algorithms & DS': 'bg-dm-purple/20 border-dm-purple/40 text-dm-purple-ll',
  'Languages':       'bg-dm-cyan/10 border-dm-cyan/30 text-dm-cyan',
  'Web Dev':         'bg-dm-green/10 border-dm-green/30 text-dm-green',
  'ML / AI':         'bg-dm-amber/10 border-dm-amber/30 text-dm-amber',
  'System Design':   'bg-blue-500/10 border-blue-400/30 text-blue-400',
  'CS Fundamentals': 'bg-red-500/10 border-red-400/30 text-red-400',
  'Interview Prep':  'bg-pink-500/10 border-pink-400/30 text-pink-400',
}

function BarChart({ categories }: { categories: Record<string, number> }) {
  const entries = Object.entries(categories).sort((a, b) => b[1] - a[1])
  const max     = entries[0]?.[1] || 1
  return (
    <div className="space-y-3">
      {entries.map(([cat, count]) => (
        <div key={cat}>
          <div className="flex items-center justify-between mb-1.5">
            <span className={clsx('dm-badge text-[10px]', CATEGORY_COLORS[cat] ?? 'bg-dm-surface-2 border-dm-border text-dm-muted')}>
              {cat}
            </span>
            <span className="text-xs font-mono text-dm-muted">{count} videos</span>
          </div>
          <div className="h-2 bg-dm-border rounded-full overflow-hidden">
            <div
              className="h-full bg-dm-purple rounded-full transition-all duration-700"
              style={{ width: `${(count / max) * 100}%` }}
            />
          </div>
        </div>
      ))}
    </div>
  )
}

type AnalysisResult = {
  total: number
  technical_count: number
  categories: Record<string, number>
  top_videos: {
    title: string; channel: string; categories: string[]
    thumbnail?: string; video_id?: string; watched_at?: string
  }[]
}

function AnalysisResults({ data, totalLabel }: { data: AnalysisResult; totalLabel: string }) {
  const techPct = data.total ? Math.round((data.technical_count / data.total) * 100) : 0
  return (
    <div className="space-y-6">
      <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
        {[
          { label: totalLabel,         val: data.total.toLocaleString(),           color: 'text-dm-text'       },
          { label: 'Study-Related',    val: data.technical_count.toLocaleString(), color: 'text-dm-purple-ll'  },
          { label: 'Study Share',      val: `${techPct}%`,                         color: 'text-dm-green'      },
          { label: 'Topics Detected',  val: Object.keys(data.categories).length.toString(), color: 'text-dm-cyan' },
        ].map(({ label, val, color }) => (
          <div key={label} className="dm-card p-4 text-center">
            <div className={clsx('font-head font-bold text-2xl', color)}>{val}</div>
            <div className="text-xs text-dm-muted mt-1">{label}</div>
          </div>
        ))}
      </div>

      <div className="grid lg:grid-cols-2 gap-6">
        <div className="dm-card p-5">
          <div className="dm-label mb-5">Technical Topic Distribution</div>
          {Object.keys(data.categories).length > 0
            ? <BarChart categories={data.categories} />
            : <p className="text-sm text-dm-muted text-center py-8">No technical topics detected.</p>
          }
        </div>

        <div className="dm-card p-5">
          <div className="dm-label mb-4">Study-Related Videos</div>
          {data.top_videos.length > 0 ? (
            <div className="space-y-2.5 max-h-80 overflow-y-auto pr-1">
              {data.top_videos.map((v, i) => (
                <div key={i} className="flex items-start gap-3 p-3 rounded-lg bg-dm-surface-2 border border-dm-border">
                  {v.thumbnail && (
                    <img src={v.thumbnail} alt="" className="w-16 h-11 rounded object-cover shrink-0" />
                  )}
                  {!v.thumbnail && (
                    <span className="text-[10px] font-mono text-dm-muted w-5 shrink-0 mt-0.5">{i + 1}</span>
                  )}
                  <div className="min-w-0 flex-1">
                    <div className="flex items-start justify-between gap-1">
                      <div className="text-xs font-medium text-dm-text line-clamp-2">{v.title}</div>
                      {v.video_id && (
                        <a
                          href={`https://www.youtube.com/watch?v=${v.video_id}`}
                          target="_blank"
                          rel="noopener noreferrer"
                          className="shrink-0 text-dm-muted hover:text-red-400 transition-colors"
                        >
                          <ExternalLink size={11} />
                        </a>
                      )}
                    </div>
                    {v.channel && (
                      <div className="text-[10px] text-dm-muted font-mono mt-0.5 truncate">{v.channel}</div>
                    )}
                    <div className="flex gap-1.5 mt-1.5 flex-wrap">
                      {(v.categories ?? []).slice(0, 2).map(cat => (
                        <span key={cat} className={clsx('dm-badge text-[9px]', CATEGORY_COLORS[cat] ?? 'bg-dm-surface-3 border-dm-border text-dm-muted')}>
                          {cat}
                        </span>
                      ))}
                    </div>
                  </div>
                </div>
              ))}
            </div>
          ) : (
            <p className="text-sm text-dm-muted text-center py-8">No study-related videos found.</p>
          )}
        </div>
      </div>

      {data.technical_count > 0 && (
        <div className="dm-card p-5 border-dm-purple/20 bg-dm-purple-dim">
          <div className="flex items-center gap-2 mb-3">
            <div className="w-2 h-2 rounded-full bg-dm-purple animate-pulse-slow" />
            <span className="text-sm font-semibold text-dm-purple-ll">Learning Insight</span>
          </div>
          <p className="text-sm text-dm-text/80 leading-relaxed">
            {techPct >= 50
              ? `Impressive — ${techPct}% of your content is technical. Your learning is consistent and focused.`
              : `${techPct}% of your content is technical. Consider increasing structured learning sessions to accelerate growth.`
            }
          </p>
          <p className="text-xs text-dm-muted mt-2 font-mono">
            Top topic: {Object.entries(data.categories).sort((a, b) => b[1] - a[1])[0]?.[0] ?? 'N/A'}
          </p>
        </div>
      )}
    </div>
  )
}

type Tab = 'liked' | 'history'

export default function YouTube() {
  const navigate = useNavigate()
  const userId   = useUserId()
  const [tab, setTab] = useState<Tab>('liked')

  const [likedData,    setLikedData]    = useState<YouTubeLikedData | null>(null)
  const [likedLoading, setLikedLoading] = useState(false)
  const [likedError,   setLikedError]   = useState('')

  const [historyData,    setHistoryData]    = useState<YouTubeAnalysis | null>(null)
  const [historyLoading, setHistoryLoading] = useState(false)
  const [historyError,   setHistoryError]   = useState('')
  const [dragging,       setDragging]       = useState(false)
  const fileInputRef = useRef<HTMLInputElement>(null)

  useEffect(() => {
    if (userId) fetchLiked()
  }, [userId])

  async function fetchLiked() {
    if (!userId) return
    setLikedLoading(true)
    setLikedError('')
    try {
      const data = await api.youtubeLiked(userId)
      setLikedData(data)
    } catch (e: unknown) {
      setLikedError(e instanceof Error ? e.message : 'Failed to load liked videos')
    } finally {
      setLikedLoading(false)
    }
  }

  const processFile = useCallback(async (file: File) => {
    if (!userId) return
    if (!file.name.endsWith('.json') && file.type !== 'application/json') {
      setHistoryError('Please upload a .json file from Google Takeout')
      return
    }
    setHistoryLoading(true)
    setHistoryError('')
    try {
      const result = await api.uploadYoutubeHistory(userId, file)
      if (result.error) setHistoryError(result.error)
      else setHistoryData(result)
    } catch (e: unknown) {
      setHistoryError(e instanceof Error ? e.message : 'Upload failed')
    } finally {
      setHistoryLoading(false)
    }
  }, [userId])

  function handleDrop(e: React.DragEvent) {
    e.preventDefault()
    setDragging(false)
    const file = e.dataTransfer.files[0]
    if (file) processFile(file)
  }

  function handleFileInput(e: React.ChangeEvent<HTMLInputElement>) {
    const file = e.target.files?.[0]
    if (file) processFile(file)
    e.target.value = ''
  }

  if (!userId) {
    return (
      <div className="min-h-screen bg-dm-bg flex items-center justify-center px-6">
        <div className="text-center max-w-sm">
          <div className="w-14 h-14 rounded-2xl bg-red-500/10 flex items-center justify-center mx-auto mb-5">
            <Youtube size={24} className="text-red-400" />
          </div>
          <h2 className="font-head font-bold text-xl text-dm-text mb-2">Sign in required</h2>
          <p className="text-dm-muted text-sm mb-5">Log in to analyse your YouTube activity.</p>
          <button onClick={() => navigate('/login')} className="dm-btn-primary flex items-center gap-2 mx-auto text-sm">
            Sign in <ChevronRight size={13} />
          </button>
        </div>
      </div>
    )
  }

  return (
    <PageShell
      title="YouTube Study Analyser"
      subtitle="AI-filtered view of your technical learning content"
      actions={
        <div className="flex items-center gap-2">
          {tab === 'liked' && (
            <button onClick={fetchLiked} className="dm-btn-ghost flex items-center gap-2 text-sm" disabled={likedLoading}>
              <RefreshCw size={14} className={likedLoading ? 'animate-spin' : ''} /> Refresh
            </button>
          )}
          {tab === 'history' && historyData && (
            <button onClick={() => { setHistoryData(null); setHistoryError('') }} className="dm-btn-ghost flex items-center gap-2 text-sm">
              <RefreshCw size={14} /> Upload new file
            </button>
          )}
        </div>
      }
    >
      {/* Tabs */}
      <div className="flex gap-1 mb-6 p-1 rounded-xl bg-dm-surface-2 border border-dm-border w-fit">
        <button
          onClick={() => setTab('liked')}
          className={clsx(
            'flex items-center gap-2 px-4 py-2 rounded-lg text-sm font-medium transition-all duration-150',
            tab === 'liked'
              ? 'bg-dm-purple text-white shadow-glow-sm'
              : 'text-dm-muted hover:text-dm-text',
          )}
        >
          <ThumbsUp size={14} /> Liked Videos
        </button>
        <button
          onClick={() => setTab('history')}
          className={clsx(
            'flex items-center gap-2 px-4 py-2 rounded-lg text-sm font-medium transition-all duration-150',
            tab === 'history'
              ? 'bg-dm-purple text-white shadow-glow-sm'
              : 'text-dm-muted hover:text-dm-text',
          )}
        >
          <FileJson size={14} /> Watch History
        </button>
      </div>

      {/* -- Liked Videos tab -- */}
      {tab === 'liked' && (
        <>
          {likedLoading ? (
            <LoadingSpinner fullPage label="Fetching your liked videos from YouTube..." />
          ) : likedError ? (
            <div className="dm-card p-8 text-center max-w-md mx-auto">
              <Youtube size={32} className="text-red-400 mx-auto mb-3" />
              <div className="text-dm-text font-semibold mb-1">Could not load liked videos</div>
              <div className="text-sm text-dm-muted mb-4">{likedError}</div>
              <button onClick={fetchLiked} className="dm-btn-primary text-sm mx-auto flex items-center gap-2">
                <RefreshCw size={13} /> Try again
              </button>
            </div>
          ) : likedData ? (
            likedData.total === 0 ? (
              <div className="dm-card p-8 text-center max-w-md mx-auto">
                <ThumbsUp size={32} className="text-dm-muted mx-auto mb-3" />
                <div className="text-dm-text font-semibold mb-1">No liked videos found</div>
                <p className="text-sm text-dm-muted">Your YouTube liked videos list appears to be empty or private.</p>
              </div>
            ) : (
              <AnalysisResults
                data={{ ...likedData, total: likedData.total }}
                totalLabel="Liked Videos"
              />
            )
          ) : null}
        </>
      )}

      {/* -- Watch History tab -- */}
      {tab === 'history' && (
        <>
          <div className="dm-card p-4 mb-6 flex items-start gap-3">
            <Info size={15} className="text-dm-cyan mt-0.5 shrink-0" />
            <div className="text-xs text-dm-muted leading-relaxed">
              <span className="text-dm-text font-semibold">How to get your watch history: </span>
              Go to <span className="text-dm-cyan font-mono">myaccount.google.com → Data &amp; privacy → Download your data</span>.
              Select only <strong>YouTube</strong>, choose JSON format.
              Inside the archive, find <span className="font-mono text-dm-text">Takeout/YouTube and YouTube Music/history/watch-history.json</span>.
            </div>
          </div>

          {historyLoading ? (
            <LoadingSpinner fullPage label="Parsing your watch history for technical content..." />
          ) : !historyData ? (
            <div className="max-w-2xl mx-auto">
              <div
                onDragOver={e => { e.preventDefault(); setDragging(true) }}
                onDragLeave={() => setDragging(false)}
                onDrop={handleDrop}
                onClick={() => fileInputRef.current?.click()}
                className={clsx(
                  'dm-card p-16 flex flex-col items-center justify-center gap-6 text-center cursor-pointer',
                  'border-2 border-dashed transition-all duration-200',
                  dragging
                    ? 'border-dm-purple/70 bg-dm-purple/10 shadow-glow scale-[1.01]'
                    : 'border-dm-border hover:border-dm-purple/40 hover:bg-dm-surface-2/50',
                )}
              >
                <div className={clsx('w-20 h-20 rounded-2xl flex items-center justify-center transition-colors duration-200', dragging ? 'bg-dm-purple/20' : 'bg-dm-surface-2')}>
                  {dragging ? <FileJson size={36} className="text-dm-purple-ll" /> : <Upload size={36} className="text-dm-muted" />}
                </div>
                <div>
                  <div className="font-head font-semibold text-lg text-dm-text mb-2">
                    {dragging ? 'Release to upload' : 'Drop watch-history.json here'}
                  </div>
                  <div className="text-sm text-dm-muted">or click to browse your files</div>
                  <div className="mt-3 flex gap-2 justify-center flex-wrap">
                    {['Algorithms', 'Python', 'System Design', 'LeetCode', 'ML / AI'].map(k => (
                      <span key={k} className="dm-badge bg-dm-surface-2 border-dm-border text-dm-muted text-[10px]">{k}</span>
                    ))}
                  </div>
                  <div className="text-xs text-dm-dim mt-3 font-mono">Accepts .json · Max 50 MB · Processed on-server</div>
                </div>
                <div className="flex items-center gap-3">
                  <Youtube size={16} className="text-red-500" />
                  <span className="text-xs text-dm-muted">Google Takeout format supported</span>
                </div>
              </div>

              {historyError && (
                <div className="mt-4 p-4 rounded-xl bg-red-500/10 border border-red-400/30 text-sm text-red-400">
                  {historyError}
                </div>
              )}

              <input ref={fileInputRef} type="file" accept=".json,application/json" onChange={handleFileInput} className="hidden" />
            </div>
          ) : (
            <AnalysisResults
              data={{
                total:           historyData.total_watched,
                technical_count: historyData.technical_count,
                categories:      historyData.categories,
                top_videos:      historyData.top_videos,
              }}
              totalLabel="Total Watched"
            />
          )}
        </>
      )}
    </PageShell>
  )
}
