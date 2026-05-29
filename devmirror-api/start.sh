#!/bin/bash
export PATH="/root/.coral/bin:/usr/local/bin:$PATH"

echo "[DevMirror] PORT is: $PORT"
echo "[DevMirror] coral path: $(which coral 2>/dev/null || echo 'NOT FOUND')"

# Refresh tokens
python /app/refresh_coral_tokens.py
if [ -f /tmp/coral_env.sh ]; then
  source /tmp/coral_env.sh
fi

# Register Coral sources in background
(
  [ -n "$YOUTUBE_ACCESS_TOKEN" ] && coral source add --file /app/coral_sources/youtube.yaml && echo "[DevMirror] YouTube registered"
  [ -n "$GMAIL_ACCESS_TOKEN" ] && coral source add --file /app/coral_sources/gmail.yaml && echo "[DevMirror] Gmail registered"
  [ -n "$CODEFORCES_HANDLE" ] && coral source add --file /app/coral_sources/codeforces.yaml && echo "[DevMirror] Codeforces registered"
  [ -n "$GOOGLE_CALENDAR_ACCESS_TOKEN" ] && coral source add --file /app/coral_sources/google_calendar.yaml && echo "[DevMirror] Calendar registered"
) &

PORT="${PORT:-8000}"
echo "[DevMirror] Starting uvicorn on port $PORT"
exec uvicorn main:app --host 0.0.0.0 --port "$PORT"
