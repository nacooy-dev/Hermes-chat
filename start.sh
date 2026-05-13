#!/bin/bash
# Hermes WebChat - Start all services in background
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$SCRIPT_DIR" || exit 1

GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

PID_DIR="/tmp/hermes-webchat-pids"
mkdir -p "$PID_DIR"

echo -e "${GREEN}🚀 启动 Hermes WebChat${NC}"
echo ""

# 1. NATS Server
if pgrep -f "nats-server.*nats.conf" > /dev/null; then
    echo -e "${YELLOW}⚠ NATS Server 已在运行${NC}"
else
    nats-server -c "$SCRIPT_DIR/nats/nats.conf" > /tmp/hermes-webchat-nats.log 2>&1 &
    NATS_PID=$!
    echo "$NATS_PID" > "$PID_DIR/nats.pid"
    sleep 1
    echo -e "${GREEN}✓ NATS Server (:4222, WS :8765)${NC}"
fi

# 2. Web Server (for index.html)
WEB_PORT=18356
if lsof -i :$WEB_PORT > /dev/null 2>&1; then
    echo -e "${YELLOW}⚠ Web Server 已在运行 (:${WEB_PORT})${NC}"
else
    cd "$SCRIPT_DIR/web"
    /opt/homebrew/bin/python3.11 -m http.server $WEB_PORT > /tmp/hermes-webchat-web.log 2>&1 &
    WEB_PID=$!
    echo "$WEB_PID" > "$PID_DIR/web.pid"
    cd "$SCRIPT_DIR"
    sleep 1
    echo -e "${GREEN}✓ Web Server (:${WEB_PORT})${NC}"
fi

# 3. Bridge (WS server + NATS subscriber)
if lsof -i :6789 > /dev/null 2>&1; then
    echo -e "${YELLOW}⚠ Bridge 已在运行 (:6789)${NC}"
else
    nohup /opt/homebrew/bin/python3.11 bridge.py > /tmp/hermes-webchat-bridge.log 2>&1 &
    BRIDGE_PID=$!
    echo "$BRIDGE_PID" > "$PID_DIR/bridge.pid"
    sleep 2
    echo -e "${GREEN}✓ Bridge (ws://127.0.0.1:6789)${NC}"
fi

echo ""
echo -e "${GREEN}========================================${NC}"
echo -e "  Web UI: ${GREEN}http://localhost:${WEB_PORT}${NC}"
echo -e "  WS:     ${GREEN}ws://127.0.0.1:6789${NC}"
echo -e "  NATS:   ${GREEN}127.0.0.1:4222${NC}"
echo -e "${GREEN}========================================${NC}"
echo ""
echo -e "  ${YELLOW}停止服务: bash stop.sh${NC}"