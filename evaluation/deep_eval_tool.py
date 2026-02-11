"""
deep_eval_tool.py - DeepEval 기반 Tool Call 정확도 평가

설정: eval_config.yaml (공통) + eval_tool_config.yaml (시나리오/도구)

평가 항목:
  1. ToolCorrectness: 올바른 도구를 호출했는가? (하이브리드: 결정론적 + LLM 최적성)
  2. ArgumentCorrectness: 인자가 적절한가?

구조:
  Phase 1 (async) — LLM tool-call 호출 → LLMTestCase 수집
  Phase 2 (sync)  — DeepEval metric.measure() 네이티브 호출

사용법:
  python deep_eval_tool.py              # v1, v2 둘 다
  python deep_eval_tool.py --strategy v2  # v2만

필요: OPENAI_API_KEY 환경변수
"""
import sys, os, json, asyncio, argparse, yaml
from datetime import datetime
from dotenv import load_dotenv

EVAL_DIR = os.path.dirname(os.path.abspath(__file__))
AGENT_DIR = os.path.join(EVAL_DIR, "..", "MCP_agent")
sys.path.insert(0, AGENT_DIR)

from langchain_openai import ChatOpenAI
from langchain_core.tools import tool
from langchain_core.messages import SystemMessage, HumanMessage

from deepeval.metrics import ToolCorrectnessMetric, ArgumentCorrectnessMetric
from deepeval.test_case import LLMTestCase, ToolCall

from nodes.context_builder import ContextBuilderNode, ContextBuilderConfig
from agent.persona_logic import PersonaManager

load_dotenv()
os.environ["OPENAI_API_KEY"] = os.getenv("OPENAI_API_KEY")


# ══════════════════════════════════════════════════════════
# YAML 로드
# ══════════════════════════════════════════════════════════

def load_yaml(filename: str) -> dict:
    with open(os.path.join(EVAL_DIR, "configs", filename), "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


# ══════════════════════════════════════════════════════════
# 더미 도구 정의 (스키마만 — 실행 안 함)
# ══════════════════════════════════════════════════════════

@tool
def web_search(query: str, display: int = 20) -> str:
    """네이버 검색을 수행합니다."""
    return ""

@tool
def naver_blog_search(query: str, display: int = 20) -> str:
    """네이버 블로그 검색을 수행합니다."""
    return ""

@tool
def naver_shopping_search(query: str, display: int = 20) -> str:
    """네이버 쇼핑 검색을 수행합니다."""
    return ""

@tool
def naver_place_search(query: str, display: int = 20) -> str:
    """네이버 플레이스 검색을 수행합니다."""
    return ""

@tool
def send_message(channel_id: str, content: str) -> str:
    """디스코드 채널에 메시지를 전송합니다."""
    return ""

@tool
def read_messages(channel_id: str, limit: int = 10) -> str:
    """디스코드 채널의 최근 메시지를 읽습니다."""
    return ""

@tool
def add_reaction(channel_id: str, message_id: str, emoji: str) -> str:
    """디스코드 메시지에 리액션을 추가합니다."""
    return ""

@tool
def channels_list() -> str:
    """슬랙 채널 목록을 조회합니다."""
    return ""

@tool
def conversations_history(channel_id: str, limit: int = 10) -> str:
    """슬랙 채널의 대화 내역을 조회합니다."""
    return ""

@tool
def conversations_add_message(channel_id: str, text: str) -> str:
    """슬랙 채널에 메시지를 전송합니다."""
    return ""

@tool
def conversations_search_messages(query: str) -> str:
    """슬랙 메시지를 검색합니다."""
    return ""

ALL_TOOLS = [
    web_search, naver_blog_search, naver_shopping_search, naver_place_search,
    send_message, read_messages, add_reaction,
    channels_list, conversations_history, conversations_add_message,
    conversations_search_messages,
]

# available_tools용 ToolCall 리스트 (하이브리드 점수 활성화)
ALL_TOOL_CALLS = [
    ToolCall(name=t.name, description=t.description)
    for t in ALL_TOOLS
]


# ══════════════════════════════════════════════════════════
# 공통 설정
# ══════════════════════════════════════════════════════════

class DummyRetriever:
    def search_with_threshold(self, **kwargs):
        return []


def build_system_prompt(strategy: str, profile: dict, intimacy: int, emotion: str, memories: list) -> str:
    config = ContextBuilderConfig(strategy=strategy)
    node = ContextBuilderNode(
        retriever=DummyRetriever(),
        persona_manager_cls=PersonaManager,
        config=config,
    )
    mem_with_metadata = [{"metadata": {}, **m} for m in memories]
    return node._build_system_prompt(
        retrieved_memories=mem_with_metadata,
        user_profile=profile,
        intimacy_level=intimacy,
        current_emotion=emotion,
    )


# ══════════════════════════════════════════════════════════
# Phase 1: Async — LLM 호출로 테스트 케이스 수집
# ══════════════════════════════════════════════════════════

async def collect_tool_responses(strategies: list[str], cfg: dict, tool_cfg: dict):
    """LLM에 tool-bound 호출을 보내고 LLMTestCase를 수집한다 (async)."""
    profile = cfg["profile"]
    intimacy = cfg.get("intimacy", 72)
    emotion = cfg["emotion"]
    memories = cfg["memories"]
    tool_descriptions = tool_cfg["tool_descriptions"]
    scenarios = tool_cfg["scenarios"]

    llm_base = ChatOpenAI(model="gpt-5.2", 
                        #   temperature=0.3,
                            max_tokens=4096)
    llm_with_tools = llm_base.bind_tools(ALL_TOOLS)

    results = {}
    for strategy in strategies:
        print(f"\n{'='*60}")
        print(f"  Tool Call 수집 — strategy: {strategy}")
        print(f"{'='*60}")

        system_prompt = build_system_prompt(strategy, profile, intimacy, emotion, memories)
        print(f"  프롬프트 길이: {len(system_prompt)}자")

        tc_test_cases = []
        ac_test_cases = []

        for i, scenario in enumerate(scenarios):
            query = scenario["input"]
            expected_names = scenario["expected"]
            cat = scenario["category"]

            response = await llm_with_tools.ainvoke([
                SystemMessage(content=system_prompt),
                HumanMessage(content=query),
            ])

            raw_calls = response.tool_calls or []
            called_names = [tc["name"] for tc in raw_calls]

            # ToolCorrectness용 ToolCall (이름 + 설명)
            tools_called_tc = [
                ToolCall(name=n, description=tool_descriptions.get(n, ""))
                for n in called_names
            ]
            expected_tools_tc = [
                ToolCall(name=n, description=tool_descriptions.get(n, ""))
                for n in expected_names
            ]

            tc_test_cases.append(LLMTestCase(
                input=query,
                actual_output=response.content or "(tool_calls only)",
                tools_called=tools_called_tc,
                expected_tools=expected_tools_tc,
            ))

            # ArgumentCorrectness용 ToolCall (이름 + 설명 + 인자)
            if raw_calls:
                tools_called_ac = [
                    ToolCall(
                        name=tc["name"],
                        description=tool_descriptions.get(tc["name"], ""),
                        input=tc.get("args", {}),
                    )
                    for tc in raw_calls
                ]
                ac_test_cases.append(LLMTestCase(
                    input=query,
                    actual_output=response.content or "(tool_calls only)",
                    tools_called=tools_called_ac,
                ))

            # 미리보기
            status = "OK" if called_names == expected_names else "DIFF"
            args_preview = {tc["name"]: tc.get("args", {}) for tc in raw_calls}
            print(f"  [{i+1}/{len(scenarios)}] [{cat}] {query}")
            print(f"    expected: {expected_names}")
            print(f"    called:   {called_names}  [{status}]")
            if args_preview:
                print(f"    args:     {args_preview}")

        results[strategy] = (tc_test_cases, ac_test_cases)

    return results


# ══════════════════════════════════════════════════════════
# Phase 2: Sync — DeepEval 평가 (프레임워크 네이티브)
# ══════════════════════════════════════════════════════════

def evaluate_strategy(strategy: str, tc_test_cases: list, ac_test_cases: list, scenarios: list):
    """DeepEval metric.measure()를 동기 호출한다. 이벤트 루프 충돌 없음."""
    print(f"\n{'='*60}")
    print(f"  Tool Call 평가 — strategy: {strategy}")
    print(f"{'='*60}")

    # ── ToolCorrectness (하이브리드: 결정론적 + LLM 최적성) ──
    print(f"\n  [1/2] ToolCorrectnessMetric 평가 중...")
    tc_scores, tc_reasons = [], []
    for tc_case in tc_test_cases:
        metric = ToolCorrectnessMetric(
            should_consider_ordering=True,
            available_tools=ALL_TOOL_CALLS,
            include_reason=True,
        )
        metric.measure(tc_case)
        tc_scores.append(metric.score or 0)
        tc_reasons.append(metric.reason or "")

    tc_avg = sum(tc_scores) / len(tc_scores) if tc_scores else 0
    tc_perfect = sum(1 for s in tc_scores if s >= 1.0)

    # ── ArgumentCorrectness ──
    ac_avg, ac_perfect, ac_scores, ac_reasons = 0, 0, [], []
    if ac_test_cases:
        print(f"  [2/2] ArgumentCorrectnessMetric 평가 중...")
        for ac_case in ac_test_cases:
            metric = ArgumentCorrectnessMetric(threshold=0.5, include_reason=True)
            metric.measure(ac_case)
            ac_scores.append(metric.score or 0)
            ac_reasons.append(metric.reason or "")

        ac_avg = sum(ac_scores) / len(ac_scores) if ac_scores else 0
        ac_perfect = sum(1 for s in ac_scores if s >= 1.0)
    else:
        print(f"  [2/2] ArgumentCorrectness: 도구 호출 없는 시나리오만 — 건너뜀")

    # ── 결과 출력 ──
    print(f"\n  {'메트릭':<28} {'평균':>8} {'완벽':>10}")
    print(f"  {'-'*50}")
    print(f"  {'ToolCorrectness (도구 선택)':<28} {tc_avg:>7.2f} {tc_perfect:>4}/{len(tc_scores)}")
    print(f"  {'ArgumentCorrectness (인자)':<28} {ac_avg:>7.2f} {ac_perfect:>4}/{len(ac_scores)}")

    # 카테고리별 ToolCorrectness
    categories = {}
    for scenario, score in zip(scenarios, tc_scores):
        cat = scenario["category"]
        categories.setdefault(cat, []).append(score)

    print(f"\n  {'카테고리':<12} {'도구선택':>8} {'건수':>6}")
    print(f"  {'-'*30}")
    for cat, cat_scores in categories.items():
        cat_avg = sum(cat_scores) / len(cat_scores)
        print(f"  {cat:<12} {cat_avg:>7.2f} {len(cat_scores):>6}")

    # 낮은 점수 reason
    low_tc = [(s, sc, r) for s, sc, r in zip(scenarios, tc_scores, tc_reasons) if sc < 1.0]
    if low_tc:
        print(f"\n  ToolCorrectness 실패 사유:")
        for s, sc, r in low_tc:
            print(f"    [{s['category']}] {s['input'][:30]}... → {sc:.2f}")
            if r:
                print(f"      {r[:120]}")

    # 시나리오별 상세 결과
    scenario_details = []
    for i, (scenario, tc_score) in enumerate(zip(scenarios, tc_scores)):
        scenario_details.append({
            "input": scenario["input"],
            "category": scenario["category"],
            "expected": scenario["expected"],
            "tool_correctness": tc_score,
            "tc_reason": tc_reasons[i] if i < len(tc_reasons) else "",
        })

    # JSON 저장
    output_path = os.path.join(EVAL_DIR, "results", f"eval_tool_results_{strategy}.json")
    output = {
        "timestamp": datetime.now().isoformat(),
        "strategy": strategy,
        "scenarios": len(scenarios),
        "tool_correctness": {"avg": tc_avg, "perfect": tc_perfect, "total": len(tc_scores)},
        "argument_correctness": {"avg": ac_avg, "perfect": ac_perfect, "total": len(ac_scores)},
        "details": scenario_details,
    }
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)
    print(f"\n  결과 저장: {output_path}")


# ══════════════════════════════════════════════════════════
# 엔트리포인트
# ══════════════════════════════════════════════════════════

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="DeepEval Tool Call 평가")
    parser.add_argument("--strategy", type=str, default="v1,v2",
                        help="평가할 전략 (v1, v2, 또는 v1,v2)")
    args = parser.parse_args()
    strategies = [s.strip() for s in args.strategy.split(",")]

    cfg = load_yaml("eval_config.yaml")
    tool_cfg = load_yaml("eval_tool_config.yaml")
    scenarios = tool_cfg["scenarios"]

    # Phase 1: Async — LLM 호출
    collected = asyncio.run(collect_tool_responses(strategies, cfg, tool_cfg))

    # Phase 2: Sync — DeepEval 평가 (프레임워크 네이티브, 이벤트 루프 충돌 없음)
    for strategy, (tc_test_cases, ac_test_cases) in collected.items():
        evaluate_strategy(strategy, tc_test_cases, ac_test_cases, scenarios)
