#!/usr/bin/env python3
"""
launch.py — starts the ODIN stack: bridge.py (8099), proxy.py (3099), server.py/mcp (8080)
Each service is assumed to already know its own port (hardcoded or read from its own config).
This script just launches all three, waits, and tears them all down together on exit.
"""

import subprocess
import sys
import signal
import time
import os

# Adjust these paths if the scripts live in subfolders, e.g. "mcp/server.py"
SERVICES = [
    {"name": "bridge",       "cmd": [sys.executable, "-m", "uvicorn", "bridge:app", "--host", "0.0.0.0", "--port", "8099"], "port": 8099},
    {"name": "proxy",        "cmd": [sys.executable, "-m", "uvicorn", "proxy:app",  "--host", "0.0.0.0", "--port", "3099"], "port": 3099},
    {"name": "mcp-server",   "cmd": [sys.executable, "server.py", "http", "--port", "8080"], "port": 8080},
    {"name": "mcp-service",  "cmd": [sys.executable, "service.py"], "port": 8082},
    {"name": "mcp-client",   "cmd": [sys.executable, "client.py"],  "port": 8081},
    {"name": "mcp-post",     "cmd": [sys.executable, "mcp_post.py"], "port": 8083},
]

processes = []

def start_all():
    for svc in SERVICES:
        print(f"[launch.py] Starting {svc['name']} on port {svc['port']} -> {' '.join(svc['cmd'])}")
        try:
            p = subprocess.Popen(svc["cmd"], cwd=os.path.dirname(os.path.abspath(__file__)))
            processes.append((svc["name"], p))
        except FileNotFoundError as e:
            print(f"[launch.py] ERROR: couldn't start {svc['name']}: {e}")
            print(f"[launch.py] Check the path/filename for {svc['cmd'][1]}")
        time.sleep(1)  # stagger startup slightly

def shutdown(signum=None, frame=None):
    print("\n[launch.py] Shutting down all services...")
    for name, p in processes:
        if p.poll() is None:  # still running
            print(f"[launch.py] Stopping {name} (pid {p.pid})")
            p.terminate()
    # give them a moment, then force-kill anything still alive
    time.sleep(2)
    for name, p in processes:
        if p.poll() is None:
            print(f"[launch.py] Force-killing {name} (pid {p.pid})")
            p.kill()
    sys.exit(0)

def main():
    signal.signal(signal.SIGINT, shutdown)
    signal.signal(signal.SIGTERM, shutdown)

    start_all()

    print("[launch.py] All services launched. Press Ctrl+C to stop everything.")

    # Wait on all processes; if any dies unexpectedly, report it but keep others running
    try:
        while True:
            for name, p in processes:
                ret = p.poll()
                if ret is not None:
                    print(f"[launch.py] WARNING: {name} exited unexpectedly (code {ret})")
            time.sleep(3)
    except KeyboardInterrupt:
        shutdown()

if __name__ == "__main__":
    main()
