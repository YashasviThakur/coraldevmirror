"""
refresh_coral_tokens.py

Exchanges Google refresh tokens for fresh access tokens,
then writes them to environment so start.sh can register Coral sources.

Run once at container startup before coral source add commands.
"""

import os
import sys
import json
import urllib.request
import urllib.parse


def refresh_google_token(refresh_token: str, client_id: str, client_secret: str) -> str:
    """Exchange a Google refresh token for a fresh access token."""
    data = urllib.parse.urlencode({
        "grant_type":    "refresh_token",
        "refresh_token": refresh_token,
        "client_id":     client_id,
        "client_secret": client_secret,
    }).encode()

    req = urllib.request.Request(
        "https://oauth2.googleapis.com/token",
        data=data,
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=15) as resp:
        result = json.loads(resp.read())

    access_token = result.get("access_token")
    if not access_token:
        raise RuntimeError(f"Token refresh failed: {result}")
    return access_token


def main():
    client_id     = os.environ.get("GOOGLE_CLIENT_ID", "")
    client_secret = os.environ.get("GOOGLE_CLIENT_SECRET", "")

    if not client_id or not client_secret:
        print("[refresh] GOOGLE_CLIENT_ID or GOOGLE_CLIENT_SECRET not set — skipping token refresh")
        return

    # YouTube token
    yt_refresh = os.environ.get("YOUTUBE_REFRESH_TOKEN", "")
    if yt_refresh:
        try:
            token = refresh_google_token(yt_refresh, client_id, client_secret)
            # Write to a file that start.sh will source
            with open("/tmp/coral_env.sh", "a") as f:
                f.write(f'export YOUTUBE_ACCESS_TOKEN="{token}"\n')
            print("[refresh] YouTube access token refreshed")
        except Exception as e:
            print(f"[refresh] YouTube token refresh failed: {e}", file=sys.stderr)

    # Gmail token
    gmail_refresh = os.environ.get("GMAIL_REFRESH_TOKEN", "")
    if gmail_refresh:
        try:
            token = refresh_google_token(gmail_refresh, client_id, client_secret)
            with open("/tmp/coral_env.sh", "a") as f:
                f.write(f'export GMAIL_ACCESS_TOKEN="{token}"\n')
            print("[refresh] Gmail access token refreshed")
        except Exception as e:
            print(f"[refresh] Gmail token refresh failed: {e}", file=sys.stderr)

    # Google Calendar token (same refresh token as Gmail if using same OAuth scope)
    cal_refresh = os.environ.get("GOOGLE_CALENDAR_REFRESH_TOKEN", "") or gmail_refresh
    if cal_refresh:
        try:
            token = refresh_google_token(cal_refresh, client_id, client_secret)
            with open("/tmp/coral_env.sh", "a") as f:
                f.write(f'export GOOGLE_CALENDAR_ACCESS_TOKEN="{token}"\n')
            print("[refresh] Google Calendar access token refreshed")
        except Exception as e:
            print(f"[refresh] Calendar token refresh failed: {e}", file=sys.stderr)


if __name__ == "__main__":
    main()
