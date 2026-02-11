#!/bin/bash

# 프로젝트 루트 디렉토리 설정 (스크립트 위치 기준으로 자동 감지)
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/../../.." && pwd)"
MCP_ROOT="$PROJECT_ROOT/MCP_agent/Fast-MCP"
ENV_FILE="$PROJECT_ROOT/.env"

echo "📁 Project Root: $PROJECT_ROOT"
echo "📁 MCP Root: $MCP_ROOT"

# Python 명령어 확인 (python3 우선)
if command -v python3 &> /dev/null; then
    PYTHON_CMD="python3"
elif command -v python &> /dev/null; then
    PYTHON_CMD="python"
else
    echo "❌ Python이 설치되어 있지 않습니다."
    exit 1
fi

# Node.js/npx 설치 확인
if ! command -v npx &> /dev/null; then
    echo "❌ Node.js/npx가 설치되어 있지 않습니다."
    echo "📋 다음 명령어를 실행하여 Node.js를 설치하세요:"
    echo "   brew install node"
    exit 1
fi

# .env 파일 존재 확인
if [ ! -f "$ENV_FILE" ]; then
    echo "⚠️  .env 파일이 없습니다. .env.example을 복사하세요."
    if [ -f "$PROJECT_ROOT/.env.example" ]; then
        cp "$PROJECT_ROOT/.env.example" "$ENV_FILE"
        echo "✅ .env.example을 .env로 복사했습니다. API 키를 설정하세요."
    fi
fi

# 환경 변수 로드 (파일 존재 시)
if [ -f "$ENV_FILE" ]; then
    set -o allexport
    source "$ENV_FILE"
    set +o allexport
    echo "✅ Loaded .env from: $ENV_FILE"
fi

# 토큰 검증
if [ -z "$DISCORD_TOKEN" ]; then
    echo "⚠️  DISCORD_TOKEN이 설정되지 않았습니다. Discord MCP를 건너뜁니다."
fi

if [ -z "$SLACK_MCP_XOXB_TOKEN" ]; then
    echo "⚠️  SLACK_MCP_XOXB_TOKEN이 설정되지 않았습니다. Slack MCP를 건너뜁니다."
fi

# naver_search mcp 서버 시작
echo "🚀 Starting Naver Search MCP..."
$PYTHON_CMD "$MCP_ROOT/mcp_servers/naver_mcp.py" &
NAVER_SEARCH_PID=$!
sleep 2

# discord mcp 서버 시작 (토큰 있을 때만)
if [ -n "$DISCORD_TOKEN" ]; then
    echo "🚀 Starting Discord MCP..."
    $PYTHON_CMD "$MCP_ROOT/mcp_servers/discord-mcp.py" &
    DISCORD_PID=$!
    sleep 2
else
    DISCORD_PID=""
fi

# Google Calendar MCP 시작
echo "🚀 Starting Google Calendar MCP on port 8002..."
# exec $PYTHON_CMD "$MCP_ROOT/mcp_servers/google_calendar_mcp.py"

# Playwright MCP 시작 (포트 사용 중이면 스킵)
if lsof -i :8931 > /dev/null 2>&1; then
    echo "⚠️  Port 8931 already in use, skipping Playwright MCP"
    PLAYWRIGHT_PID=""
else
    echo "🚀 Starting Playwright MCP..."
    npx @playwright/mcp@0.0.41 --port 8931 --timeout-action 30000 &
    PLAYWRIGHT_PID=$!
    sleep 2
fi

# Slack MCP 시작 (토큰 있을 때만)
if [ -n "$SLACK_MCP_XOXB_TOKEN" ]; then
    echo "🚀 Starting Slack MCP..."
    npx slack-mcp-server@latest --transport sse &
    MCP_PID=$!
    sleep 2

    # ngrok 시작 (설치되어 있을 때만)
    if command -v ngrok &> /dev/null; then
        echo "🚀 Starting ngrok tunnel..."
        ngrok http 3001 --log=stdout > /dev/null &
        NGROK_PID=$!
        sleep 3

        # ngrok URL 가져오기
        NGROK_URL=$(curl -s http://localhost:4040/api/tunnels 2>/dev/null | grep -o '"public_url":"[^"]*' | grep https | cut -d'"' -f4)

        if [ -n "$NGROK_URL" ]; then
            # macOS sed는 -i '' 필요
            if [[ "$OSTYPE" == "darwin"* ]]; then
                sed -i '' "s|^SLACK_MCP_URL=.*|SLACK_MCP_URL=$NGROK_URL/sse|" "$ENV_FILE"
            else
                sed -i "s|^SLACK_MCP_URL=.*|SLACK_MCP_URL=$NGROK_URL/sse|" "$ENV_FILE"
            fi

            if ! grep -q "^SLACK_MCP_URL=" "$ENV_FILE" 2>/dev/null; then
                echo "SLACK_MCP_URL=$NGROK_URL/sse" >> "$ENV_FILE"
            fi
            echo "✅ SLACK_MCP_URL: $NGROK_URL/sse"
        else
            echo "⚠️  ngrok URL을 가져올 수 없습니다."
        fi
    else
        echo "⚠️  ngrok이 설치되어 있지 않습니다. Slack MCP는 로컬에서만 사용 가능합니다."
        NGROK_PID=""
    fi
else
    MCP_PID=""
    NGROK_PID=""
fi

echo ""
echo "========================================="
echo "✅ Running MCP Servers:"
echo "   Naver Search MCP: http://localhost:8000/mcp/"
[ -n "$DISCORD_PID" ] && echo "   Discord MCP: http://localhost:8001/mcp/"
# [ -n "$GOOGLE_CALENDAR_PID" ] && echo "   Google Calendar MCP: http://localhost:8002/mcp/"
[ -n "$PLAYWRIGHT_PID" ] && echo "   Playwright MCP: http://localhost:8931"
[ -n "$MCP_PID" ] && echo "   Slack MCP Server: http://localhost:3001"
[ -n "$NGROK_URL" ] && echo "   ngrok URL: $NGROK_URL/sse"
echo "========================================="
echo "Press Ctrl+C to stop all servers"
echo ""

# Cleanup on exit
cleanup() {
    echo "🛑 Stopping servers..."
    [ -n "$NAVER_SEARCH_PID" ] && kill $NAVER_SEARCH_PID 2>/dev/null
    [ -n "$DISCORD_PID" ] && kill $DISCORD_PID 2>/dev/null
    # [ -n "$GOOGLE_CALENDAR_PID" ] && kill $GOOGLE_CALENDAR_PID 2>/dev/null
    [ -n "$PLAYWRIGHT_PID" ] && kill $PLAYWRIGHT_PID 2>/dev/null
    [ -n "$MCP_PID" ] && kill $MCP_PID 2>/dev/null
    [ -n "$NGROK_PID" ] && kill $NGROK_PID 2>/dev/null
    exit 0
}

trap cleanup SIGINT SIGTERM
wait