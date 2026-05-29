<div align="center">

<img src="https://img.shields.io/badge/version-2.0.8-6366f1?style=flat-square" />
<img src="https://img.shields.io/badge/deployed-netlify-00C7B7?style=flat-square&logo=netlify&logoColor=white" />
<img src="https://img.shields.io/badge/backend-railway-0B0D0E?style=flat-square&logo=railway&logoColor=white" />
<img src="https://img.shields.io/badge/data-coral-f97316?style=flat-square" />
<img src="https://img.shields.io/badge/license-MIT-f59e0b?style=flat-square" />

<br /><br />

# DevMirror

### Not your critic. Your coach.

One dashboard for your GitHub, LeetCode, Codeforces, Gmail, YouTube, and an AI coach that actually knows your goals.

<br />

[**Live Demo →**](https://dev-mirror.netlify.app) &nbsp;·&nbsp; [**Report a Bug**](https://github.com/YashasviThakur/DevMirror/issues) &nbsp;·&nbsp; [**Request a Feature**](https://github.com/YashasviThakur/DevMirror/issues)

</div>

---

## What is DevMirror?

Most developers have 6 tabs open just to check their own progress — GitHub here, LeetCode there, emails buried somewhere else. DevMirror collapses all of that into one place, adds an AI coach that knows your actual goals, and tells you what to focus on today.

Built for the **WeMakeDevs Pirates of the Coral-bean Hackathon** (May 2026).

---

## How Coral Powers DevMirror

DevMirror uses **[Coral](https://withcoral.com)** as its primary data layer — a unified SQL interface that lets you query APIs like they're database tables.

Before Coral, each data source required its own bespoke client: custom HTTP calls, response parsing, field normalization, error handling — repeated for every API. Coral replaced all of that with a single pattern: write a SQL query, get structured rows back. No SDKs, no pagination loops, no per-source boilerplate.

### What Coral handles

| Source | How it's used | Coral type |
|---|---|---|
| **GitHub** | Repos, push events, commit grid, user profile | Bundled connector (362 tables) |
| **Codeforces** | User rating, rank, submissions, solved count | Custom YAML source |
| **Gmail** | Internship / hackathon / scholarship threads | Custom YAML source |
| **YouTube** | Liked videos for technical content analysis | Custom YAML source |

### What this looked like before Coral

Fetching GitHub data used to mean three separate REST calls (user profile, repos, events), manually iterating push events to compute weekly commits, building the 52-week contribution grid by hand, and guarding every field against `undefined`. Each source had its own version of this.

### What it looks like with Coral

```sql
-- GitHub repos — one query, structured rows
SELECT name, language, stargazers_count, updated_at
FROM github.user_repos
WHERE username = 'YashasviThakur'
ORDER BY updated_at DESC LIMIT 10

-- Codeforces submissions — no CF API client needed
SELECT problem_name, problem_index, verdict, submitted_at
FROM codeforces.submissions
ORDER BY submitted_at DESC LIMIT 500

-- Gmail opportunities — SQL filter on live inbox
SELECT id, snippet FROM gmail.threads
WHERE q = 'subject:(internship OR hackathon OR scholarship)'
LIMIT 20

-- YouTube liked videos — direct from the playlist
SELECT video_id, title, channel_title, liked_at
FROM youtube.liked_videos
ORDER BY position ASC LIMIT 50
```

All four sources share the same `coral sql` call pattern. Token passing is handled per-call via environment variables — each user's OAuth token is injected at query time, so there's no shared global config and the same code works for every user.

### Custom YAML sources

Coral supports defining custom API sources as YAML files. DevMirror ships three:

```
devmirror-api/coral_sources/
├── codeforces.yaml   # CF API: user_info, submissions, rating_history, contests
├── gmail.yaml        # Gmail API: threads, profile
└── youtube.yaml      # YouTube API: liked_videos, channel stats
```

Each YAML describes the API endpoints, query parameters, and column mappings. Adding a new data source to DevMirror now means writing a YAML file — not writing a new API client.

### Graceful fallback

Every Coral-powered path in the backend has a direct-API fallback. If Coral isn't installed or returns `None`, the server falls back to the original REST calls — the website always works.

```python
# _fetch_codeforces in main.py
coral_user = coral_client.get_codeforces_user(handle)
if coral_user is not None:
    # Coral path — fast, structured, SQL-driven
    ...
return _fetch_codeforces_direct(handle)  # fallback — always available
```

---

## Features

### Dashboard
- GitHub contribution grid, top repositories, commit activity, languages, followers
- LeetCode solved count, difficulty breakdown, acceptance rate, recent submissions
- Codeforces rating, rank, avatar, recent verdict history
- Google Calendar events for the week ahead
- Editable goal cards (your 3 focus areas, always visible)

### Gmail Radar
- Automatically filters your inbox for **internships, hackathons, and scholarships**
- AI-generated one-line summaries for each opportunity
- Direct deep-link into Gmail for any email

### YouTube Analyser
- Upload your Google Takeout watch history JSON
- See exactly how much of your time was spent on **technical learning vs. entertainment**
- Category breakdown with bar charts

### AI Coach
- Powered by **Gemini 2.5 Flash** (Cohere fallback) — knows your 3 goals and your live data
- Ask anything: *"What should I focus on today?"*, *"How do I improve my LeetCode streak?"*
- Can **schedule study sessions directly to your Google Calendar** from the chat

---

## Tech Stack

| Layer | Technology |
|---|---|
| Frontend | React 18, TypeScript, Tailwind CSS v3, Vite |
| Backend | FastAPI 2.0, SQLAlchemy 2.0, Python 3.11+ |
| Data layer | **Coral** — unified SQL interface for GitHub, Codeforces, Gmail, YouTube |
| Database | SQLite (dev) · PostgreSQL (prod) |
| Auth | Google OAuth2 |
| AI | Gemini 2.5 Flash · Cohere (fallback) |
| Encryption | `cryptography.fernet` — all OAuth tokens encrypted at rest |
| Deploy | Netlify (frontend) · Railway (backend) |

---

## Getting Started

### Prerequisites

- Python 3.11+
- Node.js 18+
- A Google Cloud project with OAuth2 credentials
- A Gemini API key
- [Coral CLI](https://withcoral.com) (optional — direct API fallbacks work without it)

### 1. Clone the repo

```bash
git clone https://github.com/YashasviThakur/DevMirror.git
cd DevMirror
```

### 2. Backend setup

```bash
cd devmirror-api
python -m venv venv
source venv/bin/activate  # Windows: venv\Scripts\activate
pip install -r requirements.txt
```

Copy the example env file and fill in your credentials:

```bash
cp .env.example .env
```

```env
GOOGLE_CLIENT_ID=your_client_id
GOOGLE_CLIENT_SECRET=your_client_secret
GOOGLE_REDIRECT_URI=http://localhost:8000/api/auth/google/callback
FERNET_KEY=          # python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
GEMINI_API_KEY=your_gemini_key
GITHUB_TOKEN=your_github_pat   # read:user + repo scopes
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
```

```bash
cp .env.example .env.local
# Set VITE_API_URL=http://localhost:8000
```

Start the frontend:

```bash
npm run dev
```

Open [http://localhost:5173](http://localhost:5173) and sign in with Google.

### 4. Coral setup (optional, enables SQL-powered data layer)

Install the Coral CLI, then register the sources:

```bash
# Register GitHub (bundled — uses GITHUB_TOKEN from env)
coral source add github

# Register custom sources
CODEFORCES_HANDLE=your_handle coral source add --file devmirror-api/coral_sources/codeforces.yaml
coral source add --file devmirror-api/coral_sources/gmail.yaml
coral source add --file devmirror-api/coral_sources/youtube.yaml
```

If Coral is not installed, the backend falls back to direct API calls automatically.

---

## Project Structure

```
DevMirror/
├── devmirror-api/              # FastAPI backend
│   ├── main.py                 # All API routes, data fetchers, Coral integration
│   ├── coral_client.py         # Thin SQL wrapper around the Coral CLI
│   ├── coral_sources/          # Custom Coral source definitions (YAML)
│   │   ├── codeforces.yaml
│   │   ├── gmail.yaml
│   │   └── youtube.yaml
│   ├── models.py               # SQLAlchemy ORM (User, LinkedAccount)
│   ├── auth_router.py          # Google OAuth2 flow
│   └── .env.example
│
├── devmirror-frontend/         # React frontend
│   └── src/
│       ├── pages/              # Dashboard, Gmail, YouTube, Coach, ...
│       ├── components/         # Shared UI components
│       ├── api/                # API client + TypeScript types
│       └── hooks/              # useUserId, etc.
│
└── devmirror-landing.html      # Static landing page
```

---

## Environment Variables

### Backend (`devmirror-api/.env`)

| Variable | Required | Description |
|---|---|---|
| `GOOGLE_CLIENT_ID` | Yes | Google OAuth2 client ID |
| `GOOGLE_CLIENT_SECRET` | Yes | Google OAuth2 client secret |
| `GOOGLE_REDIRECT_URI` | Yes | Must match Google Cloud Console exactly |
| `FERNET_KEY` | Yes | Encryption key for stored OAuth tokens |
| `GEMINI_API_KEY` | Yes | Gemini 2.5 Flash for AI coach |
| `GITHUB_TOKEN` | Yes | GitHub PAT (`read:user` + `repo`) — also used by Coral |
| `COHERE_API_KEY` | No | Cohere fallback for AI coach |
| `FRONTEND_URL` | Yes | Frontend origin (for CORS) |
| `DATABASE_URL` | No | Defaults to SQLite |

### Frontend (`devmirror-frontend/.env.local`)

| Variable | Required | Description |
|---|---|---|
| `VITE_API_URL` | Yes | Backend URL (empty string in dev with Vite proxy) |

---

## Contributing

1. Fork the repository
2. Create a feature branch: `git checkout -b feat/your-feature`
3. Commit your changes: `git commit -m 'feat: add your feature'`
4. Push to the branch: `git push origin feat/your-feature`
5. Open a Pull Request

Please open an issue first for major changes so we can discuss the approach.

---

## Roadmap

- [ ] Mobile-responsive layout
- [ ] GitHub Actions / CI pipeline stats
- [ ] Weekly email digest
- [ ] Public profile shareable link
- [ ] Institution dashboard (aggregate analytics)

---

<div align="center">

Built by [Yashasvi Thakur](https://github.com/YashasviThakur) &nbsp;·&nbsp; Powered by [Coral](https://withcoral.com) · [Gemini](https://deepmind.google/technologies/gemini/)

⭐ Star this repo if DevMirror helped you — it means a lot.

</div>
