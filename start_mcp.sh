#!/usr/bin/env bash
# start_mcp.sh — launch MCP stack: bridge, proxy, server, service, client, post
cd /home/kwatk/mcp

# Use the local env if it exists, otherwise system python
if [ -f "env/bin/activate" ]; then
    source env/bin/activate
elif [ -f "venv/bin/activate" ]; then
    source venv/bin/activate
fi

# Kill stale MCP processes
pkill -f "bridge:app" 2>/dev/null || true
pkill -f "proxy:app" 2>/dev/null || true
pkill -f "server.py http --port 8080" 2>/dev/null || true
pkill -f "service.py" 2>/dev/null || true
pkill -f "client.py" 2>/dev/null || true
pkill -f "mcp_post.py" 2>/dev/null || true
sleep 1

echo "[MCP] Starting bridge on 8099..."
python -m uvicorn bridge:app --host 0.0.0.0 --port 8099 &
BRIDGE_PID=$!
sleep 1

echo "[MCP] Starting proxy on 3099..."
python -m uvicorn proxy:app --host 0.0.0.0 --port 3099 &
PROXY_PID=$!
sleep 1

echo "[MCP] Starting MCP server on 8080..."
python server.py http --port 8080 --base-url http://127.0.0.1:8080 &
MCP_PID=$!
sleep 2

echo "[MCP] Starting MCP service on 8082..."
python service.py &
SERVICE_PID=$!
sleep 1

echo "[MCP] Starting MCP client on 8081..."
python client.py &
CLIENT_PID=$!
sleep 1

echo "[MCP] Starting MCP post on 8083..."
python mcp_post.py &
POST_PID=$!
sleep 1

echo "[MCP] All MCP services started. PIDs: bridge=$BRIDGE_PID proxy=$PROXY_PID server=$MCP_PID service=$SERVICE_PID client=$CLIENT_PID post=$POST_PID"
trap "kill $BRIDGE_PID $PROXY_PID $MCP_PID $SERVICE_PID $CLIENT_PID $POST_PID 2>/dev/null || true" EXIT
wait
