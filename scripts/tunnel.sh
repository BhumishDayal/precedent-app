#!/usr/bin/env bash
# Public HTTPS URL for the local server (Dial webhooks, Context MCP, Slack interactivity, /v1 for other sites).
#   scripts/tunnel.sh            tunnel to :8000
#   PORT=8001 scripts/tunnel.sh  another port
# Prints the https URL and writes it to $STATE_DIR/public_url.txt (STATE_DIR = $PRECEDENT_STATE_DIR or data/),
# which the app reads when PUBLIC_URL isn't set. Does not edit .env. Ctrl-C stops the tunnel.
# Needs cloudflared on PATH or in ~/.local/bin.
set -euo pipefail
cd "$(dirname "$0")/.."
PORT="${PORT:-8000}"
STATE_DIR="${PRECEDENT_STATE_DIR:-data}"
CF="$(command -v cloudflared || echo "$HOME/.local/bin/cloudflared")"
[ -x "$CF" ] || { echo "cloudflared not found (expected $HOME/.local/bin/cloudflared)"; exit 1; }

LOG="$(mktemp -t precedent-tunnel)"
"$CF" tunnel --no-autoupdate --url "http://localhost:$PORT" >"$LOG" 2>&1 &
CF_PID=$!
trap 'kill $CF_PID 2>/dev/null; rm -f "$STATE_DIR/public_url.txt"' EXIT

URL=""
for _ in $(seq 60); do
  URL=$(grep -oE 'https://[a-z0-9-]+\.trycloudflare\.com' "$LOG" | head -1 || true)
  [ -n "$URL" ] && break
  kill -0 $CF_PID 2>/dev/null || { cat "$LOG"; exit 1; }
  sleep 0.5
done
[ -n "$URL" ] || { echo "no tunnel URL after 30 s"; cat "$LOG"; exit 1; }

echo "$URL" > "$STATE_DIR/public_url.txt"
echo "PUBLIC URL: $URL   (-> localhost:$PORT, saved to $STATE_DIR/public_url.txt)"
echo "  Slack interactivity:  $URL/slack/actions"
echo "  Dial webhook:         .venv/bin/python -m precedent.dial webhook $URL/webhooks/dial"
echo "  Dial context MCP:     .venv/bin/python -m precedent.dial register-context-mcp $URL"
echo "  Public MCP:           claude mcp add --transport http precedent $URL/mcp-public/"
wait $CF_PID
