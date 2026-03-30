#!/bin/bash
cd "$(dirname "$0")"
PIDFILE=".kitchen-pids"

echo "=== Kitchen App Stopping ==="

if [ -f "$PIDFILE" ]; then
  read -r PIDS < "$PIDFILE"
  for pid in $PIDS; do
    kill "$pid" 2>/dev/null && echo "  Stopped PID $pid"
  done
  rm -f "$PIDFILE"
fi

# Kill by port as fallback
for port in 8091 8050; do
  kill $(lsof -ti:$port) 2>/dev/null && echo "  Stopped process on port $port"
done

echo "  Stopping Docker services..."
docker compose down 2>&1 | tail -2

echo "=== Stopped ==="
