"""
graph.py - v3 HITL LangGraph 파이프라인

구조:
  START → analyzer → context_builder → agent ↔ tools → memory_manager → END

포함:
- AgentState: 그래프 상태 TypedDict
- AgentNode: LLM 호출 + 도구 바인딩 노드
- route_after_agent: safe/sensitive/memory_manager 라우팅
- create_graph_v3: 5노드 파이프라인 조립
- create_agent_graph: 전체 의존성 주입 + 그래프 생성
"""

from typing import TypedDict, Annotated, List, Dict, Any, Optional, Type
import asyncio

from langgraph.graph import StateGraph, START, END
from langgraph.graph.message import add_messages
from langgraph.prebuilt import ToolNode
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver

from langchain_core.messages import (
    BaseMessage,
    SystemMessage,
    HumanMessage,
    AIMessage,
    ToolMessage,
)

from config import (
    API_KEY,
    REQUEST_ID,
    HOST,
    SENSITIVE_TOOL_NAMES,
    load_mcp_tools,
)


# ============================================================
# State 정의
# ============================================================

class AgentState(TypedDict):
    """그래프 상태 정의"""
    messages: Annotated[list[BaseMessage], add_messages]

    # 컨텍스트 빌더 출력
    system_prompt: str
    retrieved_memories: List[Dict[str, Any]]
    context_metadata: Dict[str, Any]

    # 사용자 정보
    user_id: str
    intimacy_level: int
    user_profile: Dict[str, Any]
    first_meet_date: str
    current_emotion: str


# ============================================================
# Agent 노드
# ============================================================

class AgentNode:
    """
    Agent 노드 - 유일한 LLM 호출 지점

    context_builder가 만든 system_prompt를 사용하여 응답 생성
    매 호출마다 도구를 fresh하게 바인딩 (Clova 호환)
    """

    def __init__(self, llm, tools: List, tool_fixer):
        self.llm = llm
        self.tools = tools
        self.tool_fixer = tool_fixer

    async def __call__(self, state: AgentState, config=None) -> Dict[str, Any]:
        messages = state.get("messages", [])
        system_prompt = state.get("system_prompt", "")

        full_messages = []

        if system_prompt:
            full_messages.append(SystemMessage(content=system_prompt))

        for msg in messages:
            if isinstance(msg, ToolMessage):
                full_messages.append(msg)
            elif isinstance(msg, AIMessage):
                if msg.content or getattr(msg, "tool_calls", None):
                    full_messages.append(msg)
            elif isinstance(msg, HumanMessage):
                if msg.content:
                    full_messages.append(msg)

        sanitized_tools = self.tool_fixer(self.tools)
        llm_with_tools = self.llm.bind_tools(sanitized_tools)

        response = await self._invoke_with_retry(llm_with_tools, full_messages, config)

        if response is None:
            response = AIMessage(content="죄송해요, 응답을 생성하지 못했어요. 다시 시도해 주세요.")

        return {"messages": [response]}

    async def _invoke_with_retry(self, llm_with_tools, messages: List, config=None):
        try:
            return await llm_with_tools.ainvoke(messages, config)
        except Exception as e:
            if "429" in str(e) or "rate" in str(e).lower():
                await asyncio.sleep(3)
                try:
                    return await llm_with_tools.ainvoke(messages, config)
                except Exception:
                    return AIMessage(content="잠시 요청이 많아요. 다시 말해줄래요?")
            return AIMessage(content=f"요청 처리 중 문제가 발생했어요: {str(e)[:100]}")


# ============================================================
# 라우팅
# ============================================================

def route_after_agent(state: AgentState) -> str:
    """Agent 응답 후 라우팅: safe_tools / sensitive_tools / memory_manager"""
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
# 그래프 생성 (v3: analyzer + context_builder + agent)
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
    memory_config=None,
):
    """v3 HITL 그래프 생성

    START → analyzer → context_builder → agent ↔ tools → memory_manager → END
    """
    from nodes import (
        ContextBuilderNode,
        AnalyzerNode,
        MemoryManagerNode,
    )

    all_tools = safe_tools + sensitive_tools

    context_builder = ContextBuilderNode(
        retriever=retriever,
        persona_manager_cls=persona_manager_cls,
        config=context_config,
    )

    analyzer = AnalyzerNode(llm=analyzer_llm, config=analyzer_config)

    agent = AgentNode(llm=llm, tools=all_tools, tool_fixer=tool_fixer)

    safe_tool_node = ToolNode(safe_tools)
    sensitive_tool_node = ToolNode(sensitive_tools)

    memory_manager = MemoryManagerNode(
        window_trimmer=window_trimmer,
        summarizer=summarizer,
        repository=repository,
        config=memory_config,
    )

    workflow = StateGraph(AgentState)

    workflow.add_node("context_builder", context_builder)
    workflow.add_node("analyzer", analyzer)
    workflow.add_node("agent", agent)
    workflow.add_node("safe_tools", safe_tool_node)
    workflow.add_node("sensitive_tools", sensitive_tool_node)
    workflow.add_node("memory_manager", memory_manager)

    workflow.add_edge(START, "analyzer")
    workflow.add_edge("analyzer", "context_builder")
    workflow.add_edge("context_builder", "agent")

    workflow.add_conditional_edges(
        "agent",
        route_after_agent,
        {
            "safe_tools": "safe_tools",
            "sensitive_tools": "sensitive_tools",
            "memory_manager": "memory_manager",
        },
    )

    workflow.add_edge("safe_tools", "agent")
    workflow.add_edge("sensitive_tools", "agent")
    workflow.add_edge("memory_manager", END)

    compile_kwargs = {}
    if checkpointer:
        compile_kwargs["checkpointer"] = checkpointer

    return workflow.compile(
        **compile_kwargs,
        interrupt_before=["sensitive_tools"],
    )


# ============================================================
# 전체 의존성 주입 + 그래프 생성
# ============================================================

async def create_agent_graph(checkpointer):
    """메모리 시스템 + LLM + MCP 도구를 조립하여 완성된 그래프 반환"""
    from langchain_openai import ChatOpenAI, OpenAIEmbeddings
    from memory import create_memory_system
    from nodes import ContextBuilderConfig, AnalyzerConfig, MemoryManagerConfig
    from agent.persona_logic import PersonaManager

    if not API_KEY:
        raise ValueError("NCP_CLOVASTUDIO_API_KEY not configured")

    print("[Init] Creating memory system...")
    openai_embeddings = OpenAIEmbeddings(model="text-embedding-3-small")

    memory_system = create_memory_system(
        api_key=API_KEY,
        request_id=REQUEST_ID,
        host=HOST,
        persist_directory="./chroma_db",
        embeddings=openai_embeddings,
    )

    print("[Init] Loading MCP tools...")
    safe_tools, sensitive_tools = await load_mcp_tools()

    print("[Init] Creating LLMs...")
    agent_llm = ChatOpenAI(model="gpt-4o", temperature=0.5, max_tokens=4096)
    analyzer_llm = ChatOpenAI(model="gpt-4o-mini", temperature=0.1, max_tokens=1024)

    print(f"[Init] Total {len(safe_tools) + len(sensitive_tools)} tools loaded")

    print("[Init] Building v3 graph (with analyzer)...")
    graph = create_graph_v3(
        llm=agent_llm,
        analyzer_llm=analyzer_llm,
        safe_tools=safe_tools,
        sensitive_tools=sensitive_tools,
        tool_fixer=lambda tools: tools,
        retriever=memory_system["retriever"],
        repository=memory_system["repository"],
        summarizer=memory_system["summarizer"],
        window_trimmer=memory_system["window_trimmer"],
        persona_manager_cls=PersonaManager,
        checkpointer=checkpointer,
        context_config=ContextBuilderConfig(
            max_memories=5, similarity_threshold=0.7, strategy="v2"
        ),
        analyzer_config=AnalyzerConfig(
            max_intimacy_change=5, temperature=0.1, max_tokens=512
        ),
        memory_config=MemoryManagerConfig(
            token_threshold=8192, max_tokens_after_trim=4000
        ),
    )

    print("[Init] v3 Graph ready!")
    return graph
