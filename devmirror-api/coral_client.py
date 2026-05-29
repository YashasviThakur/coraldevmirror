"""
coral_client.py — Thin wrapper around the Coral CLI for DevMirror.

Coral (https://withcoral.com) exposes multiple APIs as a unified SQL interface.
DevMirror uses it to query GitHub, Gmail, and YouTube via SQL.

Per-user tokens (GitHub PAT, Gmail OAuth, YouTube OAuth) are passed as env vars
at subprocess call time — so every user gets their own data, not a shared config.

If Coral is not installed or not configured, every function returns None and
main.py falls back to its existing direct API calls — the website keeps working.
"""

import json
import shutil
import subprocess
import os
from typing import Any, Optional

# ── Coral availability check ───────────────────────────────────────────────────

def coral_available() -> bool:
    """Return True if the coral CLI is installed and on PATH."""
    return shutil.which("coral") is not None


def _run_sql(query: str, env: Optional[dict] = None) -> Optional[list[dict]]:
    """
    Execute a SQL query via `coral sql --json` and return rows as a list of dicts.
    Returns None if Coral is unavailable or the query fails.
    """
    if not coral_available():
        return None
    try:
        merged_env = {**os.environ, **(env or {})}
        result = subprocess.run(
            ["coral", "sql", "--format", "json", query],
            capture_output=True,
            text=True,
            timeout=20,
            env=merged_env,
        )
        if result.returncode != 0:
            print(f"[coral] query failed: {result.stderr.strip()[:200]}")
            return None
        return json.loads(result.stdout)
    except (subprocess.TimeoutExpired, json.JSONDecodeError, Exception) as e:
        print(f"[coral] exception: {e}")
        return None


# ── Codeforces ─────────────────────────────────────────────────────────────────

def get_codeforces_user(handle: str) -> Optional[dict[str, Any]]:
    """
    Query Codeforces user profile via Coral SQL.
    Falls back to None if Coral is unavailable.
    """
    rows = _run_sql(
        "SELECT handle, rating, rank, max_rating, max_rank, contribution, avatar "
        "FROM codeforces.user_info LIMIT 1",
        env={"CODEFORCES_HANDLE": handle},
    )
    if not rows:
        return None
    return rows[0]


def get_codeforces_submissions(handle: str, limit: int = 500) -> Optional[list[dict]]:
    """Recent Codeforces submissions via Coral SQL (all verdicts, ordered newest first)."""
    return _run_sql(
        f"SELECT id, contest_id, problem_name, problem_index, problem_rating, verdict, submitted_at "
        f"FROM codeforces.submissions "
        f"ORDER BY submitted_at DESC LIMIT {limit}",
        env={"CODEFORCES_HANDLE": handle},
    )


def get_codeforces_rating_history(handle: str) -> Optional[list[dict]]:
    """Contest rating history via Coral SQL."""
    return _run_sql(
        "SELECT contest_name, rank, old_rating, new_rating "
        "FROM codeforces.rating_history "
        "ORDER BY contest_id DESC LIMIT 10",
        env={"CODEFORCES_HANDLE": handle},
    )


# ── Gmail ──────────────────────────────────────────────────────────────────────

def get_gmail_opportunities(access_token: str) -> Optional[list[dict]]:
    """
    Query Gmail for internship/hackathon/scholarship threads via Coral SQL.
    Passes the OAuth token via environment variable so it stays out of the query string.
    """
    env = {"GMAIL_ACCESS_TOKEN": access_token}
    return _run_sql(
        "SELECT id, snippet FROM gmail.threads "
        "WHERE q = 'subject:(internship OR hackathon OR scholarship) is:unread' "
        "LIMIT 20",
        env=env,
    )


def get_gmail_profile(access_token: str) -> Optional[dict[str, Any]]:
    """Gmail profile (email address + mailbox stats) via Coral SQL."""
    env = {"GMAIL_ACCESS_TOKEN": access_token}
    rows = _run_sql("SELECT emailAddress, messagesTotal, threadsTotal FROM gmail.profile LIMIT 1", env=env)
    return rows[0] if rows else None


# ── YouTube ────────────────────────────────────────────────────────────────────

def get_youtube_liked_videos(access_token: str, limit: int = 50) -> Optional[list[dict]]:
    """
    Query the user's most recently liked YouTube videos via Coral SQL.
    Returns videos ordered by position (0 = most recently liked).
    """
    env = {"YOUTUBE_ACCESS_TOKEN": access_token}
    return _run_sql(
        f"SELECT video_id, title, channel_title, liked_at, thumbnail_url "
        f"FROM youtube.liked_videos "
        f"ORDER BY position ASC LIMIT {limit}",
        env=env,
    )


def get_youtube_channel_stats(access_token: str) -> Optional[dict[str, Any]]:
    """User's YouTube channel stats via Coral SQL."""
    env = {"YOUTUBE_ACCESS_TOKEN": access_token}
    rows = _run_sql(
        "SELECT title, subscriber_count, video_count, view_count "
        "FROM youtube.channels LIMIT 1",
        env=env,
    )
    return rows[0] if rows else None


# ── GitHub ─────────────────────────────────────────────────────────────────────
# Uses Coral's built-in GitHub source (sources/core/github).
# GITHUB_TOKEN is passed per-request via env var — each user's PAT is used,
# so every user sees their own repos and activity, not a shared config.

def get_github_user(github_token: str) -> Optional[dict[str, Any]]:
    """Authenticated GitHub user profile via Coral SQL."""
    env = {"GITHUB_TOKEN": github_token}
    rows = _run_sql(
        "SELECT login, name, public_repos, followers, avatar_url "
        "FROM github.user LIMIT 1",
        env=env,
    )
    return rows[0] if rows else None


def get_github_repos(github_token: str, username: str, limit: int = 10) -> Optional[list[dict]]:
    """User's top repos ordered by last updated via Coral SQL."""
    env = {"GITHUB_TOKEN": github_token}
    return _run_sql(
        f"SELECT name, language, stargazers_count, forks_count, updated_at "
        f"FROM github.user_repos "
        f"WHERE username = '{username}' "
        f"ORDER BY updated_at DESC LIMIT {limit}",
        env=env,
    )


def get_github_events(github_token: str, username: str, limit: int = 100) -> Optional[list[dict]]:
    """Recent GitHub push events for commit counting via Coral SQL."""
    env = {"GITHUB_TOKEN": github_token}
    return _run_sql(
        f"SELECT type, created_at, repo_name "
        f"FROM github.received_events "
        f"WHERE actor_login = '{username}' AND type = 'PushEvent' "
        f"ORDER BY created_at DESC LIMIT {limit}",
        env=env,
    )


def get_github_languages(github_token: str, owner: str, repo: str) -> Optional[list[dict]]:
    """Language breakdown for a repo via Coral SQL."""
    env = {"GITHUB_TOKEN": github_token}
    return _run_sql(
        f"SELECT name, bytes FROM github.languages "
        f"WHERE owner = '{owner}' AND repo = '{repo}' "
        f"LIMIT 10",
        env=env,
    )
