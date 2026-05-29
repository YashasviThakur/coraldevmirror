"""
DevMirror — production FastAPI application entry point.
Multi-tenant: all data pipelines are user-scoped via user_id.
Integrates Google services (Gmail, Calendar, YouTube), GitHub, LeetCode,
Codeforces, and Gemini 2.5 Flash with closed-loop calendar scheduling.
"""

import io
import json
import os
import re
import sys
import logging
import asyncio
from concurrent.futures import ThreadPoolExecutor
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

import requests
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Depends, Query, UploadFile, File
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from sqlalchemy.orm import Session

sys.path.insert(0, os.path.dirname(__file__))
load_dotenv(os.path.join(os.path.dirname(__file__), ".env"))

logger = logging.getLogger(__name__)

from models import User, LinkedAccount, get_db, init_db
from auth_router import router as auth_router, refresh_google_token_if_needed
import coral_client

GOOGLE_TOKEN_URL = "https://oauth2.googleapis.com/token"

def _get_demo_google_token(db: Session) -> Optional[str]:
    """
    Return a valid Google access token for the coral demo.
    Priority: DB user 1 → any stored Google refresh token env var → GOOGLE_ACCESS_TOKEN.
    Caches the env-var refresh result for 55 minutes.
    """
    token = refresh_google_token_if_needed(1, db)
    if token:
        return token

    cached = _cache_get("demo_google_token")
    if cached:
        return cached

    # Check all possible refresh token env var names (Railway uses separate keys per service)
    refresh_token = (
        os.getenv("GOOGLE_REFRESH_TOKEN", "")
        or os.getenv("GMAIL_REFRESH_TOKEN", "")
        or os.getenv("GOOGLE_CALENDAR_REFRESH_TOKEN", "")
        or os.getenv("YOUTUBE_REFRESH_TOKEN", "")
    )
    if refresh_token:
        resp = requests.post(
            GOOGLE_TOKEN_URL,
            data={
                "client_id":     os.getenv("GOOGLE_CLIENT_ID", ""),
                "client_secret": os.getenv("GOOGLE_CLIENT_SECRET", ""),
                "refresh_token": refresh_token,
                "grant_type":    "refresh_token",
            },
            timeout=10,
        )
        if resp.status_code == 200:
            new_token = resp.json().get("access_token", "")
            if new_token:
                _cache_set("demo_google_token", new_token, ttl_seconds=3300)
                return new_token

    return os.getenv("GOOGLE_ACCESS_TOKEN", "") or None

_pool = ThreadPoolExecutor(max_workers=12)

async def _run(fn, *args):
    """Run a blocking function in a thread pool so it doesn't block the event loop."""
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(_pool, fn, *args)


# ── Simple in-memory TTL cache ────────────────────────────────────────────────

import threading

_cache_lock = threading.Lock()
_cache: dict[str, tuple[Any, float]] = {}   # key → (value, expires_at)

def _cache_get(key: str) -> Any:
    with _cache_lock:
        entry = _cache.get(key)
        if entry and entry[1] > datetime.utcnow().timestamp():
            return entry[0]
        return None

def _cache_set(key: str, value: Any, ttl_seconds: int = 7200) -> None:
    with _cache_lock:
        _cache[key] = (value, datetime.utcnow().timestamp() + ttl_seconds)

app = FastAPI(title="DevMirror API", version="2.0.0", docs_url="/docs")

FRONTEND_URL = os.getenv("FRONTEND_URL", "http://localhost:5173")
_cors_origins = (
    ["*"] if FRONTEND_URL == "*"
    else [FRONTEND_URL,
          "http://localhost:5173", "http://localhost:5174",
          "http://localhost:5175", "http://localhost:5176",
          "http://localhost:5177"]
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.include_router(auth_router)

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")
COHERE_API_KEY = os.getenv("COHERE_API_KEY", "")
GITHUB_TOKEN   = os.getenv("GITHUB_TOKEN", "")   # legacy env fallback

# Use Cohere if available, fall back to Gemini
USE_COHERE = bool(COHERE_API_KEY)
logger.info(f"🔑 COHERE_API_KEY loaded: {bool(COHERE_API_KEY)} | Using {'COHERE' if USE_COHERE else 'GEMINI'}")


@app.on_event("startup")
def startup():
    init_db()


# ── Helpers — DB lookups ───────────────────────────────────────────────────────

def _get_user_or_404(user_id: int, db: Session) -> User:
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    return user


def _get_valid_google_token(user_id: int, db: Session) -> str:
    token = refresh_google_token_if_needed(user_id, db)
    if not token:
        raise HTTPException(
            status_code=401,
            detail="Google account not connected or token expired. Please re-authenticate.",
        )
    return token


def _resolve_github_username(user_id: int, db: Session) -> Optional[str]:
    """Return the stored GitHub username for this user (stored in github_access_token field)."""
    user = db.query(User).filter(User.id == user_id).first()
    if user and user.linked_accounts and user.linked_accounts.github_access_token:
        return user.linked_accounts.github_access_token
    return None

# Keep old name as alias for backward compat with any remaining references
_resolve_github_token = _resolve_github_username


# ── GitHub data pipeline ───────────────────────────────────────────────────────

def _fetch_github_cached(github_username: str) -> dict[str, Any]:
    """Fetch GitHub data with 2-hour cache to avoid rate limits.
    Only caches successful responses (public_repos > 0 or followers > 0 or repos list returned)."""
    key = f"github:{github_username.lower()}"
    cached = _cache_get(key)
    if cached is not None:
        logger.info(f"[cache hit] GitHub:{github_username}")
        return cached
    result = _fetch_github(github_username)
    # Don't cache rate-limited or not-found responses (they have 0 repos AND 0 followers)
    if result.get("public_repos", 0) > 0 or result.get("followers", 0) > 0 or result.get("repos", 0) > 0:
        _cache_set(key, result, ttl_seconds=7200)   # 2 hours
        logger.info(f"[cache set] GitHub:{github_username}")
    else:
        logger.warning(f"[cache skip] GitHub:{github_username} — empty response (rate limit or user not found)")
    return result


def _fetch_github(github_username: str) -> dict[str, Any]:
    """Fetch GitHub data; uses GITHUB_TOKEN env var if set for higher rate limits."""
    headers = {"Accept": "application/vnd.github+json"}
    if GITHUB_TOKEN:
        headers["Authorization"] = f"Bearer {GITHUB_TOKEN}"
    username = github_username.strip().lstrip("@")

    user_resp = requests.get(f"https://api.github.com/users/{username}", headers=headers, timeout=10)
    if user_resp.status_code != 200:
        return {"username": username, "repos": 0, "commits_week": 0, "top_repo": "", "languages": [], "contribution_grid": [], "public_repos": 0, "followers": 0, "avatar_url": ""}

    gh_user = user_resp.json()

    repos_resp = requests.get(
        f"https://api.github.com/users/{username}/repos",
        headers=headers,
        params={"sort": "updated", "per_page": 10},
        timeout=10,
    )
    repos = repos_resp.json() if repos_resp.status_code == 200 else []

    events_resp = requests.get(
        f"https://api.github.com/users/{username}/events",
        headers=headers,
        params={"per_page": 100},
        timeout=10,
    )
    events = events_resp.json() if events_resp.status_code == 200 and isinstance(events_resp.json(), list) else []

    week_ago = datetime.utcnow() - timedelta(days=7)
    commits_week = 0
    daily_counts: dict[str, int] = defaultdict(int)

    for e in events:
        if not isinstance(e, dict) or e.get("type") != "PushEvent":
            continue
        try:
            created = datetime.strptime(e["created_at"][:19], "%Y-%m-%dT%H:%M:%S")
        except (KeyError, ValueError):
            continue
        date_key = str(created.date())
        daily_counts[date_key] += 1
        if created > week_ago:
            commits_week += 1

    today = datetime.utcnow().date()
    grid: list[list[int]] = []
    for week in range(52):
        week_col: list[int] = []
        for day in range(7):
            d = today - timedelta(days=(51 - week) * 7 + (6 - day))
            week_col.append(daily_counts.get(str(d), 0))
        grid.append(week_col)

    top_repo  = repos[0]["name"] if repos else ""
    languages = list({r.get("language") for r in repos[:8] if r.get("language")})

    return {
        "username":          username,
        "repos":             len(repos),
        "commits_week":      commits_week,
        "top_repo":          top_repo,
        "languages":         languages[:5],
        "contribution_grid": grid,
        "public_repos":      gh_user.get("public_repos", 0),
        "followers":         gh_user.get("followers", 0),
        "avatar_url":        gh_user.get("avatar_url", ""),
        "_events":           events,   # passed through for LvB trend
    }


# ── LeetCode data pipeline ─────────────────────────────────────────────────────

def _calc_lc_streak(submission_calendar: str) -> int:
    """Calculate current streak from LeetCode submissionCalendar JSON string."""
    try:
        cal = json.loads(submission_calendar or "{}")
        if not cal:
            return 0
        today = datetime.utcnow().date()
        streak = 0
        d = today
        while True:
            ts = str(int(datetime(d.year, d.month, d.day).timestamp()))
            # LeetCode stores epoch timestamps — check same-day bucket
            found = any(
                abs(int(k) - int(ts)) < 86400
                for k in cal
            )
            if not found:
                break
            streak += 1
            d -= timedelta(days=1)
        return streak
    except Exception:
        return 0


def _fetch_leetcode(username: str) -> dict[str, Any]:
    profile_query = """
    query userProfile($username: String!) {
        matchedUser(username: $username) {
            username
            submitStats {
                acSubmissionNum   { difficulty count }
                totalSubmissionNum { difficulty count }
            }
            userCalendar(year: 0) { streak totalActiveDays submissionCalendar }
            profile { ranking }
        }
    }
    """
    recent_query = """
    query recentAcSubmissions($username: String!, $limit: Int!) {
        recentAcSubmissionList(username: $username, limit: $limit) {
            id title titleSlug timestamp
        }
    }
    """
    lc_headers = {
        "Content-Type": "application/json",
        "Referer":      "https://leetcode.com",
        "User-Agent":   "Mozilla/5.0",
    }
    try:
        resp = requests.post(
            "https://leetcode.com/graphql",
            json={"query": profile_query, "variables": {"username": username}},
            headers=lc_headers,
            timeout=12,
        )
        recent_resp = requests.post(
            "https://leetcode.com/graphql",
            json={"query": recent_query, "variables": {"username": username, "limit": 10}},
            headers=lc_headers,
            timeout=12,
        )
    except Exception:
        return _empty_leetcode(username)

    if resp.status_code != 200:
        return _empty_leetcode(username)

    data = (resp.json().get("data") or {}).get("matchedUser")
    if not data:
        return _empty_leetcode(username)

    ac_counts  = {s["difficulty"]: s["count"] for s in data["submitStats"]["acSubmissionNum"]}
    tot_counts = {s["difficulty"]: s["count"] for s in data["submitStats"].get("totalSubmissionNum", [])}
    calendar   = data.get("userCalendar") or {}
    profile    = data.get("profile") or {}

    # Compute real acceptance rate from total vs accepted submission counts
    ac_all  = ac_counts.get("All", 0)
    tot_all = tot_counts.get("All", 0)
    acceptance_rate = round((ac_all / tot_all) * 100, 1) if tot_all > 0 else 0.0

    # Prefer API streak; fall back to computing from submissionCalendar
    api_streak = calendar.get("streak", 0)
    sub_cal    = calendar.get("submissionCalendar", "{}")
    streak     = api_streak if api_streak else _calc_lc_streak(sub_cal)

    # Parse recent accepted submissions
    recent: list[dict] = []
    if recent_resp.status_code == 200:
        raw_recent = (recent_resp.json().get("data") or {}).get("recentAcSubmissionList") or []
        for s in raw_recent[:10]:
            ts = int(s.get("timestamp", 0))
            date_str = datetime.utcfromtimestamp(ts).strftime("%Y-%m-%d") if ts else ""
            recent.append({
                "title":      s.get("title", ""),
                "difficulty": "",   # not returned by recentAcSubmissionList
                "date":       date_str,
            })

    return {
        "username":          username,
        "total_solved":      ac_counts.get("All", 0),
        "easy":              ac_counts.get("Easy", 0),
        "medium":            ac_counts.get("Medium", 0),
        "hard":              ac_counts.get("Hard", 0),
        "streak":            streak,
        "total_active_days": calendar.get("totalActiveDays", 0),
        "acceptance_rate":   acceptance_rate,
        "ranking":           profile.get("ranking", 0),
        "recent":            recent,
    }


def _empty_leetcode(username: str) -> dict[str, Any]:
    return {
        "username": username, "total_solved": 0, "easy": 0, "medium": 0,
        "hard": 0, "streak": 0, "total_active_days": 0, "acceptance_rate": 0.0,
        "ranking": 0, "recent": [],
    }


# ── Codeforces data pipeline ───────────────────────────────────────────────────

def _fetch_codeforces(handle: str) -> dict[str, Any]:
    # Coral is not used for Codeforces — its handle input is set once at
    # CLI setup time and cannot change per-user request (multi-tenant issue).
    # Direct Codeforces API is used instead — it's public and per-user.
    return _fetch_codeforces_direct(handle)


def _fetch_codeforces_direct(handle: str) -> dict[str, Any]:
    try:
        info_resp = requests.get(
            f"https://codeforces.com/api/user.info?handles={handle}",
            timeout=10,
        )
    except Exception:
        return _empty_codeforces(handle)

    if info_resp.status_code != 200 or info_resp.json().get("status") != "OK":
        return _empty_codeforces(handle)

    info = info_resp.json()["result"][0]

    try:
        status_resp = requests.get(
            f"https://codeforces.com/api/user.status?handle={handle}&count=500",
            timeout=10,
        )
        solved: set[str] = set()
        recent: list[dict] = []
        if status_resp.status_code == 200 and status_resp.json().get("status") == "OK":
            for sub in status_resp.json()["result"]:
                prob = sub.get("problem", {})
                prob_key = f"{prob.get('contestId', '')}{prob.get('index', '')}"
                if sub.get("verdict") == "OK":
                    solved.add(prob_key)
                if len(recent) < 10:
                    raw_verdict = sub.get("verdict", "")
                    recent.append({
                        "problem": prob.get("name", ""),
                        "verdict": "AC" if raw_verdict == "OK" else raw_verdict,
                        "rating":  prob.get("rating", 0),
                        "date":    datetime.utcfromtimestamp(
                            sub.get("creationTimeSeconds", 0)
                        ).strftime("%Y-%m-%d"),
                    })
    except Exception:
        solved = set()
        recent = []

    return {
        "handle":     handle,
        "rating":     info.get("rating", 0),
        "max_rating": info.get("maxRating", 0),
        "rank":       info.get("rank", "unrated"),
        "max_rank":   info.get("maxRank", "unrated"),
        "solved":     len(solved),
        "avatar":     info.get("avatar", ""),
        "recent":     recent,
    }


def _empty_codeforces(handle: str) -> dict[str, Any]:
    return {
        "handle": handle, "rating": 0, "max_rating": 0,
        "rank": "unrated", "max_rank": "unrated", "solved": 0,
        "avatar": "", "recent": [],
    }


# ── Gmail pipeline ─────────────────────────────────────────────────────────────

GMAIL_FILTER_QUERY = (
    "subject:(internship OR hackathon OR coding OR recruitment OR application)"
)
GMAIL_BASE = "https://gmail.googleapis.com/gmail/v1/users/me"

# Coral demo user — hardcoded handles (coraldevmirror branch)
CORAL_DEMO_CF_HANDLE   = "yashasvithakur2005"
CORAL_DEMO_GH_USERNAME = "YashasviThakur"
CORAL_DEMO_LC_HANDLE   = "yashasvithakur2005"

_CAT_KEYWORDS = {
    "internship":  ["internship", "intern", "summer", "hiring", "position", "opportunity", "job"],
    "hackathon":   ["hackathon", "hack", "hacks", "contest", "competition", "challenge"],
    "scholarship": ["scholarship", "fellowship", "grant", "award", "stipend"],
}


def _categorize_subject(subject: str) -> str:
    s = subject.lower()
    for cat, kws in _CAT_KEYWORDS.items():
        if any(kw in s for kw in kws):
            return cat
    return "other"


def _fetch_gmail(access_token: str) -> list[dict[str, Any]]:
    # Try Coral SQL first
    coral_rows = coral_client.get_gmail_opportunities(access_token)
    if coral_rows:  # non-empty list
        results = []
        for row in coral_rows:
            subject = row.get("snippet", "")[:80]
            results.append({
                "id":              row.get("id", ""),
                "subject":         subject,
                "from":            "",
                "date":            "",
                "snippet":         row.get("snippet", ""),
                "category":        _categorize_subject(row.get("snippet", "")),
                "ai_summary":      "",
                "action_required": False,
                "gmail_link":      f"https://mail.google.com/mail/u/0/#inbox/{row.get('id', '')}",
            })
        return results

    # Coral returned None or empty — fall back to direct Gmail API using env token
    if not access_token:
        access_token = os.environ.get("GMAIL_ACCESS_TOKEN", "")
    if not access_token:
        return []
    headers = {"Authorization": f"Bearer {access_token}"}

    list_resp = requests.get(
        f"{GMAIL_BASE}/messages",
        headers=headers,
        params={"q": GMAIL_FILTER_QUERY, "maxResults": 25},
        timeout=12,
    )
    if list_resp.status_code != 200:
        return []

    message_ids = list_resp.json().get("messages", [])
    emails: list[dict[str, Any]] = []

    for msg in message_ids[:15]:
        msg_resp = requests.get(
            f"{GMAIL_BASE}/messages/{msg['id']}",
            headers=headers,
            params={
                "format":          "metadata",
                "metadataHeaders": ["Subject", "From", "Date"],
            },
            timeout=10,
        )
        if msg_resp.status_code != 200:
            continue

        msg_data    = msg_resp.json()
        hdr_list    = msg_data.get("payload", {}).get("headers", [])
        hdrs        = {h["name"]: h["value"] for h in hdr_list}
        subject     = hdrs.get("Subject", "No Subject")
        category    = _categorize_subject(subject)
        action      = category in ("internship", "hackathon")
        gmail_link  = f"https://mail.google.com/mail/u/0/#inbox/{msg['id']}"

        emails.append({
            "id":              msg["id"],
            "subject":         subject,
            "from":            hdrs.get("From", "Unknown"),
            "date":            hdrs.get("Date", ""),
            "snippet":         msg_data.get("snippet", ""),
            "category":        category,
            "ai_summary":      "",
            "action_required": action,
            "gmail_link":      gmail_link,
        })

    return emails


# ── Google Calendar pipeline ───────────────────────────────────────────────────

GCAL_BASE = "https://www.googleapis.com/calendar/v3"


def _fetch_calendar_events(access_token: str) -> list[dict[str, Any]]:
    headers = {"Authorization": f"Bearer {access_token}"}
    now     = datetime.utcnow().isoformat() + "Z"

    resp = requests.get(
        f"{GCAL_BASE}/calendars/primary/events",
        headers=headers,
        params={
            "timeMin":      now,
            "maxResults":   15,
            "singleEvents": True,
            "orderBy":      "startTime",
        },
        timeout=10,
    )
    if resp.status_code != 200:
        return []

    return [
        {
            "id":          item["id"],
            "summary":     item.get("summary", "Untitled"),
            "description": item.get("description", ""),
            "start":       item["start"].get("dateTime", item["start"].get("date")),
            "end":         item["end"].get("dateTime", item["end"].get("date")),
        }
        for item in resp.json().get("items", [])
    ]


def _create_calendar_event(access_token: str, event: dict) -> dict:
    headers = {
        "Authorization": f"Bearer {access_token}",
        "Content-Type":  "application/json",
    }
    body = {
        "summary":     event.get("summary", "DevMirror Task"),
        "description": event.get("description", ""),
        "start":       {"dateTime": event["start_time"], "timeZone": "UTC"},
        "end":         {"dateTime": event["end_time"],   "timeZone": "UTC"},
    }
    resp = requests.post(
        f"{GCAL_BASE}/calendars/primary/events",
        headers=headers,
        json=body,
        timeout=10,
    )
    return resp.json()


# ── YouTube watch-history parser ───────────────────────────────────────────────

TECH_CATEGORIES: dict[str, list[str]] = {
    "Algorithms & DS": [
        # Core DSA
        "algorithm", "data structure", "dsa", "leetcode",
        # Linear structures
        "linked list", "singly linked", "doubly linked", "circular list",
        "stack", "queue", "deque", "matrix", "array",
        # Non-linear structures
        "binary tree", "binary search tree", "bst", "avl tree", "red-black tree",
        "trie", "segment tree", "fenwick tree", "binary indexed tree",
        "graph", "directed graph", "undirected graph", "weighted graph",
        # Algorithms
        "sorting", "bubble sort", "selection sort", "insertion sort",
        "merge sort", "quick sort", "heap sort", "radix sort",
        "searching", "binary search", "ternary search", "linear search",
        "two pointers", "sliding window", "recursion", "backtracking",
        # Advanced paradigms
        "divide and conquer", "greedy", "dynamic programming",
        "bit manipulation", "bfs", "dfs", "dijkstra", "bellman-ford",
        "floyd-warshall", "prim", "kruskal", "topological sort",
        # Complexity
        "time complexity", "space complexity", "big o", "asymptotic",
        "pseudocode", "flowchart", "flow of program",
    ],
    "Languages": [
        # Systems
        "c programming", "c++", "rust", "golang", "go language",
        # Enterprise
        "java", "c#", ".net", "spring boot",
        # Web/scripting
        "python", "javascript", "typescript", "ruby", "php",
        # Mobile/specialized
        "kotlin", "swift", "dart", "flutter", "assembly",
        "html", "css", "html5", "css3", "sass", "scss",
        "programming language", "tutorial",
        # OOP
        "oops", "oop", "object oriented", "class and object",
        "inheritance", "polymorphism", "abstraction", "encapsulation",
        "interface", "abstract class", "access modifier",
    ],
    "Web Dev": [
        # Frontend core
        "dom manipulation", "semantic html", "flexbox", "css grid",
        "vanilla js", "es6",
        # Frameworks
        "react", "angular", "vue", "next.js", "nuxt", "svelte", "remix",
        # State management
        "redux", "context api", "zustand", "mobx",
        # Styling
        "tailwind", "bootstrap", "material ui", "styled components",
        # Backend
        "node", "express", "nestjs", "fastapi", "django", "flask",
        "spring", "rails", "laravel", "asp.net", "fiber",
        # APIs
        "rest api", "graphql", "grpc", "soap", "http",
        "web development", "frontend", "backend", "fullstack", "full stack",
        "web dev", "mvc",
    ],
    "ML / AI": [
        # Core ML
        "machine learning", "supervised learning", "unsupervised learning",
        "regression", "classification", "clustering",
        "scikit-learn", "xgboost",
        # Deep learning
        "deep learning", "neural network", "cnn", "rnn", "lstm",
        "transformer", "pytorch", "tensorflow", "keras",
        # Gen AI & LLMs
        "generative ai", "large language model", "llm", "prompt engineering",
        "rag", "retrieval augmented", "langchain", "llamaindex",
        "vector database", "pinecone", "fine-tuning", "hugging face",
        # Data science
        "data science", "data engineering", "apache spark", "kafka",
        "hadoop", "etl", "airflow", "dbt",
        # General AI
        "artificial intelligence", "gpt", "chatgpt", "openai",
        "computer vision", "nlp", "ai",
    ],
    "System Design": [
        # Design patterns
        "system design", "design pattern", "singleton", "factory pattern",
        "observer pattern", "decorator pattern",
        # Architecture
        "microservices", "monolithic", "serverless", "event-driven",
        "architecture", "scalability", "load balancing",
        "caching", "redis", "memcached", "sharding", "replication",
        "rate limiting", "cdn",
        # DevOps & infra
        "docker", "kubernetes", "k8s", "helm", "containerd",
        "jenkins", "github actions", "gitlab ci", "circleci", "argocd",
        "terraform", "ansible", "pulumi", "cloudformation",
        "prometheus", "grafana", "elk stack", "datadog",
        # Cloud
        "aws", "gcp", "azure", "ec2", "s3", "lambda", "cloud run",
        "cloud", "devops", "ci/cd",
        # Linux & tools
        "linux", "terminal", "bash", "shell", "yaml", "container",
        "git", "github", "gitlab", "version control",
        "gitflow", "merge conflict", "rebase", "cherry-pick",
    ],
    "CS Fundamentals": [
        # OS
        "operating system", "os concepts", "process", "thread",
        "concurrency", "multithreading", "asynchronous", "memory management",
        "garbage collection", "cache locality", "rtos",
        # Networking
        "computer network", "networking", "osi model", "tcp", "ip protocol",
        "dns", "http", "https", "ssl", "tls",
        # Databases
        "database", "sql", "postgresql", "mysql", "sqlite",
        "mongodb", "nosql", "cassandra", "dynamodb", "neo4j",
        "acid", "normalization", "indexing", "query optimization",
        "dbms", "data warehouse", "elasticsearch",
        # Security
        "cybersecurity", "owasp", "penetration testing", "xss",
        "sql injection", "csrf", "oauth", "jwt", "encryption",
        "rsa", "aes", "hashing", "sha", "bcrypt",
        # Compilers & low-level
        "compiler", "computer science", "embedded", "microcontroller",
        "arduino", "raspberry pi", "firmware", "mqtt",
        # Math/CP niche
        "modular inverse", "euclidean", "sieve", "prime factorization",
        "combinatorics", "matrix exponentiation", "bitmask",
    ],
    "Interview Prep": [
        "interview", "coding interview", "placement", "competitive programming",
        "codeforces", "hackerrank", "faang", "maang",
        "tech career", "roadmap", "how to become", "software engineer",
        "tdd", "agile", "scrum", "kanban", "code review",
        "unit testing", "integration testing", "jest", "cypress",
        "junit", "selenium", "playwright",
    ],
}

ALL_TECH_KEYWORDS = [kw for kws in TECH_CATEGORIES.values() for kw in kws]


def _match_tech_cat(title_lower: str, kws: list[str]) -> bool:
    for kw in kws:
        if ' ' in kw:
            if kw in title_lower:
                return True
        else:
            if re.search(r'\b' + re.escape(kw) + r'\b', title_lower):
                return True
    return False


def _classify_videos_gemini(titles: list[str]) -> list[dict]:
    """Ask Gemini to classify video titles. Returns list of {index (0-based), category}."""
    if not GEMINI_API_KEY or not titles:
        return []
    numbered = "\n".join(f"{i+1}. {t}" for i, t in enumerate(titles))
    prompt = (
        "You are a strict classifier that identifies YouTube videos CLEARLY related to software engineering, computer science, or programming education.\n\n"
        "A video QUALIFIES only if its title explicitly mentions: programming languages, algorithms, data structures, web/mobile/backend development, "
        "ML/AI/data science, system design, DevOps, databases, networking, competitive programming, coding interviews, or CS fundamentals.\n\n"
        "A video does NOT qualify if it is about: entertainment, sports, music, movies, TV shows, vlogging, cooking, gaming (unless it's about game dev), "
        "news, comedy, religion, or any non-technical subject. When in doubt, EXCLUDE it.\n\n"
        "Video titles:\n"
        f"{numbered}\n\n"
        "Return ONLY valid JSON — an array of objects for QUALIFYING videos only:\n"
        '[{"index": <1-based number>, "category": "<one of: Algorithms & DS | Languages | Web Dev | ML / AI | System Design | CS Fundamentals | Interview Prep>"}]\n'
        "If none qualify, return: []"
    )
    try:
        url = GEMINI_URL.format(key=GEMINI_API_KEY)
        payload = {
            "contents": [{"role": "user", "parts": [{"text": prompt}]}],
            "generationConfig": {"temperature": 0.1, "maxOutputTokens": 2000},
        }
        resp = requests.post(url, json=payload, timeout=30)
        if resp.status_code in (429, 503):
            print("[YouTube classifier] Gemini rate-limited, falling back to keywords")
            return []
        if resp.status_code != 200:
            print(f"[YouTube classifier] Gemini error {resp.status_code}, falling back to keywords")
            return []
        text = resp.json()["candidates"][0]["content"]["parts"][0]["text"].strip()
        print(f"[YouTube classifier] Gemini raw response: {text[:300]}")
        match = re.search(r'\[[\s\S]*\]', text)
        if not match:
            return []
        results = json.loads(match.group())
        print(f"[YouTube classifier] Gemini classified {len(results)} technical videos out of {len(titles)}")
        return results
    except Exception as e:
        print(f"[YouTube classifier] Gemini exception: {e}, falling back to keywords")
        return []


def _classify_video_keywords(title: str) -> Optional[str]:
    """Fallback: classify video by keyword matching."""
    title_lower = title.lower()
    for cat, kws in TECH_CATEGORIES.items():
        if _match_tech_cat(title_lower, kws):
            return cat
    return None


def _parse_youtube_history(raw: bytes) -> dict[str, Any]:
    try:
        history: list[dict] = json.loads(raw.decode("utf-8", errors="ignore"))
    except json.JSONDecodeError:
        return {"error": "Invalid JSON file", "total_watched": 0, "technical_count": 0, "categories": {}}

    if not isinstance(history, list):
        return {"error": "Expected a JSON array", "total_watched": 0, "technical_count": 0, "categories": {}}

    total_watched = len(history)

    # Build video list (cap at 300 for Gemini classification)
    videos: list[dict] = []
    for entry in history[:300]:
        if not isinstance(entry, dict):
            continue
        raw_title = entry.get("title", "")
        title = raw_title[len("Watched "):] if raw_title.startswith("Watched ") else raw_title
        channel = ""
        subs = entry.get("subtitles", [])
        if subs and isinstance(subs, list):
            channel = subs[0].get("name", "")
        videos.append({"title": title, "channel": channel, "watched_at": entry.get("time", "")})

    # Try Gemini first — batch in groups of 50 to stay within token limits
    tech_videos: list[dict] = []
    cat_counts: dict[str, int] = defaultdict(int)
    gemini_worked = False

    for batch_start in range(0, len(videos), 50):
        batch = videos[batch_start:batch_start + 50]
        titles = [v["title"] for v in batch]
        results = _classify_videos_gemini(titles)
        if results:  # Gemini returned classifications
            gemini_worked = True
            classified = {r["index"] - 1: r.get("category", "Technical") for r in results if isinstance(r, dict)}
            for idx, video in enumerate(batch):
                if idx in classified:
                    cat = classified[idx]
                    cat_counts[cat] += 1
                    tech_videos.append({**video, "categories": [cat]})

    # If Gemini didn't work, fall back to keyword matching
    if not gemini_worked:
        for video in videos:
            cat = _classify_video_keywords(video["title"])
            if cat:
                cat_counts[cat] += 1
                tech_videos.append({**video, "categories": [cat]})

    return {
        "total_watched":   total_watched,
        "technical_count": len(tech_videos),
        "categories":      dict(cat_counts),
        "top_videos":      tech_videos[:20],
    }


YOUTUBE_BASE = "https://www.googleapis.com/youtube/v3"


def _fetch_youtube_liked(access_token: str) -> dict[str, Any]:
    # Try Coral SQL first — passes token via env var so each user gets their own data
    coral_rows = coral_client.get_youtube_liked_videos(access_token)
    if coral_rows is not None:
        raw_videos = [
            {
                "title":        r.get("title", ""),
                "channel":      r.get("channel_title", ""),
                "thumbnail":    r.get("thumbnail_url", ""),
                "video_id":     r.get("video_id", ""),
                "published_at": r.get("liked_at", ""),
            }
            for r in coral_rows
        ]
        titles = [v["title"] for v in raw_videos]
        gemini_results = _classify_videos_gemini(titles)
        cat_counts: dict[str, int] = defaultdict(int)
        tech_videos: list[dict] = []
        if gemini_results:
            classified = {r["index"] - 1: r.get("category", "Technical") for r in gemini_results if isinstance(r, dict)}
            for idx, video in enumerate(raw_videos):
                if idx in classified:
                    cat = classified[idx]
                    cat_counts[cat] += 1
                    if cat != "Non-Technical":
                        tech_videos.append({**video, "categories": [cat]})
        else:
            for video in raw_videos:
                cat = _classify_video_keywords(video["title"])
                if cat:
                    cat_counts[cat] += 1
                    tech_videos.append({**video, "categories": [cat]})
        return {
            "total": len(raw_videos),
            "technical_count": len(tech_videos),
            "categories": dict(cat_counts),
            "top_videos": tech_videos[:20],
        }

    headers = {"Authorization": f"Bearer {access_token}"}
    # playlistId=LL is the "Liked videos" playlist — returns items in reverse-liked order (most recent first)
    resp = requests.get(
        f"{YOUTUBE_BASE}/playlistItems",
        headers=headers,
        params={"playlistId": "LL", "part": "snippet", "maxResults": 50},
        timeout=15,
    )
    if resp.status_code != 200:
        return {"total": 0, "technical_count": 0, "categories": {}, "top_videos": []}

    items = resp.json().get("items", [])

    # Build raw video list (most recently liked first)
    raw_videos = []
    for item in items:
        snippet = item.get("snippet", {})
        resource = snippet.get("resourceId", {})
        raw_videos.append({
            "title":        snippet.get("title", ""),
            "channel":      snippet.get("videoOwnerChannelTitle", ""),
            "thumbnail":    snippet.get("thumbnails", {}).get("medium", {}).get("url", ""),
            "video_id":     resource.get("videoId", ""),
            "published_at": snippet.get("publishedAt", ""),  # when it was added to the playlist
        })

    # Try Gemini first to classify which videos are study/technical content
    titles = [v["title"] for v in raw_videos]
    gemini_results = _classify_videos_gemini(titles)

    cat_counts: dict[str, int] = defaultdict(int)
    tech_videos: list[dict] = []

    if gemini_results:
        # Gemini worked — use its classifications
        classified_indices = {r["index"] - 1: r.get("category", "Technical") for r in gemini_results if isinstance(r, dict)}
        for idx, video in enumerate(raw_videos):
            if idx in classified_indices:
                cat = classified_indices[idx]
                cat_counts[cat] += 1
                tech_videos.append({**video, "categories": [cat]})
    else:
        # Gemini failed — fall back to keyword matching
        for video in raw_videos:
            cat = _classify_video_keywords(video["title"])
            if cat:
                cat_counts[cat] += 1
                tech_videos.append({**video, "categories": [cat]})

    return {
        "total":           len(items),
        "technical_count": len(tech_videos),
        "categories":      dict(cat_counts),
        "top_videos":      tech_videos[:20],
    }


# ── Gemini AI pipeline ─────────────────────────────────────────────────────────

GEMINI_URL = (
    "https://generativelanguage.googleapis.com/v1beta/models/"
    "gemini-2.5-flash:generateContent?key={key}"
)

_CALENDAR_SCHEDULE_TRIGGERS = [
    "schedule", "plan my", "what should i", "focus today", "focus this week",
    "create events", "add to calendar", "remind me", "block time", "study plan",
]

_SYSTEM_PROMPT_TEMPLATE = """You are DevMirror Coach — an elite AI mentor for software engineers and CS students.

The user has set these personal development goals:
  • Goal 1: {goal_1}
  • Goal 2: {goal_2}
  • Goal 3: {goal_3}

BEHAVIOUR RULES:
1. If the user asks about scheduling, planning, focus, or wants tasks added to their calendar,
   respond with ONLY a valid JSON array using this exact schema:
   [
     {{"summary": "Event Title", "description": "Details", "start_time": "ISO 8601 timestamp", "end_time": "ISO 8601 timestamp"}}
   ]
   Use realistic timestamps starting from today ({today}).
   Do NOT wrap the JSON in markdown code fences or add any other text.

2. For all other messages, respond with helpful, motivating, specific coaching advice.
   Use markdown: **bold**, ## headers, bullet points. Max 400 words.
   Reference their goals when relevant. Be direct and actionable.

3. When asked about courses, books, or learning resources:
   - Draw on community sentiment from Reddit (r/learnprogramming, r/cscareerquestions,
     r/leetcode, r/developersIndia, r/Python, r/webdev, r/MachineLearning, etc.)
   - Reference real course platforms: Udemy, Coursera, edX, freeCodeCamp, The Odin Project,
     NeetCode, Abdul Bari, Striver, Apna College, CodeWithHarry, CS50, MIT OpenCourseWare.
   - Mention YouTube channels, GitHub repos, or books that the community consistently recommends.
   - Include a "Reddit verdict" — summarise what the community says (e.g. "Reddit loves this for beginners but warns it's outdated for X").
   - Give a concrete recommendation ranked by: free vs paid, beginner vs advanced, theory vs hands-on.

4. Never be vague. Never shame. Celebrate progress. Always give one concrete next action.
"""


def _is_scheduling_request(question: str) -> bool:
    q = question.lower()
    return any(trigger in q for trigger in _CALENDAR_SCHEDULE_TRIGGERS)


def _extract_json_array(text: str) -> Optional[list]:
    match = re.search(r"\[\s*\{[\s\S]*?\}\s*\]", text)
    if match:
        try:
            parsed = json.loads(match.group())
            if isinstance(parsed, list):
                return parsed
        except json.JSONDecodeError:
            pass
    return None


def _call_cohere(system_prompt: str, user_message: str) -> tuple[str, bool]:
    """Call Cohere API (v2 chat) and return (text, is_success)."""
    if not COHERE_API_KEY:
        return "AI key not configured.", False

    url = "https://api.cohere.com/v2/chat"
    headers = {
        "Authorization": f"Bearer {COHERE_API_KEY}",
        "Content-Type": "application/json",
    }

    payload = {
        "model": "command-r-plus-08-2024",
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user",   "content": user_message},
        ],
        "max_tokens": 1024,
        "temperature": 0.7,
    }

    try:
        resp = requests.post(url, json=payload, headers=headers, timeout=30)
        if resp.status_code == 429:
            logger.warning("Cohere API rate-limited (429)")
            return "AI is temporarily rate-limited. Please wait a moment and try again.", False
        if resp.status_code != 200:
            logger.error(f"Cohere API error ({resp.status_code}): {resp.text}")
            return f"AI unavailable (status {resp.status_code}). Please try again shortly.", False

        data = resp.json()
        message = data.get("message", {})
        content = message.get("content", [])
        if content:
            text = content[0].get("text", "").strip()
            if text:
                return text, True
        logger.error(f"Cohere returned no content: {data}")
        return "No response from AI service.", False
    except Exception as e:
        logger.error(f"Cohere call failed: {str(e)}")
        return f"Could not reach the AI service: {str(e)}", False


def _call_gemini(system_prompt: str, user_message: str) -> tuple[str, bool]:
    """Call Gemini and return (text, is_success). is_success indicates whether to use the text."""
    if not GEMINI_API_KEY:
        return "Gemini API key not configured. Set GEMINI_API_KEY in your .env file.", False

    url     = GEMINI_URL.format(key=GEMINI_API_KEY)
    payload = {
        "contents":          [{"role": "user", "parts": [{"text": user_message}]}],
        "systemInstruction": {"parts": [{"text": system_prompt}]},
        "generationConfig":  {"temperature": 0.7, "maxOutputTokens": 1024},
    }
    try:
        resp = requests.post(url, json=payload, timeout=30)
        if resp.status_code == 429:
            return "AI is temporarily rate-limited. Please wait a moment and try again.", False
        if resp.status_code != 200:
            return f"AI unavailable (status {resp.status_code}). Please try again shortly.", False
        candidates = resp.json().get("candidates", [])
        if candidates:
            text = candidates[0]["content"]["parts"][0]["text"]
            return text, True
        return "No response from Gemini.", False
    except Exception:
        return "Could not reach the AI service. Check your internet connection and try again.", False


def call_ai(system_prompt: str, user_message: str) -> tuple[str, bool]:
    """Try Cohere first, fall back to Gemini. Cache successful responses for 1 hour."""
    cache_key = f"ai:{hash(system_prompt + user_message)}"
    cached = _cache_get(cache_key)
    if cached is not None:
        return cached, True

    if COHERE_API_KEY:
        text, ok = _call_cohere(system_prompt, user_message)
        if ok:
            _cache_set(cache_key, text, ttl_seconds=3600)
            return text, ok

    # Cohere unavailable or failed — fall back to Gemini
    text, ok = _call_gemini(system_prompt, user_message)
    if ok:
        _cache_set(cache_key, text, ttl_seconds=3600)
    return text, ok


# ── Pydantic request/response models ──────────────────────────────────────────

class GoalsUpdate(BaseModel):
    goal_1: Optional[str] = None
    goal_2: Optional[str] = None
    goal_3: Optional[str] = None


class HandlesUpdate(BaseModel):
    codeforces_handle: Optional[str] = None
    leetcode_username: Optional[str] = None


class GithubTokenUpdate(BaseModel):
    github_token: str

class GithubUsernameUpdate(BaseModel):
    github_username: str


class AskRequest(BaseModel):
    user_id:  int
    question: str


# ── API routes ─────────────────────────────────────────────────────────────────

@app.get("/api/health")
async def health(db: Session = Depends(get_db)):
    total_users = db.query(User).count()
    return {
        "status":      "ok",
        "version":     "2.0.0",
        "total_users": total_users,
        "sources":     {
            "github":     "ok" if GITHUB_TOKEN else "not_configured",
            "leetcode":   "ok",
            "codeforces": "ok",
            "gmail":      "ok",
            "calendar":   "ok",
            "youtube":    "ok",
            "gemini":     "ok" if GEMINI_API_KEY else "not_configured",
        },
    }


@app.get("/api/user/{user_id}")
async def get_user(user_id: int, db: Session = Depends(get_db)):
    user   = _get_user_or_404(user_id, db)
    linked = user.linked_accounts

    return {
        "id":               user.id,
        "email":            user.email,
        "account_type":     user.account_type,
        "institution_name": user.institution_name,
        "goal_1":           user.goal_1 or "",
        "goal_2":           user.goal_2 or "",
        "goal_3":           user.goal_3 or "",
        "created_at":       user.created_at.isoformat() if user.created_at else None,
        "has_google":        bool(linked and linked.google_access_token),
        "has_github":        bool(linked and linked.github_access_token),
        "github_username":   linked.github_access_token if linked else None,
        "codeforces_handle": linked.codeforces_handle if linked else None,
        "leetcode_username": linked.leetcode_username if linked else None,
    }


@app.patch("/api/user/{user_id}/goals")
async def update_goals(
    user_id: int,
    body: GoalsUpdate,
    db: Session = Depends(get_db),
):
    user = _get_user_or_404(user_id, db)
    if body.goal_1 is not None:
        user.goal_1 = body.goal_1
    if body.goal_2 is not None:
        user.goal_2 = body.goal_2
    if body.goal_3 is not None:
        user.goal_3 = body.goal_3
    db.commit()
    return {"success": True, "goal_1": user.goal_1, "goal_2": user.goal_2, "goal_3": user.goal_3}


@app.patch("/api/user/{user_id}/handles")
async def update_handles(
    user_id: int,
    body: HandlesUpdate,
    db: Session = Depends(get_db),
):
    user   = _get_user_or_404(user_id, db)
    linked = user.linked_accounts
    if not linked:
        linked = LinkedAccount(user_id=user.id)
        db.add(linked)

    if body.codeforces_handle is not None:
        linked.codeforces_handle = body.codeforces_handle
    if body.leetcode_username is not None:
        linked.leetcode_username = body.leetcode_username
    db.commit()
    return {"success": True}


@app.patch("/api/user/{user_id}/github-token")
async def update_github_token(
    user_id: int,
    body: GithubTokenUpdate,
    db: Session = Depends(get_db),
):
    user   = _get_user_or_404(user_id, db)
    linked = user.linked_accounts
    if not linked:
        linked = LinkedAccount(user_id=user.id)
        db.add(linked)
    linked.github_access_token = body.github_token
    db.commit()
    return {"success": True}


@app.patch("/api/user/{user_id}/github-username")
async def update_github_username(
    user_id: int,
    body: GithubUsernameUpdate,
    db: Session = Depends(get_db),
):
    user   = _get_user_or_404(user_id, db)
    linked = user.linked_accounts
    if not linked:
        linked = LinkedAccount(user_id=user.id)
        db.add(linked)
    linked.github_access_token = body.github_username.strip().lstrip("@")
    db.commit()
    return {"success": True}


# ── Per-source data endpoints ──────────────────────────────────────────────────

@app.get("/api/data/github")
async def data_github(user_id: int = Query(...), db: Session = Depends(get_db)):
    username = _resolve_github_username(user_id, db)
    if not username:
        raise HTTPException(status_code=401, detail="GitHub username not set. Add your GitHub username in Dashboard settings.")
    try:
        result = _fetch_github_cached(username)
        result.pop("_events", None)   # don't expose raw events in API response
        return result
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@app.get("/api/data/leetcode")
async def data_leetcode(user_id: int = Query(...), db: Session = Depends(get_db)):
    user   = _get_user_or_404(user_id, db)
    linked = user.linked_accounts
    handle = (linked.leetcode_username if linked else None) or ""
    if not handle:
        raise HTTPException(status_code=400, detail="LeetCode username not set. Update your handles in settings.")
    try:
        return _fetch_leetcode(handle)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@app.get("/api/data/codeforces")
async def data_codeforces(user_id: int = Query(...), db: Session = Depends(get_db)):
    user   = _get_user_or_404(user_id, db)
    linked = user.linked_accounts
    handle = (linked.codeforces_handle if linked else None) or ""
    if not handle:
        raise HTTPException(status_code=400, detail="Codeforces handle not set. Update your handles in settings.")
    try:
        return _fetch_codeforces(handle)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@app.get("/api/data/gmail")
async def data_gmail(user_id: int = Query(...), db: Session = Depends(get_db)):
    token  = _get_valid_google_token(user_id, db)
    emails = _fetch_gmail(token)
    return {
        "summary": f"Found {len(emails)} relevant developer opportunity email(s).",
        "emails":  emails,
    }


@app.get("/api/data/calendar")
async def data_calendar(user_id: int = Query(...), db: Session = Depends(get_db)):
    token  = _get_valid_google_token(user_id, db)
    events = _fetch_calendar_events(token)
    return {"events": events}

async def _fetch_all_data(user_id: int, db: Session) -> dict[str, Any]:
    """Fetch all user data in parallel (GitHub, LeetCode, Codeforces, Gmail, Calendar)."""
    user   = _get_user_or_404(user_id, db)
    linked = user.linked_accounts

    gh_username = _resolve_github_username(user_id, db)
    lc_handle   = linked.leetcode_username if linked else None
    cf_handle   = linked.codeforces_handle if linked else None
    g_token     = refresh_google_token_if_needed(user_id, db)

    async def safe_github():
        if not gh_username:
            return None
        try:
            d = await _run(_fetch_github_cached, gh_username)
            d.pop("_events", None)
            return d
        except Exception:
            return None

    async def safe_leetcode():
        if not lc_handle:
            return None
        try:
            return await _run(_fetch_leetcode, lc_handle)
        except Exception:
            return None

    async def safe_codeforces():
        if not cf_handle:
            return None
        try:
            return await _run(_fetch_codeforces, cf_handle)
        except Exception:
            return None

    async def safe_gmail():
        if not g_token:
            return None
        try:
            return await _run(_fetch_gmail, g_token)
        except Exception:
            return None

    async def safe_calendar():
        if not g_token:
            return None
        try:
            return {"events": await _run(_fetch_calendar_events, g_token)}
        except Exception:
            return None

    gh, lc, cf, gmail, cal = await asyncio.gather(
        safe_github(), safe_leetcode(), safe_codeforces(), safe_gmail(), safe_calendar()
    )

    return {
        "github":       gh,
        "leetcode":     lc,
        "codeforces":   cf,
        "gmail":        gmail,
        "calendar":     cal,
        "generated_at": datetime.utcnow().isoformat(),
    }


@app.get("/api/data/all")
async def data_all(user_id: int = Query(...), db: Session = Depends(get_db)):
    return await _fetch_all_data(user_id, db)


# ── YouTube watch-history upload ───────────────────────────────────────────────

@app.post("/api/youtube/upload-history")
async def upload_youtube_history(
    user_id: int = Query(...),
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
):
    _get_user_or_404(user_id, db)

    raw = await file.read()
    if len(raw) > 50 * 1024 * 1024:
        raise HTTPException(status_code=413, detail="File too large (max 50 MB)")

    analysis = _parse_youtube_history(raw)
    return analysis


@app.get("/api/data/youtube/liked")
async def data_youtube_liked(user_id: int = Query(...), db: Session = Depends(get_db)):
    token = _get_valid_google_token(user_id, db)
    try:
        return _fetch_youtube_liked(token)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


# ── Gemini AI coach with calendar scheduling ───────────────────────────────────

@app.post("/api/agent/ask")
async def ask_agent(body: AskRequest):
    # coraldevmirror: hardcoded demo user, no DB lookup
    system_prompt = _SYSTEM_PROMPT_TEMPLATE.format(
        goal_1="Crack LeetCode 150",
        goal_2="Reach CF 1600",
        goal_3="Land a top internship",
        today=datetime.utcnow().strftime("%Y-%m-%d"),
    )
    raw_response, _ok = call_ai(system_prompt, body.question)
    return {
        "response":         raw_response,
        "scheduled_events": [],
        "is_schedule":      False,
    }


# ── Backward-compatible endpoints (single-user fallback) ─────────────────────

@app.get("/api/dsa")
async def dsa_compat(user_id: Optional[int] = Query(None), db: Session = Depends(get_db)):
    # coraldevmirror: always use Coral demo handles
    lc = _fetch_leetcode(CORAL_DEMO_LC_HANDLE)
    cf = _fetch_codeforces(CORAL_DEMO_CF_HANDLE)
    return {"leetcode": lc, "codeforces": cf}


@app.get("/api/internship")
async def internship_compat(user_id: Optional[int] = Query(None), db: Session = Depends(get_db)):
    # coraldevmirror: use Coral Gmail (token ignored)
    emails = _fetch_gmail("")
    return {"summary": f"Found {len(emails)} leads.", "emails": emails}


@app.get("/api/growth-report")
async def growth_report_compat(user_id: Optional[int] = Query(None), db: Session = Depends(get_db)):
    # coraldevmirror: hardcoded demo handles, no DB lookup
    gh, lc, cf = await asyncio.gather(
        _run(_fetch_github_cached, CORAL_DEMO_GH_USERNAME),
        _run(_fetch_leetcode, CORAL_DEMO_LC_HANDLE),
        _run(_fetch_codeforces, CORAL_DEMO_CF_HANDLE),
    )
    if isinstance(gh, dict):
        gh.pop("_events", None)

    # Fetch upcoming calendar events
    token = _get_demo_google_token(db) or ""
    upcoming: list[dict] = []
    if token:
        try:
            for ev in _fetch_calendar_events(token)[:5]:
                start_raw = ev.get("start", "")
                try:
                    start_dt = datetime.fromisoformat(start_raw.replace("Z", "+00:00"))
                    if start_dt.tzinfo is not None:
                        start_dt = start_dt.astimezone(timezone.utc)
                    time_label = start_dt.strftime("%b %-d, %-I:%M %p")
                except Exception:
                    time_label = start_raw[:16]
                upcoming.append({"title": ev.get("summary", "Untitled"), "time": time_label})
        except Exception:
            pass

    gh_commits  = gh.get("commits_week", 0) if gh else 0
    gh_repos    = gh.get("public_repos", gh.get("repos", 0)) if gh else 0
    gh_top_repo = gh.get("top_repo", "") if gh else ""
    gh_langs    = gh.get("languages", []) if gh else []
    lc_total    = lc.get("total_solved", 0) if lc else 0
    lc_streak   = lc.get("streak", 0) if lc else 0
    lc_easy     = lc.get("easy", 0) if lc else 0
    lc_medium   = lc.get("medium", 0) if lc else 0
    lc_hard     = lc.get("hard", 0) if lc else 0
    cf_rating   = cf.get("rating", 0) if cf else 0
    cf_rank     = cf.get("rank", "unrated") if cf else "unrated"
    cf_solved   = cf.get("solved", 0) if cf else 0
    cal_summary = ", ".join(f"{e['title']} on {e['time']}" for e in upcoming) or "no upcoming sessions"

    system_prompt = (
        "You are DevMirror, a sharp AI growth coach for a software engineering student. "
        "Write a motivating, personalised weekly growth report in 200-250 words.\n\n"
        "FORMAT (follow exactly):\n"
        "<first name>, <exciting opening observation about their strongest metric>\n\n"
        "This Week At a Glance:\n"
        "  → GitHub: <commits and top repo insight>\n"
        "  → LeetCode: <total solved, streak, difficulty breakdown insight>\n"
        "  → Codeforces: <rating and rank insight>\n"
        "  → Calendar: <upcoming sessions insight>\n\n"
        "The Pattern I See:\n"
        "<2-3 sentences about what the data reveals about their habits and growth trajectory>\n\n"
        "Today's Nudge:\n"
        "<one specific, actionable recommendation based on their weakest area>\n\n"
        "\"<short motivational quote>\"\n\n"
        "Keep going. <personalised closing line>."
    )
    user_message = (
        f"Student: Yashasvi. "
        f"GitHub: {gh_commits} commits this week across {gh_repos} repos, top repo: {gh_top_repo}, "
        f"languages: {', '.join(gh_langs) or 'unknown'}. "
        f"LeetCode: {lc_total} solved (Easy {lc_easy}, Medium {lc_medium}, Hard {lc_hard}), {lc_streak}-day streak. "
        f"Codeforces: rating {cf_rating} ({cf_rank}), {cf_solved} problems solved. "
        f"Upcoming calendar: {cal_summary}."
    )
    report, ai_ok = call_ai(system_prompt, user_message)
    if not ai_ok:
        report = (
            f"Yashasvi, great progress this week!\n\n"
            f"This Week At a Glance:\n"
            f"  → GitHub: {gh_commits} commits across {gh_repos} repos. Top: {gh_top_repo}.\n"
            f"  → LeetCode: {lc_total} solved (Easy {lc_easy}, Medium {lc_medium}, Hard {lc_hard}), {lc_streak}-day streak.\n"
            f"  → Codeforces: rating {cf_rating} ({cf_rank}), {cf_solved} solved.\n"
            f"  → Calendar: {cal_summary}.\n\n"
            f"Keep going — consistency is what separates good developers from great ones."
        )

    return {
        "report":       report,
        "github":       {"repos": gh_repos, "commits_week": gh_commits, "top_repo": gh_top_repo, "languages": gh_langs},
        "leetcode":     {"total": lc_total, "easy": lc_easy, "medium": lc_medium, "hard": lc_hard, "streak": lc_streak},
        "codeforces":   {"rating": cf_rating, "rank": cf_rank, "solved": cf_solved},
        "calendar":     {"study_hours_week": len(upcoming), "upcoming": upcoming},
        "generated_at": datetime.utcnow().isoformat(),
    }



@app.get("/api/focus")
async def focus_compat(user_id: Optional[int] = Query(None), db: Session = Depends(get_db)):
    # coraldevmirror: hardcoded demo handles, no DB lookup
    lc = _fetch_leetcode(CORAL_DEMO_LC_HANDLE)
    cf = _fetch_codeforces(CORAL_DEMO_CF_HANDLE)
    if lc and lc.get("streak", 0) > 0:
        priority = f"Maintain your {lc['streak']}-day LeetCode streak"
        reasoning = "Streak momentum is hard to rebuild — protect it"
    elif cf and cf.get("rating", 0) < 1200:
        priority = "Attempt a Codeforces Div. 3 contest"
        reasoning = "Contests build speed and pressure-handling"
    else:
        priority = "Push at least one commit today"
        reasoning = "Building habit — even a small commit counts"

    token = _get_demo_google_token(db) or ""

    # Calendar: today's events formatted as {title, time, duration}
    calendar_today: list[dict] = []
    if token:
        try:
            today_utc = datetime.utcnow().strftime("%Y-%m-%d")
            for ev in _fetch_calendar_events(token):
                start_raw = ev.get("start", "")
                if today_utc not in start_raw:
                    continue
                try:
                    start_dt = datetime.fromisoformat(start_raw.replace("Z", "+00:00"))
                    end_dt   = datetime.fromisoformat(ev.get("end", start_raw).replace("Z", "+00:00"))
                    if start_dt.tzinfo is not None:
                        start_dt = start_dt.astimezone(timezone.utc)
                        end_dt   = end_dt.astimezone(timezone.utc)
                    hour   = start_dt.hour % 12 or 12
                    minute = start_dt.strftime("%M")
                    period = "AM" if start_dt.hour < 12 else "PM"
                    time_str = f"{hour}:{minute} {period}"
                    mins = max(0, int((end_dt - start_dt).total_seconds() / 60))
                    dur  = (f"{mins // 60}h" + (f" {mins % 60}m" if mins % 60 else "")) if mins >= 60 else f"{mins}m"
                    calendar_today.append({"title": ev.get("summary", "Untitled"), "time": time_str, "duration": dur})
                except Exception:
                    continue
        except Exception:
            pass

    # YouTube: most recently liked technical videos
    youtube_watched: list[dict] = []
    if token:
        try:
            yt = _fetch_youtube_liked(token)
            for v in yt.get("top_videos", [])[:5]:
                youtube_watched.append({
                    "title":    v.get("title", ""),
                    "channel":  v.get("channel", ""),
                    "duration": "",
                })
        except Exception:
            pass

    # Build context for AI recommendation
    gh = _fetch_github_cached(CORAL_DEMO_GH_USERNAME)
    lc_streak      = lc.get("streak", 0) if lc else 0
    lc_total       = lc.get("total_solved", 0) if lc else 0
    lc_easy        = lc.get("easy", 0) if lc else 0
    lc_medium      = lc.get("medium", 0) if lc else 0
    lc_hard        = lc.get("hard", 0) if lc else 0
    lc_acceptance  = lc.get("acceptance_rate", 0) if lc else 0
    lc_recent      = lc.get("recent", []) if lc else []
    cf_rating      = cf.get("rating", 0) if cf else 0
    cf_rank        = cf.get("rank", "unrated") if cf else "unrated"
    cf_solved      = cf.get("solved", 0) if cf else 0
    gh_commits     = gh.get("commits_week", 0) if gh else 0
    gh_top_repo    = gh.get("top_repo", "") if gh else ""
    cal_summary    = ", ".join(f"{e['title']} at {e['time']}" for e in calendar_today) or "no events found"
    yt_summary     = ", ".join(f"{v['title']} ({v['channel']})" for v in youtube_watched[:3]) or "no videos found"
    recent_lc_str  = ", ".join(f"{p['title']} ({p['difficulty']})" for p in lc_recent[:3]) if lc_recent else "none"

    system_prompt = (
        "You are DevMirror, a sharp and motivating AI coach for a software engineering student. "
        "Analyse the data and write a focused, personalised daily brief.\n\n"
        "FORMAT (follow exactly):\n"
        "Based on everything I see, your #1 focus today is:\n\n"
        "  <one clear, specific action>\n\n"
        "Here's why this is the right move today:\n"
        "  → <insight from LeetCode data>\n"
        "  → <insight from Codeforces data>\n"
        "  → <insight from calendar>\n"
        "  → <insight from GitHub or YouTube>\n\n"
        "<one concrete tip with specifics — e.g. a problem type, topic, or repo to touch>\n\n"
        "<short closing motivational line>\n\n"
        "Keep it under 200 words. Be direct, specific, and encouraging. No bullet-point lists beyond the → arrows."
    )

    user_message = (
        f"LeetCode: {lc_total} solved (Easy {lc_easy}, Medium {lc_medium}, Hard {lc_hard}), "
        f"{lc_streak}-day streak, {lc_acceptance:.1f}% acceptance rate. "
        f"Recent problems: {recent_lc_str}.\n"
        f"Codeforces: rating {cf_rating} ({cf_rank}), {cf_solved} problems solved.\n"
        f"GitHub: {gh_commits} commits this week, top repo: {gh_top_repo or 'unknown'}.\n"
        f"Google Calendar today: {cal_summary}.\n"
        f"Recently liked YouTube videos: {yt_summary}.\n"
        f"Determined priority: {priority}. Reasoning: {reasoning}."
    )

    recommendation, ai_ok = call_ai(system_prompt, user_message)
    if not ai_ok:
        recommendation = (
            f"Based on everything I see, your #1 focus today is:\n\n"
            f"  {priority}\n\n"
            f"Here's why this is the right move today:\n"
            f"  → {reasoning}\n"
            f"  → LeetCode streak: {lc_streak} days — every day counts.\n"
            f"  → Codeforces rating: {cf_rating} ({cf_rank}).\n"
            f"  → GitHub: {gh_commits} commit(s) this week.\n\n"
            f"Stay consistent — small daily actions compound into big results."
        )

    return {
        "recommendation": recommendation,
        "priority_task":  priority,
        "reasoning":      reasoning,
        "calendar_today":  calendar_today,
        "youtube_watched": youtube_watched,
    }



@app.get("/api/learn-vs-build")
async def lvb_compat(user_id: Optional[int] = Query(None), db: Session = Depends(get_db)):
    # coraldevmirror: hardcoded demo handles, no DB lookup
    gh = _fetch_github_cached(CORAL_DEMO_GH_USERNAME)
    lc = _fetch_leetcode(CORAL_DEMO_LC_HANDLE)
    commits = gh.get("commits_week", 0) if gh else 0
    solved  = lc.get("total_solved", 0) if lc else 0
    lc_streak = lc.get("streak", 0) if lc else 0

    # Score: build from commits (cap at 100), learn from LC problems solved (cap at 100)
    build_score = min(100, commits * 5)
    learn_score = min(100, solved * 4)
    total = learn_score + build_score or 1
    learn_pct = round(learn_score / total * 100)
    build_pct  = 100 - learn_pct
    balance = "balanced" if abs(learn_pct - build_pct) < 15 else ("learning_heavy" if learn_pct > build_pct else "building_heavy")

    # Generate 6-week trend with slight variation around current scores
    import random; random.seed(42)
    now = datetime.utcnow()
    trend = []
    for i in range(5, -1, -1):
        wk = now - timedelta(weeks=i)
        label = f"{wk.strftime('%b')} W{(wk.day - 1) // 7 + 1}"
        var = random.randint(-8, 8)
        lp = max(5, min(95, learn_pct + var + (i * 2)))
        trend.append({"week": label, "learn": lp, "build": 100 - lp})

    system_prompt = (
        "You are DevMirror, an AI coach analysing a developer's learn vs build balance. "
        "Write an insightful 120-150 word analysis.\n\n"
        "FORMAT:\n"
        "<opening line about their balance status>\n\n"
        "This week you spent roughly <X hours/sessions> learning (LeetCode + study) vs <Y> building (GitHub commits).\n\n"
        "That's a <ratio> ratio — <judgement at their stage>. The risk zone is when it flips to 4:1 or higher.\n\n"
        "Key observation: <specific insight about what the data shows>\n\n"
        "Action: <one concrete next-week suggestion>\n\n"
        "<short closing motivational line>."
    )
    user_message = (
        f"GitHub commits this week: {commits}. LeetCode problems solved total: {solved} ({lc_streak}-day streak). "
        f"Learn score: {learn_pct}%, Build score: {build_pct}%. Balance: {balance}."
    )
    analysis, ai_ok = call_ai(system_prompt, user_message)
    if not ai_ok:
        analysis = (
            f"Your learn/build balance is {balance.replace('_', ' ')} this week.\n\n"
            f"You made {commits} commits and solved {solved} LeetCode problems.\n\n"
            f"Learn: {learn_pct}% · Build: {build_pct}%\n\n"
            f"Action: {'Push one more commit this week.' if learn_pct > 60 else 'Try one more LeetCode problem today.'}"
        )

    return {
        "analysis":            analysis,
        "learn_score":         learn_pct,
        "build_score":         build_pct,
        "balance":             balance,
        "github_commits_week": commits,
        "youtube_hours_week":  0,
        "study_hours_week":    solved,
        "trend":               trend,
    }




@app.get("/api/coral/youtube")
async def coral_youtube(db: Session = Depends(get_db)):
    """YouTube liked videos via Coral SQL; falls back to demo user's Google token if Coral unavailable."""
    try:
        token = _get_demo_google_token(db) or ""
        result = _fetch_youtube_liked(token)
        return result
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@app.get("/api/coral/gmail")
async def coral_gmail(db: Session = Depends(get_db)):
    """Gmail opportunities via Coral SQL; falls back to demo user's Google token if Coral unavailable."""
    try:
        token = _get_demo_google_token(db) or ""
        emails = _fetch_gmail(token)
        return {"summary": f"Found {len(emails)} developer opportunity email(s).", "emails": emails}
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@app.get("/api/coral/codeforces")
async def coral_codeforces():
    """Codeforces data via Coral SQL — no auth required."""
    try:
        return _fetch_codeforces(CORAL_DEMO_CF_HANDLE)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@app.get("/api/coral/github")
async def coral_github():
    """GitHub data via direct API — no auth required."""
    try:
        result = _fetch_github_cached(CORAL_DEMO_GH_USERNAME)
        result.pop("_events", None)
        return result
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@app.get("/api/coral/leetcode")
async def coral_leetcode():
    """LeetCode data via direct API — no auth required."""
    try:
        return _fetch_leetcode(CORAL_DEMO_LC_HANDLE)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@app.get("/api/coral/calendar")
async def coral_calendar(db: Session = Depends(get_db)):
    """Google Calendar events via Coral SQL; falls back to demo user's Google token if Coral unavailable."""
    try:
        token = _get_demo_google_token(db) or ""
        rows = coral_client.get_calendar_events(token)
        if rows is None:
            # Coral unavailable — use direct Calendar API with the same token
            if token:
                events = _fetch_calendar_events(token)
                return {"events": events}
            return {"events": []}
        now = datetime.utcnow()
        cutoff = now - timedelta(days=1)  # include events from yesterday onwards
        events = []
        for r in rows:
            start_raw = str(r.get("start_date_time") or r.get("start_date") or "")
            if not start_raw:
                continue
            try:
                if "T" in start_raw:
                    start_dt = datetime.fromisoformat(start_raw.replace("Z", "+00:00"))
                    # Convert timezone-aware dt to naive UTC for comparison
                    if start_dt.tzinfo is not None:
                        start_dt = start_dt.astimezone(timezone.utc).replace(tzinfo=None)
                else:
                    start_dt = datetime.strptime(start_raw[:10], "%Y-%m-%d")
            except (ValueError, TypeError):
                continue
            if start_dt < cutoff:
                continue
            events.append({
                "id":          r.get("id", ""),
                "summary":     r.get("summary", ""),
                "description": r.get("description", ""),
                "start":       start_raw,
                "end":         str(r.get("end_date_time") or r.get("end_date") or ""),
                "_sort":       start_dt,
            })
        events.sort(key=lambda e: e["_sort"])
        for e in events:
            e.pop("_sort", None)
        # Coral returned stale/empty data — fall back to live Google Calendar API
        if not events and token:
            live = _fetch_calendar_events(token)
            if live:
                return {"events": live}
        return {"events": events[:30]}
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@app.get("/api/coral/all")
async def coral_all():
    """All data via Coral SQL + direct APIs — no auth required."""
    gh, lc, cf, gmail_raw, cal_rows = await asyncio.gather(
        _run(_fetch_github_cached, CORAL_DEMO_GH_USERNAME),
        _run(_fetch_leetcode, CORAL_DEMO_LC_HANDLE),
        _run(_fetch_codeforces, CORAL_DEMO_CF_HANDLE),
        _run(_fetch_gmail, ""),
        _run(coral_client.get_calendar_events, "", "", ""),
    )
    if isinstance(gh, dict):
        gh.pop("_events", None)
    cal_events = None
    if cal_rows:
        cal_events = [
            {
                "id":          r.get("id", ""),
                "summary":     r.get("summary", ""),
                "description": r.get("description", ""),
                "start":       str(r.get("start_date_time") or r.get("start_date") or ""),
                "end":         str(r.get("end_date_time") or r.get("end_date") or ""),
            }
            for r in cal_rows
        ]
    return {
        "github":       gh,
        "leetcode":     lc,
        "codeforces":   cf,
        "gmail":        gmail_raw,
        "calendar":     {"events": cal_events} if cal_events else None,
        "generated_at": datetime.utcnow().isoformat(),
    }


@app.get("/api/coral/user")
async def coral_user():
    """Hardcoded demo user profile — no auth required."""
    return {
        "id":                1,
        "email":             "yashasvithakur2005@gmail.com",
        "account_type":      "personal",
        "institution_name":  None,
        "goal_1":            "Crack LeetCode 150",
        "goal_2":            "Reach CF 1600",
        "goal_3":            "Land a top internship",
        "created_at":        None,
        "has_google":        True,
        "has_github":        True,
        "github_username":   CORAL_DEMO_GH_USERNAME,
        "codeforces_handle": CORAL_DEMO_CF_HANDLE,
        "leetcode_username": CORAL_DEMO_LC_HANDLE,
    }


# ── Entry point ────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import uvicorn
    port = int(os.getenv("PORT", 8000))
    uvicorn.run("main:app", host="0.0.0.0", port=port, reload=True)
