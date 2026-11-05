#!/usr/bin/env bash
# Start the Precedent server and print its URLs.
#   scripts/demo.sh            no tunnel: Dial replies arrive by long-poll
#   scripts/demo.sh --tunnel   also start cloudflared (for Dial webhooks) and print the public URL
# Ctrl-C stops everything. PORT=8002 scripts/demo.sh to run on another port.
set -euo pipefail
cd "$(dirname "$0")/.."
PORT="${PORT:-8000}"
TUNNEL_FLAG=""; [ "${1:-}" = "--tunnel" ] && TUNNEL_FLAG=1

.venv/bin/uvicorn precedent.server:app --host 0.0.0.0 --port "$PORT" &
UVICORN=$!
trap 'kill $UVICORN ${TUNNEL:-} 2>/dev/null' EXIT

for _ in $(seq 40); do curl -s -o /dev/null "http://localhost:$PORT/api/alerts" && break; sleep 0.5; done

if [ -n "$TUNNEL_FLAG" ]; then
  if command -v cloudflared >/dev/null; then
    LOG="$(mktemp -t precedent-tunnel)"
    cloudflared tunnel --url "http://localhost:$PORT" >"$LOG" 2>&1 &
    TUNNEL=$!
    for _ in $(seq 30); do
      URL=$(grep -oE 'https://[a-z0-9-]+\.trycloudflare\.com' "$LOG" | head -1 || true)
      [ -n "$URL" ] && break; sleep 1
    done
  else
    echo "!! cloudflared not found: brew install cloudflared"
  fi
fi

echo
echo "  Console:      http://localhost:$PORT/app"
echo "  Status board: http://localhost:$PORT/stage"
if [ -n "${URL:-}" ]; then
  echo "  Public URL:   $URL"
  echo "  Dial webhook: $URL/webhooks/dial   (set PUBLIC_URL=$URL in .env if needed)"
fi
echo
wait $UVICORN
