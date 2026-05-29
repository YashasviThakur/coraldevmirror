<div align="center">

<img src="https://img.shields.io/badge/version-2.0.8-6366f1?style=flat-square" />
<img src="https://img.shields.io/badge/deployed-netlify-00C7B7?style=flat-square&logo=netlify&logoColor=white" />
<img src="https://img.shields.io/badge/backend-railway-0B0D0E?style=flat-square&logo=railway&logoColor=white" />
<img src="https://img.shields.io/badge/AI-Cohere-coral?style=flat-square" />
<img src="https://img.shields.io/badge/data-Coral_SQL-ff6b35?style=flat-square" />
<img src="https://img.shields.io/badge/license-MIT-f59e0b?style=flat-square" />

<br /><br />

# DevMirror

### Not your critic. Your coach.

One dashboard for your GitHub, LeetCode, Codeforces, Gmail, YouTube, and Google Calendar —  
with an AI coach that actually knows your goals and can schedule your week.

<br />

[**Live Demo →**](https://devmirrorcoral.netlify.app) &nbsp;·&nbsp; [**Report a Bug**](https://github.com/YashasviThakur/DevMirror/issues) &nbsp;·&nbsp; [**Request a Feature**](https://github.com/YashasviThakur/DevMirror/issues)

</div>

---

## What is DevMirror?

Most developers have 6 tabs open just to check their own progress — GitHub here, LeetCode there, emails buried somewhere else. DevMirror collapses all of that into one place, adds an AI coach that knows your actual goals, and tells you what to focus on today.

Built for the **WeMakeDevs Pirates of the Coral-bean Hackathon** (May 2026).  
The theme was **Coral** — a tool that lets you query any REST API using SQL. We used it as the data layer connecting all our external data sources.

---

## Features

### Dashboard
- GitHub contribution grid, top repositories, commit activity, language breakdown
- LeetCode solved count, difficulty breakdown (Easy / Medium / Hard), recent submissions with verdict
- Codeforces rating, rank, solved count, recent submission verdicts
- Google Calendar upcoming events for the week
- Editable focus goal cards — your 3 personal development goals, always visible

### Gmail Radar
- Filters your inbox automatically for **internships, hackathons, and scholarships**
- AI-generated one-line summary per email (Cohere)
- Category filter chips (All / Internship / Hackathon / Scholarship)
- Direct deep-link into Gmail for any message

### YouTube Analyser
- Queries your **liked videos** via YouTube Data API
- Classifies each video as technical or non-technical using Cohere/Gemini + keyword fallback
- Detailed category breakdown: DSA, Web Dev, System Design, DevOps, ML/AI, etc.
- Bar charts showing time split between learning and entertainment

### Calendar
- Full Google Calendar view — upcoming events grouped by date
- **AI Planner**: type in plain English ("Plan 3 DSA sessions this week") and events are created directly on your Google Calendar
- Optimistic UI — new events appear instantly without waiting for a page reload
- Powered by Cohere; responses are friendly and conversational, not raw JSON

### AI Coach
- Powered by **Cohere** (`command-r-plus-08-2024`) — knows your 3 goals and your live data
- Ask anything: *"What should I focus on today?"*, *"Review Kunal Kushwaha's DSA course"*, *"Plan my GSoC 2026 prep"*
- Scheduling requests are detected and create real Google Calendar events
- Course/resource questions get structured answers with community consensus and a concrete next step
- Temperature tuned to 0.3 to reduce hallucinations

### Focus Today
- AI-generated daily recommendation based on your LeetCode streak, Codeforces rating, calendar, and YouTube activity
- Priority task card with reasoning
- Today's scheduled sessions pulled from Google Calendar
- Technical YouTube videos watched recently

### Growth Report
- AI-generated weekly progress report (Cohere) based on all your live data
- Upcoming calendar sessions listed for context

### DSA Progress
- Combined LeetCode + Codeforces view
- Streak tracking, acceptance rate, difficulty breakdown
- Recent submission list with AC (green) / wrong (red) verdict indicators

### Learn vs Build
- AI analysis of how you balance learning (courses, DSA) vs building (GitHub commits, projects)
- 6-week trend chart generated from your activity data

---

## Tech Stack

| Layer | Technology |
|---|---|
| Frontend | React 18, TypeScript, Tailwind CSS v3, Vite 5 |
| Charts | Recharts |
| Icons | Lucide React |
| Routing | React Router v6 |
| Backend | FastAPI, Python 3.11+, Uvicorn |
| ORM | SQLAlchemy 2.0 |
| Database | SQLite (dev) · PostgreSQL (prod on Railway) |
| Auth | Google OAuth2 (PKCE flow via `google-auth-oauthlib`) |
| Token security | `cryptography.fernet` — all OAuth tokens AES-encrypted at rest |
| Primary AI | Cohere `command-r-plus-08-2024` |
| Fallback AI | Gemini 2.5 Flash (when Cohere is unavailable) |
| Data layer | **Coral SQL** — queries REST APIs via SQL |
| Deploy | Netlify (frontend) · Railway (backend) |

---

## How Coral SQL is Used

[Coral](https://withcoral.com) is the core of the hackathon theme. It lets you write SQL queries against REST APIs — Coral handles the HTTP calls, pagination, and JSON parsing under the hood.

### Architecture

```
Frontend  →  FastAPI (main.py)  →  coral_client.py  →  Coral CLI subprocess  →  REST APIs
                                ↓
                          (fallback if Coral not installed)
                          Direct requests calls
```

`coral_client.py` wraps the Coral CLI by running `coral sql --format json "<query>"` as a subprocess and returning the parsed rows. If Coral is unavailable, every function returns `None` and `main.py` falls back to direct API calls — so the app always works.

OAuth tokens are passed as **environment variables at call time** (e.g. `GMAIL_ACCESS_TOKEN`, `YOUTUBE_ACCESS_TOKEN`) so each user's data stays isolated and tokens never appear in the SQL strings.

### Coral Source YAML Files

Four custom Coral source definitions live in `devmirror-api/coral_sources/`. Each YAML tells Coral how to map SQL tables to API endpoints.

#### `codeforces.yaml`
Queries the public Codeforces API — no token required.

| SQL Table | API Endpoint | Key Columns |
|---|---|---|
| `codeforces.user_info` | `/api/user.info` | `handle`, `rating`, `rank`, `max_rating` |
| `codeforces.submissions` | `/api/user.status` | `verdict`, `problem_name`, `problem_rating`, `language` |
| `codeforces.rating_history` | `/api/user.rating` | `contest_name`, `old_rating`, `new_rating` |
| `codeforces.contests` | `/api/contest.list` | `name`, `phase`, `start_time_seconds` |

Input variable: `CODEFORCES_HANDLE` (injected into query path via `{{input.CODEFORCES_HANDLE}}`).

#### `youtube.yaml`
Queries the YouTube Data API v3. Auth via `YOUTUBE_ACCESS_TOKEN` injected as `Authorization: Bearer` header.

| SQL Table | API Endpoint | Key Columns |
|---|---|---|
| `youtube.liked_videos` | `/playlistItems?playlistId=LL` | `video_id`, `title`, `channel_title`, `liked_at`, `position` |
| `youtube.playlists` | `/playlists?mine=true` | `id`, `title`, `item_count`, `privacy_status` |
| `youtube.channels` | `/channels?mine=true` | `title`, `subscriber_count`, `video_count`, `view_count` |

`liked_videos` is actively used — it feeds the YouTube Analyser page. Coral fetches the top 50 liked videos; Cohere/Gemini then classifies them as technical or non-technical.

#### `gmail.yaml`
Queries the Gmail API. Auth via `GMAIL_ACCESS_TOKEN`.

| SQL Table | API Endpoint | Key Columns |
|---|---|---|
| `gmail.profile` | `/users/me/profile` | `emailAddress`, `messagesTotal`, `threadsTotal` |
| `gmail.labels` | `/users/me/labels` | `id`, `name`, `type` |
| `gmail.messages` | `/users/me/messages` | `id`, `threadId` — supports `q` filter (Gmail search syntax) |
| `gmail.threads` | `/users/me/threads` | `id`, `snippet` — supports `q` filter |

The `q` filter maps directly to Gmail search syntax, e.g.:  
`SELECT id, snippet FROM gmail.threads WHERE q = 'subject:internship OR subject:hackathon'`

#### `google_calendar.yaml`
Queries the Google Calendar API. Auth via `GOOGLE_CALENDAR_ACCESS_TOKEN`. Includes full OAuth 2.0 PKCE flow definition for local Coral CLI use.

| SQL Table | API Endpoint | Key Columns |
|---|---|---|
| `google_calendar.calendars` | `/users/me/calendarList` | `id`, `summary`, `time_zone`, `primary` |
| `google_calendar.events` | `/calendars/{id}/events` | `summary`, `description`, `start_date_time`, `end_date_time`, `location`, `html_link` |
| `google_calendar.settings` | `/users/me/settings` | `id`, `value` |

`events` supports `time_min`, `time_max`, and `q` filters and uses cursor-based pagination (`pageToken`).

> **Note:** The Calendar page now bypasses Coral and always fetches live from the Google Calendar API directly — Coral's internal cache was stale and would miss newly scheduled events. The YAML remains for documentation and potential future use.

---

## Project Structure

```
DevMirror/
│
├── README.md
├── devmirror-landing.html          # Static landing page (no framework)
│
├── devmirror-api/                  # FastAPI backend
│   ├── main.py                     # All API routes, data fetchers, AI logic
│   ├── models.py                   # SQLAlchemy ORM models (User, LinkedAccount)
│   ├── auth_router.py              # Google OAuth2 flow + token refresh
│   ├── coral_client.py             # Thin Coral CLI wrapper (subprocess → SQL → JSON)
│   ├── refresh_coral_tokens.py     # Utility to refresh Google OAuth tokens
│   ├── requirements.txt
│   ├── .env.example
│   └── coral_sources/              # Coral DSL v3 source definitions
│       ├── codeforces.yaml
│       ├── youtube.yaml
│       ├── gmail.yaml
│       └── google_calendar.yaml
│
└── devmirror-frontend/             # React + Vite frontend
    ├── index.html
    ├── vite.config.ts              # Dev proxy: /api → localhost:8000
    ├── tailwind.config.js
    ├── .env / .env.example
    └── src/
        ├── App.tsx                 # Router setup + ErrorBoundary
        ├── main.tsx
        │
        ├── api/
        │   └── client.ts           # All API calls + TypeScript interfaces
        │
        ├── hooks/
        │   └── useUserId.ts        # Read userId from localStorage
        │
        ├── components/
        │   ├── Sidebar.tsx         # Navigation + user profile
        │   ├── PageShell.tsx       # Layout wrapper (Sidebar + main area)
        │   ├── AIReport.tsx        # Typing-animation AI text renderer
        │   ├── LoadingSpinner.tsx  # Reusable loading state
        │   └── StatCard.tsx        # Metric card with icon + value
        │
        └── pages/
            ├── Landing.tsx         # Public landing page
            ├── Login.tsx           # Google OAuth sign-in
            ├── Dashboard.tsx       # Main overview (GitHub + LeetCode + CF + Calendar)
            ├── Gmail.tsx           # Gmail Radar (opportunity filter + AI summary)
            ├── YouTube.tsx         # YouTube analyser (technical vs entertainment)
            ├── Calendar.tsx        # Google Calendar view + AI Planner chat
            ├── Coach.tsx           # AI Coach chat interface
            ├── FocusToday.tsx      # Daily AI recommendation
            ├── GrowthReport.tsx    # Weekly AI progress report
            ├── DSAProgress.tsx     # LeetCode + Codeforces combined view
            ├── LearnVsBuild.tsx    # Learn vs build balance + trend chart
            └── Internship.tsx      # Internship opportunity tracker
```

---

## Backend — `main.py` at a Glance

`main.py` is the single backend file. Key sections:

| Section | What it does |
|---|---|
| `_get_demo_google_token()` | Retrieves the stored Google OAuth token from DB, auto-refreshes if expired |
| `_fetch_github()` | Calls GitHub REST API v3 — repos, commit events, languages, contribution streak |
| `_fetch_leetcode()` | Calls LeetCode GraphQL API — solved counts, streak, recent submissions |
| `_fetch_codeforces()` / `_fetch_codeforces_direct()` | Codeforces public API — rating, rank, submission history (normalises `"OK"` → `"AC"`) |
| `_fetch_gmail()` | Gmail API — filters for internship/hackathon/scholarship emails, calls Cohere for AI summaries |
| `_fetch_youtube_liked()` | YouTube API → Coral SQL first, then classifies videos via Cohere/Gemini + keyword fallback |
| `_fetch_calendar_events()` | Google Calendar API — upcoming events, sorted by start time |
| `_create_calendar_event()` | Creates an event on the user's primary Google Calendar |
| `call_ai()` | Cohere-first AI call with Gemini fallback; 1-hour response cache |
| `/api/agent/ask` | AI Coach endpoint — parses JSON from AI response to detect + create calendar events, returns friendly confirmation |
| `/api/coral/calendar` | Always fetches live Google Calendar (bypasses Coral cache) |
| `/api/focus` | Aggregates LeetCode + CF + Calendar + YouTube data → AI recommendation |
| `/api/growth-report` | Weekly AI report with upcoming sessions |
| `/api/learn-vs-build` | AI analysis + 6-week trend generation |

---

## AI Pipeline

```
User message
     │
     ▼
call_ai(system_prompt, message)
     │
     ├── Try Cohere (command-r-plus-08-2024, temp=0.3)
     │       │
     │       ├── Success → cache 1 hour → return response
     │       │
     │       └── Rate-limited / error
     │
     └── Fallback: Gemini 2.5 Flash (temp=0.3)
             │
             └── cache 1 hour → return response
```

The system prompt is built from the user's live goals and today's date. It includes accuracy rules that tell the model not to invent specific facts (channel names, URLs, enrollment figures) it can't verify from training data.

For **calendar scheduling**, the AI returns a raw JSON array of events. The backend detects this, creates each event via the Google Calendar API, then replaces the raw JSON with a friendly human-readable confirmation before sending it to the frontend.

---

## Getting Started

### Prerequisites

- Python 3.11+
- Node.js 18+
- A Google Cloud project with OAuth2 credentials (Gmail + Calendar + YouTube scopes)
- A Cohere API key
- (Optional) Coral CLI installed for SQL-based data access

### 1. Clone the repo

```bash
git clone https://github.com/YashasviThakur/DevMirror.git
cd DevMirror
```

### 2. Backend setup

```bash
cd devmirror-api
python -m venv venv
source venv/bin/activate   # Windows: venv\Scripts\activate
pip install -r requirements.txt
```

Copy and fill the env file:

```bash
cp .env.example .env
```

```env
GOOGLE_CLIENT_ID=your_client_id
GOOGLE_CLIENT_SECRET=your_client_secret
GOOGLE_REDIRECT_URI=http://localhost:8000/api/auth/google/callback
FERNET_KEY=         # python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
COHERE_API_KEY=your_cohere_key
GEMINI_API_KEY=your_gemini_key   # optional fallback
FRONTEND_URL=http://localhost:5173
DATABASE_URL=sqlite:///./devmirror.db
```

Start the backend:

```bash
uvicorn main:app --reload
```

### 3. Frontend setup

```bash
cd devmirror-frontend
npm install
cp .env.example .env.local
# VITE_API_URL=   (leave empty — Vite proxy forwards /api to localhost:8000)
npm run dev
```

Open [http://localhost:5173](http://localhost:5173) and sign in with Google.

---

## Environment Variables

### Backend (`devmirror-api/.env`)

| Variable | Required | Description |
|---|---|---|
| `GOOGLE_CLIENT_ID` | Yes | Google OAuth2 client ID |
| `GOOGLE_CLIENT_SECRET` | Yes | Google OAuth2 client secret |
| `GOOGLE_REDIRECT_URI` | Yes | Must match Google Cloud Console exactly |
| `FERNET_KEY` | Yes | AES encryption key for stored OAuth tokens |
| `COHERE_API_KEY` | Yes | Primary AI — Cohere API key |
| `GEMINI_API_KEY` | No | Fallback AI — Gemini API key |
| `FRONTEND_URL` | Yes | Frontend origin (CORS) |
| `DATABASE_URL` | No | Defaults to `sqlite:///./devmirror.db` |
| `GMAIL_REFRESH_TOKEN` | No | Pre-loaded demo Google token (Railway) |
| `CALENDAR_REFRESH_TOKEN` | No | Pre-loaded demo Google token (Railway) |
| `YOUTUBE_REFRESH_TOKEN` | No | Pre-loaded demo Google token (Railway) |

### Frontend (`devmirror-frontend/.env.local`)

| Variable | Required | Description |
|---|---|---|
| `VITE_API_URL` | No | Backend URL — empty in dev (Vite proxy), Railway URL in prod |

---

## Contributing

1. Fork the repository
2. Create a feature branch: `git checkout -b feat/your-feature`
3. Commit: `git commit -m 'feat: add your feature'`
4. Push: `git push origin feat/your-feature`
5. Open a Pull Request

Please open an issue first for major changes.

---

## Roadmap

- [ ] Mobile-responsive layout
- [ ] Shareable public profile link
- [ ] Weekly email digest
- [ ] GitHub Actions / CI pipeline stats
- [ ] Institution dashboard (aggregate analytics)

---

<div align="center">

Built by [Yashasvi Thakur](https://github.com/YashasviThakur) &nbsp;·&nbsp; Powered by [Cohere](https://cohere.com) &nbsp;·&nbsp; Data via [Coral SQL](https://withcoral.com)

⭐ Star this repo if DevMirror helped you — it means a lot.

</div>
