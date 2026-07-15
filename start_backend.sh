#!/usr/bin/env bash
# start_backend.sh — launch the Backend/Engine stack
cd /home/kwatk/Backend
if [ -f "env/bin/activate" ]; then
    source env/bin/activate
elif [ -f "venv/bin/activate" ]; then
    source venv/bin/activate
fi

# Kill stale backend processes
pkill -f "uvicorn.*Backend/main:app" 2>/dev/null || true
sleep 1

echo "[BACKEND] Starting engine/router/parser on 8000..."
python -m uvicorn main:app --host 0.0.0.0 --port 8000 &
BACKEND_PID=$!
sleep 2

echo "[BACKEND] Engine live on port 8000. PID=$BACKEND_PID"
trap "kill $BACKEND_PID 2>/dev/null || true" EXIT
wait
