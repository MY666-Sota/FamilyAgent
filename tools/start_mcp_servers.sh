#!/usr/bin/env bash
###############################################################################
# FamilyAgent MCP 工具层 — 一键启动脚本
#
# 拉起全部 4 个常驻服务，供窗口1 做真实 MCP 联调：
#   file-server     8090  HTTP   文件下载（其他工具 file_url 的前提）
#   office-word-mcp 9001  SSE    /sse
#   presenton-mcp   9002  SSE    /sse
#   paddleocr-mcp   9003  SSE    /sse
#
# 用法：
#   bash tools/start_mcp_servers.sh           # 启动全部（已在跑的会跳过）
#   bash tools/start_mcp_servers.sh stop      # 停止全部
#   bash tools/start_mcp_servers.sh status    # 查看端口监听状态
#   bash tools/start_mcp_servers.sh restart   # 重启全部
#
# 说明：
#   - 开发/联调用。生产部署见 infra/docker-compose.yml。
#   - 日志写到 .runlogs/（已 gitignore），不落 C 盘。
#   - 本地服务调用一律绕开系统代理（NO_PROXY），避免 localhost 被代理拦截。
###############################################################################
set -uo pipefail

# 脚本在 tools/ 下，工作根目录是其上一级
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
LOGS="$ROOT/.runlogs"
PIDS_FILE="$LOGS/mcp_pids"
mkdir -p "$LOGS"

# 本地服务间调用不走系统代理（与 server / 测试脚本保持一致）
export NO_PROXY="localhost,127.0.0.1"
export no_proxy="localhost,127.0.0.1"
# 防止子进程 Python 控制台编码问题（Windows GBK）
export PYTHONIOENCODING="utf-8"

PYTHON="${PYTHON:-python}"

# 服务清单："名称|端口|脚本相对路径"
SERVICES=(
    "file-server|8090|tools/file-server/server.py"
    "office-word-mcp|9001|mcp-servers/office-word-mcp/server.py"
    "presenton-mcp|9002|mcp-servers/presenton-mcp/server.py"
    "paddleocr-mcp|9003|mcp-servers/paddleocr-mcp/server.py"
)

# 检查端口是否在监听（Windows netstat）
port_listening() {
    netstat -ano 2>/dev/null | grep -E ":$1[[:space:]]" | grep -q LISTENING
}

# 取占用某端口的 PID（Windows netstat 最后一列）
pid_on_port() {
    netstat -ano 2>/dev/null | grep -E ":$1[[:space:]]" | grep LISTENING | awk '{print $NF}' | head -1
}

start_all() {
    echo "=== 启动 MCP 工具层（NO_PROXY=$NO_PROXY） ==="
    : > "$PIDS_FILE"
    for svc in "${SERVICES[@]}"; do
        IFS='|' read -r name port script <<< "$svc"
        if port_listening "$port"; then
            echo "  [跳过] $name 已在 :$port 运行（PID $(pid_on_port "$port")）"
            continue
        fi
        local log="$LOGS/${name}.log"
        "$PYTHON" "$ROOT/$script" > "$log" 2>&1 &
        local pid=$!
        echo "${name}|${port}|${pid}" >> "$PIDS_FILE"
        echo "  [启动] $name → :$port  (PID $pid, 日志 $log)"
        # file-server 是其他服务的前提，先稍等
        [ "$name" = "file-server" ] && sleep 1
    done

    echo ""
    echo "等待服务就绪..."
    local ok=0 total=${#SERVICES[@]}
    for i in $(seq 1 15); do
        ok=0
        for svc in "${SERVICES[@]}"; do
            IFS='|' read -r name port script <<< "$svc"
            port_listening "$port" && ok=$((ok+1))
        done
        [ "$ok" -eq "$total" ] && break
        sleep 1
    done

    echo ""
    status
    if [ "$ok" -eq "$total" ]; then
        echo ""
        echo "✅ 全部 $total 个服务就绪。停止：bash tools/start_mcp_servers.sh stop"
    else
        echo ""
        echo "⚠️  仅 $ok/$total 个就绪，检查日志：$LOGS/"
        return 1
    fi
}

stop_all() {
    echo "=== 停止 MCP 工具层 ==="
    # 优先按端口停（最可靠），兼顾 PID 文件
    for svc in "${SERVICES[@]}"; do
        IFS='|' read -r name port script <<< "$svc"
        local pid
        pid=$(pid_on_port "$port")
        if [ -n "${pid:-}" ]; then
            taskkill //PID "$pid" //F >/dev/null 2>&1 \
                && echo "  [停止] $name :$port (PID $pid)" \
                || echo "  [失败] $name :$port (PID $pid)"
        else
            echo "  [跳过] $name :$port 未运行"
        fi
    done
    rm -f "$PIDS_FILE"
}

status() {
    echo "=== 端口监听状态 ==="
    for svc in "${SERVICES[@]}"; do
        IFS='|' read -r name port script <<< "$svc"
        if port_listening "$port"; then
            printf "  ✅ %-16s :%s  PID %s\n" "$name" "$port" "$(pid_on_port "$port")"
        else
            printf "  ❌ %-16s :%s  未运行\n" "$name" "$port"
        fi
    done
}

case "${1:-start}" in
    start)   start_all ;;
    stop)    stop_all ;;
    status)  status ;;
    restart) stop_all; sleep 2; start_all ;;
    *)
        echo "用法: bash tools/start_mcp_servers.sh [start|stop|status|restart]"
        exit 1
        ;;
esac
