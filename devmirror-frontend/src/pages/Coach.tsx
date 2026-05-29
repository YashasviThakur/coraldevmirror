import { useState, useRef, useEffect, ReactElement } from 'react'
import {
  Terminal, Send, CalendarCheck, RefreshCw,
  ChevronRight, LogIn, Bot,
} from 'lucide-react'
import clsx from 'clsx'
import PageShell from '../components/PageShell'
import { api, ChatMessage, ChatResponse } from '../api/client'
import { useUserId } from '../hooks/useUserId'
import { useNavigate } from 'react-router-dom'

// -- Simple safe markdown renderer ---------------------------------------------
function MarkdownLine({ text }: { text: string }) {
  if (text.startsWith('## ')) {
    return <div className="text-dm-text font-semibold text-sm mt-2 mb-0.5">{text.slice(3)}</div>
  }
  if (text.startsWith('# ')) {
    return <div className="text-dm-purple-ll font-bold text-base mt-3 mb-1">{text.slice(2)}</div>
  }
  if (text.startsWith('- ') || text.startsWith('* ')) {
    return <div className="text-dm-text text-sm pl-3 flex gap-2"><span className="text-dm-purple-ll shrink-0">•</span><span>{renderInline(text.slice(2))}</span></div>
  }
  if (text.startsWith('> ')) {
    return (
      <div className="text-dm-muted text-sm border-l-2 border-dm-purple/40 pl-3 italic">
        {renderInline(text.slice(2))}
      </div>
    )
  }
  if (text === '') return <div className="h-1" />
  return <div className="text-dm-text text-sm leading-relaxed">{renderInline(text)}</div>
}

function renderInline(text: string): (ReactElement | string)[] {
  const parts = text.split(/(\*\*[^*]+\*\*|`[^`]+`)/g)
  return parts.map((part, i) => {
    if (part.startsWith('**') && part.endsWith('**')) {
      return <strong key={i} className="text-dm-purple-ll font-semibold">{part.slice(2, -2)}</strong>
    }
    if (part.startsWith('`') && part.endsWith('`')) {
      return (
        <code key={i} className="font-mono text-dm-cyan bg-dm-surface-2 px-1 py-0.5 rounded text-[11px]">
          {part.slice(1, -1)}
        </code>
      )
    }
    return part
  })
}

function MarkdownContent({ content }: { content: string }) {
  return (
    <div className="space-y-0.5">
      {content.split('\n').map((line, i) => (
        <MarkdownLine key={i} text={line} />
      ))}
    </div>
  )
}

// -- Scheduled events summary ---------------------------------------------------
function ScheduledEvents({ events }: { events: ChatResponse['scheduled_events'] }) {
  if (!events.length) return null
  return (
    <div className="mt-3 p-3 rounded-lg bg-dm-green/10 border border-dm-green/25">
      <div className="flex items-center gap-2 mb-2">
        <CalendarCheck size={13} className="text-dm-green" />
        <span className="text-xs font-semibold text-dm-green">
          {events.length} event{events.length > 1 ? 's' : ''} added to Google Calendar
        </span>
      </div>
      <div className="space-y-1">
        {events.map((ev, i) => (
          <div key={i} className="flex items-center gap-2 text-xs text-dm-muted">
            <span className="w-1 h-1 rounded-full bg-dm-green shrink-0" />
            <span className="text-dm-text">{ev.summary}</span>
            <span className="font-mono ml-auto">
              {new Date(ev.start).toLocaleDateString('en-US', { month: 'short', day: 'numeric' })}
            </span>
          </div>
        ))}
      </div>
    </div>
  )
}

// -- Chat bubble ----------------------------------------------------------------
function ChatBubble({ msg, response }: { msg: ChatMessage; response?: ChatResponse }) {
  const isUser = msg.role === 'user'
  return (
    <div className={clsx('flex gap-3 items-start', isUser && 'flex-row-reverse')}>
      <div className={clsx(
        'w-7 h-7 rounded-lg flex items-center justify-center shrink-0 mt-0.5',
        isUser ? 'bg-dm-surface-2 border border-dm-border' : 'bg-dm-purple shadow-glow-sm',
      )}>
        {isUser
          ? <span className="text-xs font-bold text-dm-muted">U</span>
          : <Bot size={14} className="text-white" />
        }
      </div>

      <div className={clsx(
        'max-w-[78%] rounded-xl px-4 py-3',
        isUser
          ? 'bg-dm-surface-2 border border-dm-border text-dm-text text-sm'
          : 'bg-dm-surface border border-dm-purple/20',
      )}>
        {isUser ? (
          <span className="text-sm">{msg.content}</span>
        ) : (
          <>
            <MarkdownContent content={msg.content} />
            {response && <ScheduledEvents events={response.scheduled_events} />}
          </>
        )}
      </div>
    </div>
  )
}

// -- Suggestion chips -----------------------------------------------------------
const SUGGESTIONS = [
  'What should I focus on today?',
  'Schedule my study plan for this week',
  'How can I improve my LeetCode streak?',
  'Analyse my learn vs build balance',
  'Plan my GSoC 2026 preparation',
]

// -- Main Coach component -------------------------------------------------------
export default function Coach() {
  const navigate = useNavigate()
  const userId   = useUserId()

  const [messages,  setMessages]  = useState<ChatMessage[]>([])
  const [responses, setResponses] = useState<Map<number, ChatResponse>>(new Map())
  const [input,     setInput]     = useState('')
  const [loading,   setLoading]   = useState(false)

  const bottomRef = useRef<HTMLDivElement>(null)
  const inputRef  = useRef<HTMLTextAreaElement>(null)

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [messages])

  async function sendMessage(text: string) {
    if (!userId || !text.trim() || loading) return

    const userMsg: ChatMessage = { role: 'user', content: text.trim() }
    setMessages(prev => [...prev, userMsg])
    setInput('')
    setLoading(true)

    try {
      const res     = await api.ask(userId, text.trim())
      const asstMsg: ChatMessage = { role: 'assistant', content: res.response }
      setMessages(prev => {
        const next = [...prev, asstMsg]
        setResponses(r => new Map(r).set(next.length - 1, res))
        return next
      })
    } catch (e: unknown) {
      const msg = e instanceof Error ? e.message : 'Unknown error'
      if (msg.includes('User not found')) {
        navigate('/login')
        return
      }
      const errMsg: ChatMessage = {
        role: 'assistant',
        content: `I encountered an error: ${msg}. Please try again.`,
      }
      setMessages(prev => [...prev, errMsg])
    } finally {
      setLoading(false)
      setTimeout(() => inputRef.current?.focus(), 50)
    }
  }

  function handleKeyDown(e: React.KeyboardEvent<HTMLTextAreaElement>) {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault()
      sendMessage(input)
    }
  }

  if (!userId) {
    return (
      <div className="min-h-screen bg-dm-bg flex items-center justify-center px-6">
        <div className="text-center max-w-sm">
          <div className="w-14 h-14 rounded-2xl bg-dm-purple/15 flex items-center justify-center mx-auto mb-5">
            <LogIn size={24} className="text-dm-purple-ll" />
          </div>
          <h2 className="font-head font-bold text-xl text-dm-text mb-2">Sign in to chat with your coach</h2>
          <p className="text-dm-muted text-sm mb-5">The AI Coach uses your real goals and data to give personalised advice.</p>
          <button onClick={() => navigate('/login')} className="dm-btn-primary flex items-center gap-2 mx-auto text-sm">
            Sign in <ChevronRight size={13} />
          </button>
        </div>
      </div>
    )
  }

  return (
    <PageShell
      title="AI Coach"
      subtitle="Powered by Cohere · Knows your goals · Can schedule Calendar events"
    >
      <div className="flex flex-col h-[calc(100vh-7rem)]">
        {/* Chat terminal */}
        <div className="flex-1 dm-card overflow-hidden flex flex-col min-h-0">
          {/* Terminal bar */}
          <div className="flex items-center gap-2 px-4 py-3 border-b border-dm-border bg-dm-surface-2/60 shrink-0">
            <Terminal size={13} className="text-dm-muted" />
            <span className="text-xs text-dm-muted font-mono">devmirror:~/coach</span>
            <span className="ml-auto dm-badge-purple text-[10px]">Cohere</span>
          </div>

          {/* Messages */}
          <div className="flex-1 overflow-y-auto p-5 space-y-5 min-h-0">
            {messages.length === 0 ? (
              <div className="flex flex-col items-center justify-center h-full gap-6">
                <div className="w-14 h-14 rounded-2xl bg-dm-purple/15 flex items-center justify-center">
                  <Bot size={26} className="text-dm-purple-ll" />
                </div>
                <div className="text-center">
                  <div className="font-head font-semibold text-dm-text mb-1">DevMirror Coach</div>
                  <div className="text-sm text-dm-muted max-w-sm">
                    Your personal AI mentor. Ask about focus, scheduling, DSA, career strategy, or
                    request a study plan to be added directly to your Google Calendar.
                  </div>
                </div>
                <div className="flex flex-wrap gap-2 justify-center max-w-lg">
                  {SUGGESTIONS.map(s => (
                    <button
                      key={s}
                      onClick={() => sendMessage(s)}
                      className="text-xs px-3 py-1.5 rounded-full border border-dm-border text-dm-muted hover:border-dm-purple/40 hover:text-dm-text hover:bg-dm-surface-2 transition-all duration-150"
                    >
                      {s}
                    </button>
                  ))}
                </div>
              </div>
            ) : (
              <>
                {messages.map((msg, i) => (
                  <ChatBubble
                    key={i}
                    msg={msg}
                    response={msg.role === 'assistant' ? responses.get(i) : undefined}
                  />
                ))}
                {loading && (
                  <div className="flex gap-3 items-start">
                    <div className="w-7 h-7 rounded-lg bg-dm-purple shadow-glow-sm flex items-center justify-center shrink-0">
                      <Bot size={14} className="text-white" />
                    </div>
                    <div className="bg-dm-surface border border-dm-purple/20 rounded-xl px-4 py-3">
                      <div className="flex gap-1">
                        <span className="w-1.5 h-1.5 rounded-full bg-dm-purple animate-bounce" style={{ animationDelay: '0ms' }} />
                        <span className="w-1.5 h-1.5 rounded-full bg-dm-purple animate-bounce" style={{ animationDelay: '150ms' }} />
                        <span className="w-1.5 h-1.5 rounded-full bg-dm-purple animate-bounce" style={{ animationDelay: '300ms' }} />
                      </div>
                    </div>
                  </div>
                )}
                <div ref={bottomRef} />
              </>
            )}
          </div>

          {/* Input area */}
          <div className="border-t border-dm-border p-4 shrink-0 bg-dm-surface-2/30">
            {/* Suggestion chips (shown only when there are messages) */}
            {messages.length > 0 && (
              <div className="flex gap-2 flex-wrap mb-3">
                {SUGGESTIONS.slice(0, 3).map(s => (
                  <button
                    key={s}
                    onClick={() => sendMessage(s)}
                    disabled={loading}
                    className="text-[10px] px-2.5 py-1 rounded-full border border-dm-border text-dm-muted hover:border-dm-purple/40 hover:text-dm-text transition-all duration-150 disabled:opacity-40"
                  >
                    {s}
                  </button>
                ))}
              </div>
            )}

            <div className="flex gap-3 items-end">
              <textarea
                ref={inputRef}
                value={input}
                onChange={e => setInput(e.target.value)}
                onKeyDown={handleKeyDown}
                placeholder="Ask your coach? (Enter to send, Shift+Enter for new line)"
                rows={2}
                disabled={loading}
                className={clsx(
                  'flex-1 resize-none dm-input text-sm py-2.5 font-mono',
                  'focus:border-dm-purple/60',
                  loading && 'opacity-60',
                )}
              />
              <button
                onClick={() => sendMessage(input)}
                disabled={loading || !input.trim()}
                className={clsx(
                  'w-10 h-10 rounded-xl flex items-center justify-center shrink-0 transition-all duration-150',
                  input.trim() && !loading
                    ? 'bg-dm-purple hover:bg-dm-purple-l text-white shadow-glow-sm'
                    : 'bg-dm-surface-2 text-dm-muted cursor-not-allowed',
                )}
              >
                {loading
                  ? <RefreshCw size={15} className="animate-spin" />
                  : <Send size={15} />
                }
              </button>
            </div>
            <div className="text-[10px] text-dm-dim font-mono mt-2">
              Scheduling requests automatically create Google Calendar events.
            </div>
          </div>
        </div>
      </div>
    </PageShell>
  )
}
