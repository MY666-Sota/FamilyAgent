#!/usr/bin/env bash
# 启动所有 MCP server 和 file-server（开发用，生产走 docker-compose）
# 用法：bash start_all.sh
#   停止：bash start_all.sh stop

set -e
ROOT="$(cd "$(dirname "$0")" && pwd)"
LOGS="$ROOT/.logs"
mkdir -p "$LOGS"

PIDS_FILE="$LOGS/pids"

stop_all() {
    if [ -f "$PIDS_FILE" ]; then
        while IFS= read -r pid; do
            kill "$pid" 2>/dev/null && echo "Stopped $pid" || true
        done < "$PIDS_FILE"
        rm -f "$PIDS_FILE"
    fi
    echo "All services stopped."
}

if [ "${1:-}" = "stop" ]; then
    stop_all
    exit 0
fi

> "$PIDS_FILE"

start_service() {
    local name="$1"
    local cmd="$2"
    local log="$LOGS/${name}.log"
    echo "Starting $name..."
    eval "$cmd" > "$log" 2>&1 &
    local pid=$!
    echo "$pid" >> "$PIDS_FILE"
    echo "  PID $pid  →  $log"
}

# file-server (8090) — 其他工具文件 URL 的前提
start_service "file-server" \
    "python \"$ROOT/tools/file-server/server.py\""

sleep 1

# MCP SSE servers
start_service "office-word-mcp" \
    "python \"$ROOT/mcp-servers/office-word-mcp/server.py\""

start_service "presenton-mcp" \
    "python \"$ROOT/mcp-servers/presenton-mcp/server.py\""

start_service "paddleocr-mcp" \
    "python \"$ROOT/mcp-servers/paddleocr-mcp/server.py\""

echo ""
echo "All services started. Logs → $LOGS/"
echo "Run 'bash start_all.sh stop' to stop."
echo ""
echo "Waiting 3s for servers to be ready..."
sleep 3

echo "Running quick self-test..."
python "$ROOT/tools/test/test_mcp.py" --quick
