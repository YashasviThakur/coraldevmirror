const BASE = import.meta.env.VITE_API_URL ?? ''

async function request<T>(path: string, options?: RequestInit): Promise<T> {
  const res = await fetch(`${BASE}${path}`, {
    headers: { 'Content-Type': 'application/json' },
    ...options,
  })
  if (!res.ok) {
    if (res.status === 404) {
      // Stale user_id in localStorage — clear it so the app redirects to login
      clearUserId()
    }
    const err = await res.text()
    throw new Error(err || `HTTP ${res.status}`)
  }
  return res.json() as Promise<T>
}

// -- Session helpers ------------------------------------------------------------
// Coral demo branch: no auth needed — always act as user 1

export function getUserId(): number | null {
  return 1
}

export function setUserId(_id: number): void {}

export function clearUserId(): void {}

// -- Shared types ---------------------------------------------------------------

export interface UserProfile {
  id:                number
  name?:             string
  email:             string
  account_type:      'personal' | 'institution'
  institution_name:  string | null
  goal_1:            string
  goal_2:            string
  goal_3:            string
  created_at:        string | null
  has_google:        boolean
  has_github:        boolean
  github_username:   string | null
  codeforces_handle: string | null
  leetcode_username: string | null
}

export interface GitHubData {
  username:          string
  repos:             number
  commits_week:      number
  top_repo:          string
  languages:         string[]
  contribution_grid: number[][]
  public_repos:      number
  followers:         number
  avatar_url:        string
}

export interface LeetCodeData {
  username:          string
  total_solved:      number
  easy:              number
  medium:            number
  hard:              number
  streak:            number
  total_active_days: number
  acceptance_rate:   number
  ranking:           number
  recent:            { title: string; difficulty: string; date: string }[]
}

export interface CodeForcesData {
  handle:     string
  rating:     number
  max_rating: number
  rank:       string
  max_rank:   string
  solved:     number
  avatar:     string
  recent:     { problem: string; verdict: string; rating: number; date: string }[]
}

export interface GmailEmail {
  id:              string
  subject:         string
  from:            string
  date:            string
  snippet:         string
  category:        'internship' | 'hackathon' | 'scholarship' | 'other'
  ai_summary:      string
  action_required: boolean
  gmail_link:      string
}

export interface GmailData {
  summary: string
  emails:  GmailEmail[]
}

export interface CalendarEvent {
  id:          string
  summary:     string
  description: string
  start:       string
  end:         string
}

export interface CalendarData {
  events: CalendarEvent[]
}

export interface AllData {
  github?:       GitHubData | null
  leetcode?:     LeetCodeData | null
  codeforces?:   CodeForcesData | null
  gmail?:        GmailEmail[] | null
  calendar?:     CalendarEvent[] | null
  generated_at?: string
}

export interface YouTubeAnalysis {
  total_watched:   number
  technical_count: number
  categories:      Record<string, number>
  top_videos:      { title: string; channel: string; categories: string[]; watched_at: string }[]
  error?:          string
}

export interface YouTubeLikedData {
  total:           number
  technical_count: number
  categories:      Record<string, number>
  top_videos:      {
    title:        string
    channel:      string
    categories:   string[]
    thumbnail:    string
    video_id:     string
    published_at: string
  }[]
}

export interface ChatMessage {
  role:    'user' | 'assistant'
  content: string
}

export interface ChatResponse {
  response:         string
  scheduled_events: { id: string; summary: string; start: string; end: string }[]
  is_schedule:      boolean
}

export interface HealthData {
  status:      string
  version:     string
  total_users: number
  sources:     Record<string, 'ok' | 'error' | 'not_configured'>
}

// Backward-compat types (old pages still use these)
export interface DSAData {
  leetcode: {
    username: string; total_solved: number; easy: number; medium: number
    hard: number; streak: number; acceptance_rate: number
    recent: { title: string; difficulty: string; date: string }[]
  }
  codeforces: {
    handle: string; rating: number; max_rating: number; rank: string
    solved: number
    recent: { problem: string; verdict: string; rating: number; date: string }[]
  }
}

export interface GrowthReportData {
  report:       string
  github:       { repos: number; commits_week: number; top_repo: string; languages: string[] }
  leetcode:     { total: number; easy: number; medium: number; hard: number; streak: number }
  codeforces:   { rating: number; rank: string; solved: number }
  calendar:     { study_hours_week: number; upcoming: { title: string; time: string }[] }
  generated_at: string
}

export interface FocusData {
  recommendation:  string
  priority_task:   string
  reasoning:       string
  calendar_today:  { title: string; time: string; duration: string }[]
  youtube_watched: { title: string; channel: string; duration: string }[]
}

export interface LearnVsBuildData {
  analysis:            string
  learn_score:         number
  build_score:         number
  balance:             'learning_heavy' | 'building_heavy' | 'balanced'
  github_commits_week: number
  youtube_hours_week:  number
  study_hours_week:    number
  trend:               { week: string; learn: number; build: number }[]
}

export interface InternshipData {
  summary: string
  emails:  GmailEmail[]
}

// -- API surface ----------------------------------------------------------------

export const api = {
  health: () => request<HealthData>('/api/health'),

  // User profile
  getUser:         (_id: number) => request<UserProfile>(`/api/coral/user`),
  updateGoals:     (id: number, goals: { goal_1?: string; goal_2?: string; goal_3?: string }) =>
                     request<{ success: boolean }>(`/api/user/${id}/goals`, { method: 'PATCH', body: JSON.stringify(goals) }),
  updateHandles:   (id: number, handles: { codeforces_handle?: string; leetcode_username?: string }) =>
                     request<{ success: boolean }>(`/api/user/${id}/handles`, { method: 'PATCH', body: JSON.stringify(handles) }),
  updateGithubToken: (id: number, token: string) =>
                     request<{ success: boolean }>(`/api/user/${id}/github-token`, { method: 'PATCH', body: JSON.stringify({ github_token: token }) }),
  updateGithubUsername: (id: number, username: string) =>
                     request<{ success: boolean }>(`/api/user/${id}/github-username`, { method: 'PATCH', body: JSON.stringify({ github_username: username }) }),

  // Data sources — routed through Coral SQL (no auth needed)
  github:     (_userId: number) => request<GitHubData>(`/api/coral/github`),
  leetcode:   (_userId: number) => request<LeetCodeData>(`/api/coral/leetcode`),
  codeforces: (_userId: number) => request<CodeForcesData>(`/api/coral/codeforces`),
  gmail:      (_userId: number) => request<GmailData>(`/api/coral/gmail`),
  calendar:   (_userId: number) => request<CalendarData>(`/api/coral/calendar`),
  allData:    (_userId: number) => request<AllData>(`/api/coral/all`),

  // YouTube liked videos via Coral SQL
  youtubeLiked: (_userId: number) => request<YouTubeLikedData>(`/api/coral/youtube`),

  // YouTube history upload
  uploadYoutubeHistory: async (userId: number, file: File): Promise<YouTubeAnalysis> => {
    const form = new FormData()
    form.append('file', file)
    const res = await fetch(`${BASE}/api/youtube/upload-history?user_id=${userId}`, { method: 'POST', body: form })
    if (!res.ok) throw new Error(await res.text())
    return res.json()
  },

  // AI coach
  ask: (userId: number, question: string) =>
    request<ChatResponse>('/api/agent/ask', {
      method: 'POST',
      body: JSON.stringify({ user_id: userId, question }),
    }),

  // Backward-compat endpoints — routed to coral/no-auth versions
  dsa:          (_userId?: number) => request<DSAData>(`/api/dsa?user_id=1`),
  growthReport: (_userId?: number) => request<GrowthReportData>(`/api/growth-report?user_id=1`),
  focus:        (_userId?: number) => request<FocusData>(`/api/focus?user_id=1`),
  learnVsBuild: (_userId?: number) => request<LearnVsBuildData>(`/api/learn-vs-build?user_id=1`),
  internship:   (_userId?: number) => request<InternshipData>(`/api/internship?user_id=1`),
}
