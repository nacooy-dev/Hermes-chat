#!/bin/bash
# Hermes WebChat - Stop all services
PID_DIR="/tmp/hermes-webchat-pids"

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

echo -e "${YELLOW}🛑 停止 Hermes WebChat${NC}"

killed=0

# Bridge
if [ -f "$PID_DIR/bridge.pid" ]; then
    pid=$(cat "$PID_DIR/bridge.pid")
    if kill "$pid" 2>/dev/null; then
        echo -e "  ${GREEN}✕ Bridge (PID $pid)${NC}"
        killed=1
    fi
    rm -f "$PID_DIR/bridge.pid"
fi
# Fallback: kill by port
if lsof -ti :6789 > /dev/null 2>&1; then
    pid=$(lsof -ti :6789)
    kill "$pid" 2>/dev/null
    echo -e "  ${GREEN}✕ Bridge (PID $pid, port 6789)${NC}"
    killed=1
fi

# Web Server
if [ -f "$PID_DIR/web.pid" ]; then
    pid=$(cat "$PID_DIR/web.pid")
    if kill "$pid" 2>/dev/null; then
        echo -e "  ${GREEN}✕ Web Server (PID $pid)${NC}"
        killed=1
    fi
    rm -f "$PID_DIR/web.pid"
fi
if lsof -ti :18356 > /dev/null 2>&1; then
    pid=$(lsof -ti :18356)
    kill "$pid" 2>/dev/null
    echo -e "  ${GREEN}✕ Web Server (PID $pid, port 18356)${NC}"
    killed=1
fi

# NATS Server
nats_pid=$(pgrep -f "nats-server.*nats.conf" 2>/dev/null)
if [ -n "$nats_pid" ]; then
    kill "$nats_pid" 2>/dev/null
    echo -e "  ${GREEN}✕ NATS Server (PID $nats_pid)${NC}"
    killed=1
fi
if [ -f "$PID_DIR/nats.pid" ]; then
    rm -f "$PID_DIR/nats.pid"
fi

rmdir "$PID_DIR" 2>/dev/null

if [ "$killed" -eq 0 ]; then
    echo -e "  ${YELLOW}没有运行中的服务${NC}"
fi

echo -e "${GREEN}✓ 已停止${NC}"
