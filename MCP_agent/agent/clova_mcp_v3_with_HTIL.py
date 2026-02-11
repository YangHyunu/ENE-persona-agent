"""
agent/clova_mcp_v3.py - v2 + Analyzer 통합

v2 대비 추가:
- AnalyzerNode: 사용자 감정/호감도 분석 (LLM 1회 추가)

구조:
  START → context_builder → analyzer → agent ↔ tools → memory_manager → END

특징:
1. context_builder: 자동 기억 검색 + 시스템 프롬프트 (LLM 없음)
2. analyzer: 감정/호감도 분석 (LLM 1회)
3. agent: 도구 사용 + 최종 응답 (LLM 1회)
4. 총 LLM 호출: 2회 (analyzer + agent)
"""

import os
import sys
import asyncio
import uuid
import re
import json
from typing import List, Dict, Any, Optional
from datetime import datetime
from dotenv import load_dotenv

# 상위 디렉토리 추가
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# LangGraph/LangChain 임포트
from langgraph.graph import StateGraph, START, END
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver
from langgraph.prebuilt import ToolNode
from langchain_core.messages import HumanMessage, AIMessage, SystemMessage, ToolMessage

# MCP 클라이언트
try:
    from langchain_mcp_adapters.client import MultiServerMCPClient
    HAS_MCP = True
except ImportError:
    print("Warning: langchain-mcp-adapters not found. MCP features disabled.")
    HAS_MCP = False

# Clova LLM
try:
    from langchain_naver import ChatClovaX
    HAS_CLOVA = True
except ImportError:
    print("Warning: langchain-naver not found.")
    HAS_CLOVA = False

from langchain_core.utils.function_calling import convert_to_openai_tool

# 로컬 모듈
from memory import create_memory_system
from nodes import (
    ContextBuilderNode,
    ContextBuilderConfig,
    AnalyzerNode,
    AnalyzerConfig,
    MemoryManagerNode,
    MemoryManagerConfig
)
from graph import AgentState, AgentNode
from agent.persona_logic import PersonaManager


# ============================================================
# 환경 설정
# ============================================================

load_dotenv()

API_KEY = os.getenv("NCP_CLOVASTUDIO_API_KEY", "")
REQUEST_ID = os.getenv("NCP_CLOVASTUDIO_REQUEST_ID", "")
HOST = 'clovastudio.stream.ntruss.com'
SLACK_MCP_URL = os.getenv("SLACK_MCP_URL")

# MCP 서버 설정
MCP_SERVERS = {
    "naver_search": {
        "url": "http://127.0.0.1:8000/mcp/",
        "transport": "streamable_http"
    },
    "discord-mcp": {
        "url": "http://localhost:8001/mcp/",
        "transport": "streamable_http"
    },
    "playwright-mcp": {
        "url": "http://localhost:8931/mcp",
        "transport": "streamable_http",
    }
}

if SLACK_MCP_URL:
    MCP_SERVERS["slack-mcp"] = {
        "url": SLACK_MCP_URL,
        "transport": "sse",
    }

# 민감한 도구 목록
SENSITIVE_TOOL_NAMES = {
    "send_message",
    "read_messages",
    "add_reaction",
    "channels_list",
    "conversations_history",
    "conversations_add_message"
}


# ============================================================
# Tool Schema Fix for Clova
# ============================================================

def _recursive_fix_properties(schema: Any):
    if isinstance(schema, dict):
        if schema.get("type") == "object" and "properties" not in schema:
            schema["properties"] = {}
        for key, value in schema.items():
            _recursive_fix_properties(value)
    elif isinstance(schema, list):
        for item in schema:
            _recursive_fix_properties(item)


def fix_clova_tool_schema(tools):
    fixed_tools = []
    for tool in tools:
        try:
            schema = convert_to_openai_tool(tool)
        except Exception:
            continue
        if "function" in schema:
            func = schema["function"]
            if "parameters" not in func or not func["parameters"]:
                func["parameters"] = {"type": "object", "properties": {}, "required": []}
            if "properties" not in func["parameters"]:
                func["parameters"]["properties"] = {}
            if not func["parameters"]["properties"]:
                func["parameters"]["properties"] = {"_dummy": {"type": "string", "description": "Ignore"}}
            _recursive_fix_properties(func["parameters"])
        fixed_tools.append(schema)
    return fixed_tools


# ============================================================
# MCP 도구 로드
# ============================================================

async def load_mcp_tools() -> tuple[List, List]:
    if not HAS_MCP:
        return [], []

    safe_tools = []
    sensitive_tools = []

    try:
        client = MultiServerMCPClient(MCP_SERVERS)
        all_tools = await client.get_tools()

        for t in all_tools:
            name = t.name if hasattr(t, 'name') else str(t)
            if name in SENSITIVE_TOOL_NAMES:
                sensitive_tools.append(t)
            else:
                safe_tools.append(t)

        print(f"[MCP] Loaded {len(safe_tools)} safe tools, {len(sensitive_tools)} sensitive tools")

    except Exception as e:
        print(f"[MCP] Error loading tools: {e}")

    return safe_tools, sensitive_tools


# ============================================================
# 라우팅 함수
# ============================================================

def route_after_agent(state: AgentState) -> str:
    """Agent 응답 후 라우팅"""
    messages = state.get("messages", [])

    if not messages:
        return "memory_manager"

    last_message = messages[-1]

    if not isinstance(last_message, AIMessage):
        return "memory_manager"

    tool_calls = getattr(last_message, "tool_calls", None)

    if not tool_calls:
        return "memory_manager"

    called_names = [tc.get("name", "") for tc in tool_calls]

    if any(name in SENSITIVE_TOOL_NAMES for name in called_names):
        return "sensitive_tools"

    return "safe_tools"
# ============================================================
# HITL
# ============================================================
async def execute_graph_with_hitl(graph, inputs, config):
    """
    HITL 처리를 포함한 그래프 실행 함수
    """
    current_inputs = inputs

    while True:
        should_break_execution = False
        
        # astream을 통해 노드별 업데이트를 추적
        async for chunk in graph.astream(current_inputs, config=config, stream_mode="updates"):
            for node_name, output in chunk.items():
                if node_name == "agent":
                    # Agent가 응답을 생성한 경우
                    if "messages" in output and output["messages"]:
                        last_msg = output["messages"][-1]
                        
                        # 도구 호출이 있는지 확인
                        if hasattr(last_msg, "tool_calls") and last_msg.tool_calls:
                            tool_names = [tc["name"] for tc in last_msg.tool_calls]
                            
                            # 민감한 도구가 포함되어 있다면 승인 절차 진행
                            if any(name in SENSITIVE_TOOL_NAMES for name in tool_names):
                                print("\n" + "!" * 30)
                                print("🚨 [보안] 민감한 도구 실행 승인 요청")
                                for tc in last_msg.tool_calls:
                                    print(f"🛠️  실행 도구: {tc['name']}\n   매개변수: {tc['args']}")
                                
                                approval = input("\n승인하시겠습니까? (y/n): ").strip().lower()

                                if approval != 'y':
                                    print("❌ 사용자가 실행을 거부했습니다.")
                                    rejection_msgs = [
                                        ToolMessage(
                                            tool_call_id=tc['id'],
                                            content="사용자가 이 작업을 거부했습니다. 다른 대안을 제시하거나 거부 사실을 알리세요."
                                        ) for tc in last_msg.tool_calls
                                    ]
                                    # 거부 메시지를 강제로 상태에 주입 (sensitive_tools 노드가 실행된 것처럼)
                                    await graph.aupdate_state(
                                        config,
                                        {"messages": rejection_msgs},
                                        as_node="sensitive_tools"
                                    )
                                    # 입력을 None으로 만들고 다음 루프에서 Agent가 거부 상황을 인지하게 함
                                    current_inputs = None
                                    should_break_execution = True
                                    break
                                else:
                                    print("✅ 승인됨. 작업을 진행합니다...")

                elif node_name == "memory_manager":
                    # 최종 완료 단계
                    pass

            if should_break_execution:
                break

        # 루프 종료 조건 확인
        current_state = await graph.aget_state(config)
        if not current_state.next:
            return True
        
        current_inputs = None # 연속 실행을 위해 입력 초기화




# ============================================================
# 그래프 생성 (v3: context_builder + analyzer + agent)
# ============================================================

def create_graph_v3(
    llm,
    analyzer_llm,
    safe_tools: List,
    sensitive_tools: List,
    tool_fixer,
    retriever,
    repository,
    summarizer,
    window_trimmer,
    persona_manager_cls,
    checkpointer=None,
    context_config=None,
    analyzer_config=None,
    memory_config=None
):
    """
    v3 그래프 생성: context_builder + analyzer + agent

    v2 대비:
    - analyzer 노드 추가 (감정/호감도 분석)
    """
    all_tools = safe_tools + sensitive_tools

    # 노드 인스턴스 생성
    context_builder = ContextBuilderNode(
        retriever=retriever,
        persona_manager_cls=persona_manager_cls,
        config=context_config
    )

    analyzer = AnalyzerNode(
        llm=analyzer_llm,
        config=analyzer_config
    )

    agent = AgentNode(
        llm=llm,
        tools=all_tools,
        tool_fixer=tool_fixer
    )

    safe_tool_node = ToolNode(safe_tools)
    sensitive_tool_node = ToolNode(sensitive_tools)

    memory_manager = MemoryManagerNode(
        window_trimmer=window_trimmer,
        summarizer=summarizer,
        repository=repository,
        config=memory_config
    )

    # 그래프 정의
    workflow = StateGraph(AgentState)

    # 노드 추가
    workflow.add_node("context_builder", context_builder)
    workflow.add_node("analyzer", analyzer)
    workflow.add_node("agent", agent)
    workflow.add_node("safe_tools", safe_tool_node)
    workflow.add_node("sensitive_tools", sensitive_tool_node)
    workflow.add_node("memory_manager", memory_manager)

    # 엣지 정의: analyzer → context_builder → agent
    # analyzer가 먼저 감정 분석 → context_builder가 분석 결과 반영한 system_prompt 생성
    workflow.add_edge(START, "analyzer")
    workflow.add_edge("analyzer", "context_builder")
    workflow.add_edge("context_builder", "agent")

    # 조건부 라우팅
    workflow.add_conditional_edges(
        "agent",
        route_after_agent,
        {
            "safe_tools": "safe_tools",
            "sensitive_tools": "sensitive_tools",
            "memory_manager": "memory_manager"
        }
    )

    # 도구 실행 후 agent로 복귀
    workflow.add_edge("safe_tools", "agent")
    workflow.add_edge("sensitive_tools", "agent")
    workflow.add_edge("memory_manager", END)

    # 컴파일
    compile_kwargs = {}
    if checkpointer:
        compile_kwargs["checkpointer"] = checkpointer
    
    # HITL을 위한 인터럽트 추가
    return workflow.compile(
        **compile_kwargs,
        interrupt_before=["sensitive_tools"] 
    )


# ============================================================
# 그래프 생성 헬퍼
# ============================================================

async def create_agent_graph(checkpointer):
    """v3 에이전트 그래프 생성"""
    if not HAS_CLOVA or not API_KEY:
        raise ValueError("Clova API key not configured")

    # 1. 메모리 시스템 생성
    print("[Init] Creating memory system...")
    memory_system = create_memory_system(
        api_key=API_KEY,
        request_id=REQUEST_ID,
        host=HOST,
        persist_directory="./chroma_db"
    )

    # 2. MCP 도구 로드
    print("[Init] Loading MCP tools...")
    safe_tools, sensitive_tools = await load_mcp_tools()

    # 3. LLM 생성
    print("[Init] Creating LLMs...")

    # Agent용 LLM
    agent_llm = ChatClovaX(
        model="HCX-005",
        temperature=0.5,
        max_tokens=4096
    )

    # Analyzer용 LLM (더 낮은 temperature)
    analyzer_llm = ChatClovaX(
        model="HCX-005",
        temperature=0.1,
        max_tokens=1024
    )

    print(f"[Init] Total {len(safe_tools) + len(sensitive_tools)} tools loaded")

    # 4. 그래프 생성
    print("[Init] Building v3 graph (with analyzer)...")
    graph = create_graph_v3(
        llm=agent_llm,
        analyzer_llm=analyzer_llm,
        safe_tools=safe_tools,
        sensitive_tools=sensitive_tools,
        tool_fixer=fix_clova_tool_schema,
        retriever=memory_system["retriever"],
        repository=memory_system["repository"],
        summarizer=memory_system["summarizer"],
        window_trimmer=memory_system["window_trimmer"],
        persona_manager_cls=PersonaManager,
        checkpointer=checkpointer,
        context_config=ContextBuilderConfig(
            max_memories=5,
            similarity_threshold=0.7
        ),
        analyzer_config=AnalyzerConfig(
            max_intimacy_change=5,
            temperature=0.1,
            max_tokens=512
        ),
        memory_config=MemoryManagerConfig(
            token_threshold=8192,
            max_tokens_after_trim=4000
        )
    )

    print("[Init] v3 Graph ready!")
    return graph

# ============================================================
# 세션관리
# ============================================================

def get_last_thread_id():
    if os.path.exists("last_session.txt"):
        with open("last_session.txt", "r") as f:
            return f.read().strip()
    return "mcp_default_session"

# 세션 ID 저장 함수
def save_last_thread_id(thread_id):
    with open("last_session.txt", "w") as f:
        f.write(thread_id)


# ============================================================
# 세션 실행
# ============================================================

async def run_session():
    """대화 세션 실행"""

    print("\n" + "=" * 60)
    print("  MCP Agent v3 (with Analyzer)")
    print("  구조: context_builder → analyzer → agent ↔ tools")
    print("=" * 60)
    print("\n명령어: /status, /boost, /reset, /tools, /quit\n")

    async with AsyncSqliteSaver.from_conn_string("persona_mcp_v3.sqlite") as checkpointer:
        try:
            graph = await create_agent_graph(checkpointer)
        except Exception as e:
            print(f"Error creating graph: {e}")
            return
        


        current_thread_id = get_last_thread_id()
        config = {
            "configurable": {
                "thread_id": current_thread_id
            }
        }

        user_profile = {
            "nickname": "",
            "relation_type": "친한 친구",
            "first_meet_date": datetime.now().isoformat()
        }

        while True:
            try:
                current = await graph.aget_state(config)
                current_vals = current.values if current.values else {}
                user_input = input("\n You: ").strip()

                if not user_input:
                    continue

                # 명령어 처리
                if user_input.lower() == "/quit":
                    print(" 안녕히 가세요!")
                    break

                if user_input.lower() == "/status":
                    print("\n 세션 상태:")
                    print(f"  Thread ID: mcp_session_v3")
                    print(f"  Profile: {current_vals.get('user_profile', user_profile)}")
                    print(f"  Intimacy Level: {current_vals.get('intimacy_level', 0)}")
                    print(f"  Current Emotion: {current_vals.get('current_emotion', 'N/A')}")
                    continue

                if user_input.lower() == "/boost":
                    level = current_vals.get("intimacy_level", 0)
                    await graph.aupdate_state(config, {"intimacy_level": min(100, level + 10)}, as_node="memory_manager")
                    print(f"친밀도 증가: {level} -> {min(100, level + 10)}")
                    continue

                if user_input == "/reset":
                    new_thread_id = f"mcp_session_v3_{uuid.uuid4().hex[:8]}"
                    new_id = f"mcp_session_{uuid.uuid4().hex[:8]}"
                    config["configurable"]["thread_id"] = new_id
                    save_last_thread_id(new_id) # 파일에 새 ID 기록
                    user_profile = {"nickname": "", "relation_type": "AI 비서"}

                    print(f"✨ 새 세션 시작: {new_id}")

            


                    print(f"전체 초기화 완료 (새 세션: {new_thread_id})")
                    continue

                if user_input == "/tools":
                    safe_tools, sensitive_tools = await load_mcp_tools()
                    print(f"[Safe Tools]: {[t.name for t in safe_tools]}")
                    print(f"[Sensitive Tools]: {[t.name for t in sensitive_tools]}")
                    continue

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

                print("\n AI: ", end="", flush=True)



                await execute_graph_with_hitl(graph, state, config)

                # 3. [변경] 실행이 완료된 후의 최종 상태를 다시 가져옵니다.
                final_state = await graph.aget_state(config)
                result = final_state.values  # 기존의 result 변수 역할을 수행
                # 4. 응답 처리 및 출력 로직 (기존 로직 유지)
                if result.get("messages"):
                    # 마지막 AI 메시지를 찾아 답변과 친밀도 변화를 파싱합니다.
                    for msg in reversed(result["messages"]):
                        if isinstance(msg, AIMessage) and msg.content:
                            try:
                                json_match = re.search(r'\{[^{}]*"답변"[^{}]*\}', msg.content)
                                if json_match:
                                    response_data = json.loads(json_match.group())

                                    # 호감도 변화
                                    affinity_change = response_data.get("호감도변화", 0)
                                    if affinity_change:
                                        current_intimacy = current_vals.get("intimacy_level", 0)
                                        new_intimacy = max(0, min(100, current_intimacy + affinity_change))
                                        await graph.aupdate_state(config, {"intimacy_level": new_intimacy}, as_node="memory_manager")
                                        print(f"   친밀도: {current_intimacy} -> {new_intimacy}")

                                    # 닉네임 변화
                                    new_nickname = response_data.get("nickname", "")
                                    current_profile = current_vals.get("user_profile", user_profile)
                                    if new_nickname and new_nickname != current_profile.get("nickname", ""):
                                        updated_profile = {**current_profile, "nickname": new_nickname}
                                        await graph.aupdate_state(config, {"user_profile": updated_profile}, as_node="memory_manager")
                                        print(f"   닉네임 설정: '{new_nickname}'")

                                    # 관계 타입 변화
                                    new_relation = response_data.get("relation", "")
                                    if new_relation and new_relation != current_profile.get("relation_type", ""):
                                        updated_profile = current_vals.get("user_profile", user_profile)
                                        updated_profile = {**updated_profile, "relation_type": new_relation}
                                        await graph.aupdate_state(config, {"user_profile": updated_profile}, as_node="memory_manager")
                                        print(f"   관계 타입: '{new_relation}'")

                                    # 감정 상태 (Analyzer에서 이미 업데이트했지만 응답에서도 체크)
                                    new_emotion = response_data.get("감정", "")
                                    if new_emotion:
                                        await graph.aupdate_state(config, {"current_emotion": new_emotion}, as_node="memory_manager")
                                        print(f"   감정: '{new_emotion}'")

                                    answer = response_data.get("답변", msg.content)
                                    print(answer)
                                else:
                                    # JSON 형식이 아닐 경우 일반 출력
                                    if not msg.tool_calls: # 도구 호출 메시지는 출력 제외
                                        print(f"\nAI: {msg.content}")
                            except (json.JSONDecodeError, Exception):
                                if not msg.tool_calls:
                                    print(f"\nAI: {msg.content}")
                            break

                # 5. 메타데이터 및 Analyzer 결과 출력 (기존 로직 유지)
                metadata = result.get("context_metadata", {})
                if metadata.get("memories_found", 0) > 0:
                    print(f"   ({metadata['memories_found']}개의 관련 기억 활용됨)")

                emotion = result.get("current_emotion", "")
                if emotion:
                    print(f"   [Analyzer] 현재 감정: {emotion}")
                
            except KeyboardInterrupt:
                print("\n\n 안녕히 가세요!")
                break
            except Exception as e:
                print(f"\n Error: {e}")
                import traceback
                traceback.print_exc()

# def run():
#     asyncio.run(run_session())
# ============================================================
# 메인//
# ============================================================

if __name__ == "__main__":
    # run()
    asyncio.run(run_session())