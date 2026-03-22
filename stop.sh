#!/bin/bash
# DruidClaw stop script
# Stops the web server and daemon processes

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
RUN_DIR="${DRUIDCLAW_RUN_DIR:-$HOME/.druidclaw/run}"

echo "========================================"
echo "  DruidClaw - Stop Script"
echo "========================================"
echo

# Stop web server
echo ">>> Stopping DruidClaw web server..."
WEB_PID=$(lsof -t -i:19123 2>/dev/null || true)
if [ -n "$WEB_PID" ]; then
    kill $WEB_PID 2>/dev/null || true
    echo "    Web server (PID: $WEB_PID) stopped."
else
    echo "    No web server running on port 19123."
fi

# Stop daemon
echo ">>> Stopping DruidClaw daemon..."
if [ -f "$RUN_DIR/daemon.pid" ]; then
    DAEMON_PID=$(cat "$RUN_DIR/daemon.pid" 2>/dev/null || true)
    if [ -n "$DAEMON_PID" ] && kill -0 $DAEMON_PID 2>/dev/null; then
        kill $DAEMON_PID 2>/dev/null || true
        sleep 1
        if kill -0 $DAEMON_PID 2>/dev/null; then
            kill -9 $DAEMON_PID 2>/dev/null || true
        fi
        echo "    Daemon (PID: $DAEMON_PID) stopped."
    else
        echo "    Daemon process not running."
    fi
    rm -f "$RUN_DIR/daemon.pid"
else
    echo "    No daemon PID file found."
fi

# Clean up socket
if [ -f "$RUN_DIR/daemon.sock" ]; then
    rm -f "$RUN_DIR/daemon.sock"
    echo "    Socket file cleaned up."
fi

# Check for any remaining DruidClaw processes
echo ">>> Checking for remaining DruidClaw processes..."
REMAINING=$(pgrep -f "druidclaw" 2>/dev/null || true)
if [ -n "$REMAINING" ]; then
    echo "    Found remaining processes: $REMAINING"
    echo "    Stopping them..."
    echo "$REMAINING" | xargs kill 2>/dev/null || true
fi

echo
echo "========================================"
echo "  DruidClaw stopped successfully!"
echo "========================================"
