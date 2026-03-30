#!/bin/bash
set -e
cd "$(dirname "$0")"
PIDFILE=".kitchen-pids"

echo "=== Kitchen App Starting ==="

# 1. Docker services
echo "[1/4] Starting Grocy + MCP API..."
docker compose up -d 2>&1 | tail -2

echo "[2/4] Waiting for Grocy..."
for i in $(seq 1 30); do
  if curl -s -o /dev/null -w '' http://localhost:9283 2>/dev/null; then
    echo "  Grocy ready."
    break
  fi
  sleep 1
done

# 3. Hachimenroppi dashboard
echo "[3/4] Starting Hachimenroppi dashboard..."
kill $(lsof -ti:8050) 2>/dev/null || true
sleep 0.5
(cd /Users/ytonoyam/Dev/hachimenroppi && python3 app.py > /dev/null 2>&1) &
HACHI_PID=$!

# 4. Voice server (unified app)
echo "[4/4] Starting Kitchen App server..."
kill $(lsof -ti:8091) 2>/dev/null || true
sleep 0.5
python3 voice-server.py > /dev/null 2>&1 &
VOICE_PID=$!

# Save PIDs
echo "$VOICE_PID $HACHI_PID" > "$PIDFILE"
sleep 2

echo ""
echo "=== All services running ==="
echo "  Kitchen App:   http://localhost:8091"
echo "  Grocy:         http://localhost:9283"
echo "  Hachimenroppi: http://localhost:8050"
echo ""

open http://localhost:8091
