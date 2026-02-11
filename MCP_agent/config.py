"""
config.py - MCP 서버 설정, 민감 도구 분류, 환경변수 로드

모든 설정과 MCP 도구 로딩을 중앙 관리
"""

import os
from typing import List
from dotenv import load_dotenv

load_dotenv()

# ============================================================
# 환경변수
# ============================================================

API_KEY = os.getenv("NCP_CLOVASTUDIO_API_KEY", "")
REQUEST_ID = os.getenv("NCP_CLOVASTUDIO_REQUEST_ID", "")
HOST = "clovastudio.stream.ntruss.com"
SLACK_MCP_URL = os.getenv("SLACK_MCP_URL")

# ============================================================
# MCP 서버 설정
# ============================================================

MCP_SERVERS = {
    "naver_search": {
        "url": "http://127.0.0.1:8000/mcp/",
        "transport": "streamable_http",
    },
    "discord-mcp": {
        "url": "http://localhost:8001/mcp/",
        "transport": "streamable_http",
    },
    "playwright-mcp": {
        "url": "http://localhost:8931/mcp",
        "transport": "streamable_http",
    },
}

if SLACK_MCP_URL:
    MCP_SERVERS["slack-mcp"] = {
        "url": SLACK_MCP_URL,
        "transport": "sse",
    }

# ============================================================
# 민감 도구 분류
# ============================================================

SENSITIVE_TOOL_NAMES = {
    "send_message",
    "read_messages",
    "add_reaction",
    "channels_list",
    "conversations_history",
    "conversations_add_message",
    # Google Calendar
    "list_calendar_events",
    "create_calendar_event",
    "update_calendar_event",
    "delete_calendar_event",
}

# ============================================================
# MCP 도구 로딩
# ============================================================

async def load_mcp_tools() -> tuple[List, List]:
    """MCP 서버에서 도구를 로드하고 safe/sensitive로 분류"""
    try:
        from langchain_mcp_adapters.client import MultiServerMCPClient
    except ImportError:
        print("Warning: langchain-mcp-adapters not found. MCP features disabled.")
        return [], []

    safe_tools = []
    sensitive_tools = []

    try:
        client = MultiServerMCPClient(MCP_SERVERS)
        all_tools = await client.get_tools()

        for t in all_tools:
            name = t.name if hasattr(t, "name") else str(t)
            if name in SENSITIVE_TOOL_NAMES:
                sensitive_tools.append(t)
            else:
                safe_tools.append(t)

        print(f"[MCP] Loaded {len(safe_tools)} safe tools, {len(sensitive_tools)} sensitive tools")

    except Exception as e:
        print(f"[MCP] Error loading tools: {e}")

    return safe_tools, sensitive_tools
