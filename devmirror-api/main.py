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
from datetime import datetime, timedelta
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


def _build_github_result(username: str, user_data: dict, repos: list, events: list) -> dict[str, Any]:
    """Shared result builder used by both the Coral and direct-API GitHub paths."""
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
        "public_repos":      user_data.get("public_repos", 0) or 0,
        "followers":         user_data.get("followers", 0) or 0,
        "avatar_url":        user_data.get("avatar_url", "") or "",
        "_events":           events,
    }


def _fetch_github(github_username: str) -> dict[str, Any]:
    """Fetch GitHub data via Coral SQL first, falling back to the direct GitHub API."""
    username = github_username.strip().lstrip("@")

    # Try Coral first
    if GITHUB_TOKEN:
        coral_user   = coral_client.get_github_user(GITHUB_TOKEN)
        coral_repos  = coral_client.get_github_repos(GITHUB_TOKEN, username)
        coral_events = coral_client.get_github_events(GITHUB_TOKEN, username)
        if coral_repos is not None and coral_events is not None:
            return _build_github_result(username, coral_user or {}, coral_repos, coral_events)

    # Fall back to direct GitHub API
    headers = {"Accept": "application/vnd.github+json"}
    if GITHUB_TOKEN:
        headers["Authorization"] = f"Bearer {GITHUB_TOKEN}"

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

    return _build_github_result(username, gh_user, repos, events)


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
    totals_query = """
    query {
        allQuestionsCount { difficulty count }
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
        totals_resp = requests.post(
            "https://leetcode.com/graphql",
            json={"query": totals_query},
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

    # Total available problems per difficulty from LeetCode
    lc_totals: dict[str, int] = {"Easy": 814, "Medium": 1715, "Hard": 741}  # fallback
    try:
        if totals_resp.status_code == 200:
            raw_totals = (totals_resp.json().get("data") or {}).get("allQuestionsCount") or []
            fetched = {t["difficulty"]: t["count"] for t in raw_totals}
            if fetched.get("Easy") and fetched.get("Medium") and fetched.get("Hard"):
                lc_totals = fetched
    except Exception:
        pass

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
        "easy_total":        lc_totals.get("Easy", 814),
        "medium_total":      lc_totals.get("Medium", 1715),
        "hard_total":        lc_totals.get("Hard", 741),
        "streak":            streak,
        "total_active_days": calendar.get("totalActiveDays", 0),
        "acceptance_rate":   acceptance_rate,
        "ranking":           profile.get("ranking", 0),
        "recent":            recent,
    }


def _empty_leetcode(username: str) -> dict[str, Any]:
    return {
        "username": username, "total_solved": 0, "easy": 0, "medium": 0,
        "hard": 0, "easy_total": 814, "medium_total": 1715, "hard_total": 741,
        "streak": 0, "total_active_days": 0, "acceptance_rate": 0.0,
        "ranking": 0, "recent": [],
    }


# ── Codeforces data pipeline ───────────────────────────────────────────────────

def _fetch_codeforces(handle: str) -> dict[str, Any]:
    coral_user = coral_client.get_codeforces_user(handle)
    if coral_user is not None:
        coral_subs = coral_client.get_codeforces_submissions(handle) or []
        solved: set[str] = set()
        recent: list[dict] = []
        for sub in coral_subs:
            prob_key = f"{sub.get('contest_id', '')}{sub.get('problem_index', '')}"
            if sub.get("verdict") == "OK":
                solved.add(prob_key)
            if len(recent) < 10:
                ts = sub.get("submitted_at") or 0
                recent.append({
                    "problem": sub.get("problem_name", ""),
                    "verdict": sub.get("verdict", ""),
                    "rating":  sub.get("problem_rating") or 0,
                    "date":    datetime.utcfromtimestamp(ts).strftime("%Y-%m-%d") if ts else "",
                })
        return {
            "handle":     handle,
            "rating":     coral_user.get("rating") or 0,
            "max_rating": coral_user.get("max_rating") or 0,
            "rank":       coral_user.get("rank") or "unrated",
            "max_rank":   coral_user.get("max_rank") or "unrated",
            "solved":     len(solved),
            "avatar":     coral_user.get("avatar") or "",
            "recent":     recent,
        }
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
                    recent.append({
                        "problem": prob.get("name", ""),
                        "verdict": sub.get("verdict", ""),
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
    # Try Coral SQL first — passes token via env var so each user gets their own data
    coral_rows = coral_client.get_gmail_opportunities(access_token)
    if coral_rows is not None:
        results = []
        for row in coral_rows:
            subject = row.get("snippet", "")[:80]
            results.append({
                "id":              row.get("id", ""),
                "subject":         subject,
                "from":            "",
                "date":            "",
                "snippet":         row.get("snippet", ""),
                "category":        _categorize_subject(subject),
                "ai_summary":      "",
                "action_required": False,
                "gmail_link":      f"https://mail.google.com/mail/u/0/#inbox/{row.get('id', '')}",
            })
        return results

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
        "You are a classifier that identifies YouTube videos related to software development, computer science, or tech learning.\n\n"
        "Be INCLUSIVE. A video qualifies if it covers ANY of: programming, algorithms, data structures, web/mobile/backend dev, "
        "ML/AI, system design, DevOps, Linux, Git, databases, networking, competitive programming, tech career, coding interviews, "
        "or any tech tutorial. When in doubt, include it.\n\n"
        "Video titles:\n"
        f"{numbered}\n\n"
        "Return ONLY valid JSON — an array of objects for every qualifying video:\n"
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
                        tech_videos.append({**video, "category": cat})
        else:
            for video in raw_videos:
                cat = _classify_video_keywords(video["title"], video["channel"])
                cat_counts[cat] += 1
                if cat != "Non-Technical":
                    tech_videos.append({**video, "category": cat})
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
   Use markdown: **bold**, ## headers, bullet points. Max 350 words.
   Reference their goals when relevant. Be direct and actionable.

3. Never be vague. Never shame. Celebrate progress. Always give one concrete next action.
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
        "model": "command-r",
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
    """Call the appropriate AI API (Cohere preferred, fall back to Gemini)."""
    if USE_COHERE:
        return _call_cohere(system_prompt, user_message)
    else:
        return _call_gemini(system_prompt, user_message)


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
async def ask_agent(body: AskRequest, db: Session = Depends(get_db)):
    user = _get_user_or_404(body.user_id, db)

    system_prompt = _SYSTEM_PROMPT_TEMPLATE.format(
        goal_1=user.goal_1 or "Not set",
        goal_2=user.goal_2 or "Not set",
        goal_3=user.goal_3 or "Not set",
        today=datetime.utcnow().strftime("%Y-%m-%d"),
    )

    raw_response, gemini_ok = call_ai(system_prompt, body.question)
    scheduled_events: list[dict] = []

    if gemini_ok and _is_scheduling_request(body.question):
        events_payload = _extract_json_array(raw_response)
        if events_payload:
            g_token = refresh_google_token_if_needed(body.user_id, db)
            if g_token:
                for ev in events_payload:
                    if "start_time" in ev and "end_time" in ev:
                        created = _create_calendar_event(g_token, ev)
                        scheduled_events.append({
                            "id":      created.get("id", ""),
                            "summary": ev.get("summary", ""),
                            "start":   ev.get("start_time", ""),
                            "end":     ev.get("end_time", ""),
                        })
            return {
                "response":         f"I've scheduled {len(scheduled_events)} event(s) on your Google Calendar.",
                "scheduled_events": scheduled_events,
                "is_schedule":      True,
            }

    return {
        "response":         raw_response,
        "scheduled_events": [],
        "is_schedule":      False,
    }


# ── Backward-compatible endpoints (single-user fallback) ─────────────────────

@app.get("/api/dsa")
async def dsa_compat(user_id: Optional[int] = Query(None), db: Session = Depends(get_db)):
    if not user_id:
        return {"leetcode": _empty_leetcode(""), "codeforces": _empty_codeforces("")}
    user   = db.query(User).filter(User.id == user_id).first()
    linked = user.linked_accounts if user else None
    lc     = _fetch_leetcode(linked.leetcode_username) if (linked and linked.leetcode_username) else _empty_leetcode("")
    cf     = _fetch_codeforces(linked.codeforces_handle) if (linked and linked.codeforces_handle) else _empty_codeforces("")
    return {"leetcode": lc, "codeforces": cf}


@app.get("/api/internship")
async def internship_compat(user_id: Optional[int] = Query(None), db: Session = Depends(get_db)):
    if not user_id:
        return {"summary": "No user_id provided. Please log in.", "emails": []}
    try:
        token  = _get_valid_google_token(user_id, db)
        emails = _fetch_gmail(token)
        return {"summary": f"Found {len(emails)} leads.", "emails": emails}
    except HTTPException:
        return {"summary": "Gmail not connected.", "emails": []}


@app.get("/api/growth-report")
async def growth_report_compat(user_id: Optional[int] = Query(None), db: Session = Depends(get_db)):
    if not user_id:
        return {
            "report": "Please log in to generate your growth report.",
            "github": {"repos": 0, "commits_week": 0, "top_repo": "", "languages": []},
            "leetcode": {"total": 0, "easy": 0, "medium": 0, "hard": 0, "streak": 0},
            "codeforces": {"rating": 0, "rank": "unrated", "solved": 0},
            "calendar": {"study_hours_week": 0, "upcoming": []},
            "generated_at": datetime.utcnow().isoformat(),
        }

    user   = db.query(User).filter(User.id == user_id).first()
    result = await _fetch_all_data(user_id=user_id, db=db)
    lc_raw  = result.get("leetcode") or {}
    cf_raw  = result.get("codeforces") or {}
    gh_raw  = result.get("github") or {}
    cal_raw = result.get("calendar") or {}

    # Normalise to match GrowthReportData interface
    lc = {
        "total":  lc_raw.get("total_solved", 0),
        "easy":   lc_raw.get("easy", 0),
        "medium": lc_raw.get("medium", 0),
        "hard":   lc_raw.get("hard", 0),
        "streak": lc_raw.get("streak", 0),
    }
    cf = {
        "rating": cf_raw.get("rating", 0),
        "rank":   cf_raw.get("rank", "unrated"),
        "solved": cf_raw.get("solved", 0),
    }
    gh = {
        "repos":        gh_raw.get("public_repos", gh_raw.get("repos", 0)),
        "commits_week": gh_raw.get("commits_week", 0),
        "top_repo":     gh_raw.get("top_repo", ""),
        "languages":    gh_raw.get("languages", []),
    }

    # Calculate study hours and upcoming events from calendar
    events = cal_raw.get("events", [])
    study_kws = {"study", "learn", "practice", "leetcode", "dsa", "review", "course", "tutorial"}
    study_hours = 0.0
    upcoming = []
    for ev in events[:5]:
        title = ev.get("summary", "")
        start = ev.get("start", "")
        upcoming.append({"title": title, "time": start[:16].replace("T", " ") if "T" in start else start[:10]})
        if any(kw in title.lower() for kw in study_kws) and "T" in start:
            try:
                sd = datetime.fromisoformat(start.replace("Z", "+00:00"))
                ed = datetime.fromisoformat(ev.get("end", "").replace("Z", "+00:00"))
                study_hours += min((ed - sd).total_seconds() / 3600, 8)
            except Exception:
                pass
    cal = {"study_hours_week": round(study_hours, 1), "upcoming": upcoming[:3]}

    # Generate AI report via Gemini (with fallback)
    today_str = datetime.utcnow().strftime("%Y-%m-%d")
    goals = f"{user.goal_1 or 'Not set'} / {user.goal_2 or 'Not set'} / {user.goal_3 or 'Not set'}" if user else "Not set"
    question = (
        f"Generate a motivating growth report for this developer (today: {today_str}):\n\n"
        f"GitHub: {gh['commits_week']} commits this week, top repo: {gh['top_repo'] or 'N/A'}, "
        f"languages: {', '.join(gh['languages'][:3]) or 'N/A'}\n"
        f"LeetCode: {lc['total']} solved ({lc['easy']} easy / {lc['medium']} medium / {lc['hard']} hard), "
        f"{lc['streak']}-day streak\n"
        f"Codeforces: Rating {cf['rating']} ({cf['rank']}), {cf['solved']} solved\n"
        f"Calendar: {study_hours:.1f}h study time, {len(events)} upcoming events\n"
        f"Goals: {goals}\n\n"
        f"Write a personal, energetic 150-200 word coaching report. "
        f"Reference specific numbers. End with a concrete next action. End with ∎"
    )
    system_prompt = _SYSTEM_PROMPT_TEMPLATE.format(
        goal_1=user.goal_1 if user else "Not set",
        goal_2=user.goal_2 if user else "Not set",
        goal_3=user.goal_3 if user else "Not set",
        today=today_str,
    )
    report, gemini_ok = await _run(call_ai, system_prompt, question)

    # If AI failed, provide a fallback report with real stats
    if not gemini_ok:
        report = (
            f"**Your Growth Report**\n\n"
            f"**GitHub**: {gh['commits_week']} commits this week | "
            f"{gh.get('repos', 0)} public repos | Top: {gh['top_repo'] or 'N/A'}\n"
            f"**LeetCode**: {lc['total']} problems solved | "
            f"{lc['easy']} Easy, {lc['medium']} Medium, {lc['hard']} Hard | "
            f"{lc['streak']}-day streak\n"
            f"**Codeforces**: Rating {cf['rating']} ({cf['rank']}) | {cf['solved']} problems solved\n"
            f"**Study**: {study_hours:.1f}h this week | {len(events)} calendar events\n\n"
            f"*AI analysis unavailable. Check back when the AI service is available.*"
        )

    return {
        "report":       report,
        "github":       gh,
        "leetcode":     lc,
        "codeforces":   cf,
        "calendar":     cal,
        "generated_at": datetime.utcnow().isoformat(),
    }


@app.get("/api/focus")
async def focus_compat(user_id: Optional[int] = Query(None), db: Session = Depends(get_db)):
    if not user_id:
        return {
            "recommendation": "Log in to get a personalised focus recommendation from your real data.",
            "priority_task":  "Set up your DevMirror profile",
            "reasoning":      "Connect GitHub, LeetCode and Codeforces to unlock AI coaching.",
            "calendar_today": [],
            "youtube_watched": [],
        }

    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        return {
            "recommendation": "User not found. Please log in again.",
            "priority_task":  "Log in", "reasoning": "",
            "calendar_today": [], "youtube_watched": [],
        }

    linked      = user.linked_accounts
    gh_username = _resolve_github_username(user_id, db)
    g_token     = refresh_google_token_if_needed(user_id, db)

    async def _lc():
        if linked and linked.leetcode_username:
            try: return await _run(_fetch_leetcode, linked.leetcode_username)
            except Exception: pass
        return None

    async def _cf():
        if linked and linked.codeforces_handle:
            try: return await _run(_fetch_codeforces, linked.codeforces_handle)
            except Exception: pass
        return None

    async def _gh():
        if gh_username:
            try:
                d = await _run(_fetch_github_cached, gh_username)
                d.pop("_events", None)
                return d
            except Exception: pass
        return None

    async def _cal():
        if g_token:
            try: return await _run(_fetch_calendar_events, g_token)
            except Exception: pass
        return []

    lc, cf, gh, calendar_events = await asyncio.gather(_lc(), _cf(), _gh(), _cal())
    calendar_events = calendar_events or []

    today_str = datetime.utcnow().strftime("%A, %Y-%m-%d")
    stats = f"Today is {today_str}.\n"

    if lc:
        stats += (
            f"\nLeetCode: {lc['total_solved']} solved "
            f"({lc['easy']} easy / {lc['medium']} medium / {lc['hard']} hard), "
            f"{lc.get('streak', 0)}-day streak, "
            f"{lc.get('acceptance_rate', 0):.1f}% acceptance rate.\n"
        )
        if lc.get("recent"):
            titles = ", ".join(p["title"] for p in lc["recent"][:3])
            stats += f"Recent problems: {titles}.\n"

    if cf:
        stats += f"\nCodeforces: Rating {cf['rating']} ({cf['rank']}), {cf.get('solved', 0)} solved.\n"

    if gh:
        stats += (
            f"\nGitHub: {gh.get('commits_week', 0)} commits this week, "
            f"top repo: {gh.get('top_repo', 'N/A')}, "
            f"languages: {', '.join(gh.get('languages', [])[:3])}.\n"
        )

    # Use a ±12h window so events match regardless of user's timezone
    now_utc = datetime.utcnow()
    window_start = (now_utc - timedelta(hours=12)).date()
    window_end   = (now_utc + timedelta(hours=12)).date()
    today_events = []
    for e in calendar_events:
        start = e.get("start") or ""
        try:
            # Handle both all-day events (YYYY-MM-DD) and timed events (YYYY-MM-DDTHH:MM:SS...)
            if "T" in start:
                event_date = datetime.fromisoformat(start.replace("Z", "+00:00")).date()
            else:
                event_date = datetime.strptime(start, "%Y-%m-%d").date()
            if window_start <= event_date <= window_end:
                today_events.append(e)
        except (ValueError, AttributeError, TypeError):
            pass
    if today_events:
        titles = ", ".join(e["summary"] for e in today_events[:3])
        stats += f"\nCalendar today: {titles}.\n"

    question = (
        f"Based on this developer's current data, give a focused daily recommendation:\n\n"
        f"{stats}\n"
        f"Goals: {user.goal_1 or 'Not set'} / {user.goal_2 or 'Not set'} / {user.goal_3 or 'Not set'}\n\n"
        f"Give a specific, motivating focus recommendation for today. Be concrete — name "
        f"actual problem types, repos, or skills. Keep it under 200 words. End with ∎"
    )

    system_prompt = _SYSTEM_PROMPT_TEMPLATE.format(
        goal_1=user.goal_1 or "Not set",
        goal_2=user.goal_2 or "Not set",
        goal_3=user.goal_3 or "Not set",
        today=today_str,
    )

    recommendation, gemini_ok = await _run(call_ai, system_prompt, question)

    # If AI failed, provide a basic recommendation
    if not gemini_ok:
        recommendation = (
            "**Focus Today**\n\n"
            "AI analysis is temporarily unavailable. "
            "Check the data below and your calendar for guidance."
        )

    # Derive priority task heuristically
    if lc and lc.get("streak", 0) > 0:
        priority_task = f"Maintain your {lc['streak']}-day LeetCode streak"
        reasoning = "Streak momentum is hard to rebuild — protect it"
    elif lc and lc.get("total_solved", 0) < 50:
        priority_task = "Solve 2 LeetCode problems (Easy → Medium)"
        reasoning = "Foundation-building phase — consistency beats intensity"
    elif cf and cf.get("rating", 0) < 1200:
        priority_task = "Attempt a Codeforces Div. 3 contest"
        reasoning = "Contests build speed and pressure-handling"
    elif gh and gh.get("commits_week", 0) == 0:
        priority_task = "Push at least one commit today"
        reasoning = "Building habit — even a small commit counts"
    else:
        priority_task = "Review and refactor your top GitHub repo"
        reasoning = "Code quality compounds over time"

    # Format today's calendar events
    today_cal: list[dict] = []
    for ev in today_events[:10]:
        start_str = ev.get("start", "")
        end_str   = ev.get("end", "")
        try:
            if "T" in start_str:
                # Timed event
                start_dt = datetime.fromisoformat(start_str.replace("Z", "+00:00"))
                duration = ""
                if end_str and "T" in end_str:
                    end_dt = datetime.fromisoformat(end_str.replace("Z", "+00:00"))
                    mins   = int((end_dt - start_dt).total_seconds() / 60)
                    duration = f"{mins // 60}h {mins % 60}m" if mins >= 60 else f"{mins}m"
                today_cal.append({
                    "title":    ev.get("summary", "Event"),
                    "time":     start_dt.strftime("%I:%M %p"),
                    "duration": duration,
                })
            else:
                # All-day event (no T in start)
                today_cal.append({
                    "title":    ev.get("summary", "Event"),
                    "time":     "All day",
                    "duration": "",
                })
        except Exception:
            pass

    # Fetch recently-liked technical YouTube videos (YouTube API does not expose
    # "liked at" timestamps, so we show the top technical liked videos instead)
    youtube_today: list[dict] = []
    if g_token:
        try:
            yt_data = _fetch_youtube_liked(g_token)
            for video in yt_data.get("top_videos", [])[:5]:
                youtube_today.append({
                    "title":   video.get("title", ""),
                    "channel": video.get("channel", ""),
                    "duration": "—",
                })
        except Exception:
            pass

    return {
        "recommendation":  recommendation,
        "priority_task":   priority_task,
        "reasoning":       reasoning,
        "calendar_today":  today_cal,
        "youtube_watched": youtube_today,
    }


@app.get("/api/learn-vs-build")
async def lvb_compat(user_id: Optional[int] = Query(None), db: Session = Depends(get_db)):
    if not user_id:
        return {
            "analysis":            "Connect your accounts to see your real learn/build balance.",
            "learn_score":         50,
            "build_score":         50,
            "balance":             "balanced",
            "github_commits_week": 0,
            "youtube_hours_week":  0,
            "study_hours_week":    0,
            "trend":               [],
        }

    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        return {
            "analysis": "User not found.", "learn_score": 50, "build_score": 50,
            "balance": "balanced", "github_commits_week": 0,
            "youtube_hours_week": 0, "study_hours_week": 0, "trend": [],
        }

    linked = user.linked_accounts

    commits_week    = 0
    study_hours     = 0.0
    lc_streak       = 0
    lc_solved       = 0

    gh_events: list[dict] = []
    gh_username = _resolve_github_username(user_id, db)
    if gh_username:
        try:
            gh = _fetch_github_cached(gh_username)
            commits_week = gh.get("commits_week", 0)
            gh_events = gh.get("_events", [])
        except Exception:
            pass

    if linked and linked.leetcode_username:
        try:
            lc = _fetch_leetcode(linked.leetcode_username)
            lc_streak = lc.get("streak", 0)
            lc_solved = lc.get("total_solved", 0)
        except Exception:
            pass

    g_token = refresh_google_token_if_needed(user_id, db)
    if g_token:
        try:
            events = _fetch_calendar_events(g_token)
            study_kws = {"study", "learn", "practice", "leetcode", "dsa", "review", "read", "course", "tutorial", "revision"}
            for ev in events:
                if any(kw in ev.get("summary", "").lower() for kw in study_kws):
                    s, e = ev.get("start", ""), ev.get("end", "")
                    if s and e and "T" in s:
                        try:
                            sd = datetime.fromisoformat(s.replace("Z", "+00:00"))
                            ed = datetime.fromisoformat(e.replace("Z", "+00:00"))
                            study_hours += min((ed - sd).total_seconds() / 3600, 8)
                        except Exception:
                            pass
        except Exception:
            pass

    # Score calculation
    build_pts = commits_week * 10
    learn_pts = lc_streak * 5 + study_hours * 8
    total_pts = max(build_pts + learn_pts, 1)
    build_score = int(max(10, min(90, (build_pts / total_pts) * 100)))
    learn_score = 100 - build_score

    if build_score < 35:
        balance = "learning_heavy"
    elif build_score > 65:
        balance = "building_heavy"
    else:
        balance = "balanced"

    # Real 6-week trend — derived from GitHub push events
    today_dt = datetime.utcnow()
    weekly_commits: dict[int, int] = defaultdict(int)   # weeks_ago → commit count
    for e in gh_events:
        if not isinstance(e, dict) or e.get("type") != "PushEvent":
            continue
        try:
            created = datetime.strptime(e["created_at"][:10], "%Y-%m-%d")
            weeks_ago = (today_dt.date() - created.date()).days // 7
            if 0 <= weeks_ago < 6:
                weekly_commits[weeks_ago] += 1
        except (KeyError, ValueError):
            pass

    trend = []
    for weeks_ago in range(5, -1, -1):
        week_start = today_dt - timedelta(weeks=weeks_ago)
        label = f"{week_start.strftime('%b')} W{(week_start.day - 1) // 7 + 1}"
        wc = weekly_commits.get(weeks_ago, 0)
        w_build_pts = wc * 10
        w_learn_pts = lc_streak * 2 if weeks_ago == 0 else 0
        w_total = max(w_build_pts + w_learn_pts, 1)
        w_build = int(max(10, min(90, (w_build_pts / w_total) * 100))) if (w_build_pts + w_learn_pts) > 0 else build_score
        trend.append({"week": label, "learn": 100 - w_build, "build": w_build})

    question = (
        f"Analyze this developer's learning vs building balance:\n"
        f"- GitHub commits this week: {commits_week}\n"
        f"- LeetCode streak: {lc_streak} days, {lc_solved} total solved\n"
        f"- Study hours from calendar: {study_hours:.1f}h\n"
        f"- Learn score: {learn_score}%, Build score: {build_score}% → {balance}\n"
        f"- Goals: {user.goal_1 or 'Not set'} / {user.goal_2 or 'Not set'} / {user.goal_3 or 'Not set'}\n\n"
        f"Give a concise 3-4 sentence analysis. Be specific and actionable. End with ∎"
    )

    system_prompt = _SYSTEM_PROMPT_TEMPLATE.format(
        goal_1=user.goal_1 or "Not set",
        goal_2=user.goal_2 or "Not set",
        goal_3=user.goal_3 or "Not set",
        today=datetime.utcnow().strftime("%Y-%m-%d"),
    )

    analysis, gemini_ok = call_ai(system_prompt, question)

    # If Gemini failed, provide a fallback analysis
    if not gemini_ok:
        if balance == "learning_heavy":
            analysis = (
                f"You're **learning-focused** ({learn_score}% learn vs {build_score}% build). "
                f"Consider starting a small project to apply knowledge."
            )
        elif balance == "building_heavy":
            analysis = (
                f"You're **build-focused** ({build_score}% build vs {learn_score}% learn). "
                f"Remember to dedicate time for learning and skill expansion."
            )
        else:
            analysis = (
                f"You have a **balanced** learning and building schedule ({learn_score}% learn, {build_score}% build). "
                f"Keep maintaining this healthy mix."
            )

    return {
        "analysis":            analysis,
        "learn_score":         learn_score,
        "build_score":         build_score,
        "balance":             balance,
        "github_commits_week": commits_week,
        "youtube_hours_week":  0.0,
        "study_hours_week":    round(study_hours, 1),
        "trend":               trend,
    }


# ── Entry point ────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import uvicorn
    port = int(os.getenv("PORT", 8000))
    uvicorn.run("main:app", host="0.0.0.0", port=port, reload=True)
