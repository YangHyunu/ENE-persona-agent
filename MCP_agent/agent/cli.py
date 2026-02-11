"""
cli.py - 순수 CLI 대화 인터페이스

graph.py + config.py 기반, GUI 없이 터미널에서 실행
"""

import sys
import os
import asyncio
import uuid
import re
import json
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver
from langchain_core.messages import HumanMessage, AIMessage, ToolMessage

from config import SENSITIVE_TOOL_NAMES, load_mcp_tools
from graph import create_agent_graph


# ============================================================
# Session Management
# ============================================================

def get_last_thread_id():
    if os.path.exists("last_session.txt"):
        with open("last_session.txt", "r") as f:
            return f.read().strip()
    return "mcp_default_session"


def save_last_thread_id(thread_id):
    with open("last_session.txt", "w") as f:
        f.write(thread_id)


# ============================================================
# HITL (CLI)
# ============================================================

async def execute_graph_with_hitl(graph, inputs, config):
    current_inputs = inputs

    while True:
        should_break = False

        async for chunk in graph.astream(current_inputs, config=config, stream_mode="updates"):
            for node_name, output in chunk.items():
                if node_name == "agent":
                    if "messages" in output and output["messages"]:
                        last_msg = output["messages"][-1]

                        if hasattr(last_msg, "tool_calls") and last_msg.tool_calls:
                            tool_names = [tc["name"] for tc in last_msg.tool_calls]

                            if any(name in SENSITIVE_TOOL_NAMES for name in tool_names):
                                print("\n" + "!" * 30)
                                print("[HITL] 민감한 도구 실행 승인 요청")
                                for tc in last_msg.tool_calls:
                                    print(f"  도구: {tc['name']}\n  매개변수: {tc['args']}")

                                approval = input("\n승인? (y/n): ").strip().lower()

                                if approval != 'y':
                                    print("[HITL] 거부됨")
                                    rejection_msgs = [
                                        ToolMessage(
                                            tool_call_id=tc['id'],
                                            content="사용자가 이 작업을 거부했습니다. 다른 대안을 제시하거나 거부 사실을 알리세요."
                                        ) for tc in last_msg.tool_calls
                                    ]
                                    await graph.aupdate_state(
                                        config,
                                        {"messages": rejection_msgs},
                                        as_node="sensitive_tools"
                                    )
                                    current_inputs = None
                                    should_break = True
                                    break
                                else:
                                    print("[HITL] 승인됨")

        if should_break:
            break

        current_state = await graph.aget_state(config)
        if not current_state.next:
            return current_state.values

        current_inputs = None


# ============================================================
# 응답 파싱
# ============================================================

async def process_response(graph, config, result, user_profile):
    """AI 응답 파싱 + 상태 업데이트"""
    current = await graph.aget_state(config)
    current_vals = current.values if current.values else {}

    if not result or not result.get("messages"):
        print("(응답 없음)")
        return

    for msg in reversed(result["messages"]):
        if not isinstance(msg, AIMessage) or not msg.content:
            continue
        if getattr(msg, "tool_calls", None):
            continue

        try:
            json_match = re.search(r'\{[^{}]*"답변"[^{}]*\}', msg.content)
            if json_match:
                data = json.loads(json_match.group())
                answer = data.get("답변", msg.content)

                # 호감도
                change = data.get("호감도변화", 0)
                if change:
                    cur = current_vals.get("intimacy_level", 0)
                    new = max(0, min(100, cur + change))
                    await graph.aupdate_state(config, {"intimacy_level": new})
                    print(f"   친밀도: {cur} -> {new}")

                # 닉네임
                current_profile = current_vals.get("user_profile", user_profile)
                new_nick = data.get("nickname", "")
                if new_nick and new_nick != current_profile.get("nickname", ""):
                    current_profile = {**current_profile, "nickname": new_nick}
                    await graph.aupdate_state(config, {"user_profile": current_profile})
                    print(f"   닉네임: '{new_nick}'")

                # 관계 (current_profile을 재사용 → 닉네임 유실 방지)
                new_rel = data.get("relation", "")
                if new_rel and new_rel != current_profile.get("relation_type", ""):
                    current_profile = {**current_profile, "relation_type": new_rel}
                    await graph.aupdate_state(config, {"user_profile": current_profile})
                    print(f"   관계: '{new_rel}'")

                # 감정
                new_emo = data.get("감정", "")
                if new_emo:
                    await graph.aupdate_state(config, {"current_emotion": new_emo})
                    print(f"   감정: '{new_emo}'")

                print(f"\n{answer}")
            else:
                print(f"\n{msg.content}")
        except (json.JSONDecodeError, Exception):
            print(f"\n{msg.content}")
        break

    # 메타데이터
    metadata = result.get("context_metadata", {})
    if metadata.get("memories_found", 0) > 0:
        print(f"   ({metadata['memories_found']}개의 관련 기억 활용됨)")

    emotion = result.get("current_emotion", "")
    if emotion:
        print(f"   [Analyzer] 감정: {emotion}")


# ============================================================
# 명령어 처리
# ============================================================

async def handle_command(command, graph, config, user_profile):
    """슬래시 명령어 처리. True 반환 시 루프 종료."""
    if command == "/quit":
        print("안녕히 가세요!")
        return True

    if command == "/status":
        current = await graph.aget_state(config)
        vals = current.values if current.values else {}
        print(f"  Thread: {config['configurable']['thread_id']}")
        print(f"  Profile: {vals.get('user_profile', user_profile)}")
        print(f"  Intimacy: {vals.get('intimacy_level', 0)}")
        print(f"  Emotion: {vals.get('current_emotion', 'N/A')}")
        return False

    if command == "/boost":
        current = await graph.aget_state(config)
        vals = current.values if current.values else {}
        level = vals.get("intimacy_level", 0)
        new_level = min(100, level + 10)
        await graph.aupdate_state(config, {"intimacy_level": new_level}, as_node="sensitive_tools")
        print(f"친밀도: {level} -> {new_level}")
        return False

    if command == "/reset":
        new_id = f"mcp_session_v3_{uuid.uuid4().hex[:8]}"
        config["configurable"]["thread_id"] = new_id
        save_last_thread_id(new_id)
        user_profile.clear()
        user_profile.update({
            "nickname": "",
            "relation_type": "단짝 비서 ENE (에네)",
            "first_meet_date": datetime.now().isoformat()
        })
        print(f"새 세션: {new_id}")
        return False

    if command == "/tools":
        safe, sensitive = await load_mcp_tools()
        print(f"  Safe: {[t.name for t in safe]}")
        print(f"  Sensitive: {[t.name for t in sensitive]}")
        return False

    print(f"알 수 없는 명령어: {command}")
    return False


# ============================================================
# Main
# ============================================================

async def run_session():
    print("\n" + "=" * 50)
    print("  ENE CLI - MCP Agent v3")
    print("  명령어: /status /boost /reset /tools /quit")
    print("=" * 50 + "\n")

    try:
        import aiosqlite
    except ImportError:
        print("[ERROR] pip install aiosqlite")
        return

    async with AsyncSqliteSaver.from_conn_string("persona_mcp_v3.sqlite") as checkpointer:
        try:
            graph = await create_agent_graph(checkpointer)
        except Exception as e:
            print(f"[ERROR] {e}")
            import traceback
            traceback.print_exc()
            return

        thread_id = get_last_thread_id()
        save_last_thread_id(thread_id)

        config = {
            "recursion_limit": 25,
            "configurable": {"thread_id": thread_id}
        }

        user_profile = {
            "nickname": "",
            "relation_type": "단짝 비서 ENE (에네)",
            "first_meet_date": datetime.now().isoformat()
        }

        print(f"[Session] {thread_id}\n")

        while True:
            try:
                user_input = input("You: ").strip()
                if not user_input:
                    continue

                if user_input.startswith("/"):
                    should_quit = await handle_command(user_input, graph, config, user_profile)
                    if should_quit:
                        break
                    continue

                # 현재 상태
                current = await graph.aget_state(config)
                current_vals = current.values if current.values else {}

                state = {
                    "messages": [HumanMessage(content=user_input)],
                    "user_id": "default",
                    "intimacy_level": current_vals.get("intimacy_level", 0),
                    "user_profile": current_vals.get("user_profile", user_profile),
                    "current_emotion": current_vals.get("current_emotion", ""),
                    "system_prompt": "",
                    "retrieved_memories": [],
                    "context_metadata": {}
                }

                result = await execute_graph_with_hitl(graph, state, config)

                if result:
                    await process_response(graph, config, result, user_profile)

            except KeyboardInterrupt:
                print("\n안녕히 가세요!")
                break
            except Exception as e:
                print(f"[ERROR] {e}")
                import traceback
                traceback.print_exc()


if __name__ == "__main__":
    asyncio.run(run_session())
