"""
deep_eval_pr.py - DeepEval ArenaGEval 기반 v1 vs v2 프롬프트 A/B 평가

설정: eval_config.yaml (공통) + eval_pr_config.yaml (메트릭/시드)

구조:
  Phase 1 (async) — 질문 생성 + v1/v2 응답 수집 → ArenaTestCase
  Phase 2 (sync)  — ArenaGEval metric.measure() 네이티브 호출

사용법:
  python deep_eval_pr.py                    # 기본 (시드 3개 x 5문항, 호감도 72)
  python deep_eval_pr.py --per-seed 3       # 시드당 3문항
  python deep_eval_pr.py --seeds 5          # 시드 5개 사용
  python deep_eval_pr.py --matrix           # 호감도×만남기간 매트릭스 전체 평가

필요: OPENAI_API_KEY 환경변수
"""
import sys, os, json, re, asyncio, argparse, yaml
from datetime import datetime, timedelta
from dotenv import load_dotenv

EVAL_DIR = os.path.dirname(os.path.abspath(__file__))
AGENT_DIR = os.path.join(EVAL_DIR, "..", "MCP_agent")
sys.path.insert(0, AGENT_DIR)

from langchain_openai import ChatOpenAI
from langchain_core.messages import SystemMessage, HumanMessage

from deepeval.metrics import ArenaGEval
from deepeval.test_case import ArenaTestCase, LLMTestCase, LLMTestCaseParams, Contestant

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
# 더미 retriever
# ══════════════════════════════════════════════════════════

class DummyRetriever:
    def search_with_threshold(self, **kwargs):
        return []


# ══════════════════════════════════════════════════════════
# 시나리오 자동 생성
# ══════════════════════════════════════════════════════════

async def generate_test_queries(seeds: list, per_seed: int, intimacy: int, days: int) -> list:
    llm = ChatOpenAI(model="gpt-5-mini", max_tokens=2048)

    all_queries = []
    for seed in seeds:
        category = seed["category"]
        description = seed["description"]
        prompt = f"""너는 AI 비서 "ENE"와 대화하는 사용자 역할이야.
아래 카테고리에 맞는 한국어 대화 입력을 {per_seed}개 생성해.

카테고리: {category}
설명: {description}
사용자 설정: 닉네임 "현우", 호감도 {intimacy}, 만남 {days}일째

규칙:
- 실제 사용자가 타이핑할 법한 자연스러운 문장
- 각각 다른 의도를 가진 문장
- JSON 배열로 출력: ["문장1", "문장2", ...]"""

        response = await llm.ainvoke([HumanMessage(content=prompt)])

        try:
            match = re.search(r'\[.*\]', response.content, re.DOTALL)
            if match:
                queries = json.loads(match.group())
                for q in queries[:per_seed]:
                    all_queries.append({"category": category, "query": q})
        except (json.JSONDecodeError, Exception) as e:
            print(f"  [WARN] {category} 생성 실패: {e}")

    return all_queries


# ══════════════════════════════════════════════════════════
# 프롬프트 빌드
# ══════════════════════════════════════════════════════════

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
# LLM 응답 생성
# ══════════════════════════════════════════════════════════

async def get_response(llm, system_prompt: str, query: str) -> str:
    messages = [
        SystemMessage(content=system_prompt),
        HumanMessage(content=query),
    ]
    response = await llm.ainvoke(messages)
    if not response.content:
        print(f"    [WARN] empty content | type={type(response)}")
    return response.content


# ══════════════════════════════════════════════════════════
# ArenaGEval 메트릭 생성 (YAML 기반)
# ══════════════════════════════════════════════════════════

PARAM_MAP = {
    "INPUT": LLMTestCaseParams.INPUT,
    "ACTUAL_OUTPUT": LLMTestCaseParams.ACTUAL_OUTPUT,
    "EXPECTED_OUTPUT": LLMTestCaseParams.EXPECTED_OUTPUT,
    "CONTEXT": LLMTestCaseParams.CONTEXT,
    "RETRIEVAL_CONTEXT": LLMTestCaseParams.RETRIEVAL_CONTEXT,
}


def create_arena_metric(mc: dict, intimacy: int = 72, expected_tone: str = "") -> ArenaGEval:
    criteria = mc["criteria"].format(
        intimacy=intimacy,
        expected_tone=expected_tone or f"호감도 {intimacy}에 맞는 말투",
    )
    params = [PARAM_MAP[p] for p in mc["params"]]
    return ArenaGEval(
        name=mc["name"],
        criteria=criteria,
        evaluation_steps=mc["evaluation_steps"],
        evaluation_params=params,
    )


# ══════════════════════════════════════════════════════════
# Phase 1: Async — 질문 생성 + v1/v2 응답 수집
# ══════════════════════════════════════════════════════════

async def collect_arena_data(
    llm, profile: dict, intimacy: int, emotion: str, memories: list,
    seeds: list, per_seed: int,
):
    """질문을 생성하고 v1/v2 응답을 수집한다 (async)."""
    days = (datetime.now() - datetime.strptime(profile["first_meet_date"], "%Y-%m-%d")).days

    print(f"  질문 생성 중...")
    test_queries = await generate_test_queries(seeds, per_seed, intimacy, days)
    print(f"  질문 {len(test_queries)}개 생성 완료")

    prompt_v1 = build_system_prompt("v1", profile, intimacy, emotion, memories)
    prompt_v2 = build_system_prompt("v2", profile, intimacy, emotion, memories)

    arena_test_cases = []
    for i, tq in enumerate(test_queries):
        query = tq["query"]
        resp_v1 = await get_response(llm, prompt_v1, query) or "(empty)"
        resp_v2 = await get_response(llm, prompt_v2, query) or "(empty)"

        arena_test_cases.append(ArenaTestCase(
            contestants=[
                Contestant(
                    name="v1",
                    test_case=LLMTestCase(input=query, actual_output=resp_v1),
                ),
                Contestant(
                    name="v2",
                    test_case=LLMTestCase(input=query, actual_output=resp_v2),
                ),
            ]
        ))

        preview_v1 = resp_v1.replace("\n", " ")[:60]
        preview_v2 = resp_v2.replace("\n", " ")[:60]
        print(f"  [{i+1}/{len(test_queries)}] {tq['category']}")
        print(f"    v1: {preview_v1}...")
        print(f"    v2: {preview_v2}...")

    return arena_test_cases, days


async def collect_all(num_seeds: int, per_seed: int, use_matrix: bool):
    """모든 조건에 대해 arena 데이터를 수집한다."""
    cfg = load_yaml("eval_config.yaml")
    pr_cfg = load_yaml("eval_pr_config.yaml")

    profile = cfg["profile"]
    emotion = cfg["emotion"]
    memories = cfg["memories"]
    seeds = pr_cfg["scenario_seeds"][:num_seeds]

    llm = ChatOpenAI(model="o4-mini-2025-04-16", max_tokens=4096)

    collected = []

    if use_matrix:
        print(f"\n{'='*60}")
        print(f"  매트릭스 데이터 수집 ({len(cfg['test_matrix'])}개 조건)")
        print(f"{'='*60}")

        for entry in cfg["test_matrix"]:
            test_profile = {
                **profile,
                "first_meet_date": (datetime.now() - timedelta(days=entry["days_ago"])).strftime("%Y-%m-%d"),
            }
            print(f"\n{'─'*60}")
            print(f"  조건: {entry['label']} | 호감도={entry['intimacy']} | {entry['days_ago']}일째")
            print(f"{'─'*60}")

            arena_test_cases, days = await collect_arena_data(
                llm, test_profile, entry["intimacy"], emotion, memories, seeds, per_seed,
            )
            collected.append({
                "label": entry["label"],
                "intimacy": entry["intimacy"],
                "days": days,
                "expected_tone": entry["expected_tone"],
                "arena_test_cases": arena_test_cases,
            })
    else:
        intimacy = cfg.get("intimacy", 72)
        print(f"\n{'─'*60}")
        print(f"  조건: default | 호감도={intimacy}")
        print(f"{'─'*60}")

        arena_test_cases, days = await collect_arena_data(
            llm, profile, intimacy, emotion, memories, seeds, per_seed,
        )
        collected.append({
            "label": "default",
            "intimacy": intimacy,
            "days": days,
            "expected_tone": "",
            "arena_test_cases": arena_test_cases,
        })

    return collected, pr_cfg


# ══════════════════════════════════════════════════════════
# Phase 2: Sync — ArenaGEval 평가 (프레임워크 네이티브)
# ══════════════════════════════════════════════════════════

def evaluate_arena(
    arena_test_cases: list, metric_configs: list,
    intimacy: int, expected_tone: str, label: str,
):
    """ArenaGEval metric.measure()를 동기 호출한다. 이벤트 루프 충돌 없음."""
    print(f"\n{'='*60}")
    print(f"  Arena 평가: {label} | 호감도={intimacy}")
    print(f"{'='*60}")

    metric_results = {}
    for mc in metric_configs:
        print(f"\n  비교 중: {mc['name']}")

        wins = {"v1": 0, "v2": 0, "draw": 0}
        for tc in arena_test_cases:
            m = create_arena_metric(mc, intimacy, expected_tone)
            m.measure(tc)
            w = m.winner if m.winner in ("v1", "v2") else "draw"
            wins[w] += 1

        metric_results[mc["name"]] = wins

    # 결과 출력
    total_queries = len(arena_test_cases)
    print(f"\n  {'메트릭':<25} {'v1승':>6} {'v2승':>6} {'무승부':>6} {'승자':>6}")
    print(f"  {'-'*54}")

    v1_total_wins, v2_total_wins = 0, 0
    for name, wins in metric_results.items():
        winner = "v2" if wins["v2"] > wins["v1"] else ("v1" if wins["v1"] > wins["v2"] else "draw")
        v1_total_wins += wins["v1"]
        v2_total_wins += wins["v2"]
        print(f"  {name:<25} {wins['v1']:>6} {wins['v2']:>6} {wins['draw']:>6} {winner:>6}")

    overall = "v2" if v2_total_wins > v1_total_wins else ("v1" if v1_total_wins > v2_total_wins else "draw")
    print(f"  {'-'*54}")
    print(f"  {'종합':<25} {v1_total_wins:>6} {v2_total_wins:>6} {'':>6} {overall:>6}")

    return {
        "label": label,
        "intimacy": intimacy,
        "metrics": metric_results,
        "v1_wins": v1_total_wins,
        "v2_wins": v2_total_wins,
        "winner": overall,
        "num_queries": total_queries,
    }


# ══════════════════════════════════════════════════════════
# 엔트리포인트
# ══════════════════════════════════════════════════════════

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="DeepEval ArenaGEval v1 vs v2 A/B 평가")
    parser.add_argument("--seeds", type=int, default=3, help="시드 개수")
    parser.add_argument("--per-seed", type=int, default=5, help="시드당 질문 수")
    parser.add_argument("--matrix", action="store_true", help="호감도×만남기간 매트릭스 전체 평가")
    args = parser.parse_args()

    # Phase 1: Async — LLM 호출 (질문 생성 + v1/v2 응답 수집)
    collected, pr_cfg = asyncio.run(collect_all(args.seeds, args.per_seed, args.matrix))
    metric_configs = pr_cfg["metrics"]

    # Phase 2: Sync — DeepEval 평가 (프레임워크 네이티브, 이벤트 루프 충돌 없음)
    all_results = []
    for entry in collected:
        result = evaluate_arena(
            entry["arena_test_cases"], metric_configs,
            entry["intimacy"], entry["expected_tone"], entry["label"],
        )
        result["days"] = entry["days"]
        all_results.append(result)

    # 최종 요약 (매트릭스)
    if len(all_results) > 1:
        print(f"\n{'='*60}")
        print(f"  매트릭스 종합 요약")
        print(f"{'='*60}")
        print(f"\n  {'조건':<16} {'호감도':>6} {'일수':>6} {'v1승':>6} {'v2승':>6} {'승자':>6}")
        print(f"  {'-'*50}")
        for r in all_results:
            print(f"  {r['label']:<16} {r['intimacy']:>6} {r['days']:>6} {r['v1_wins']:>6} {r['v2_wins']:>6} {r['winner']:>6}")

    # JSON 저장
    output = {
        "timestamp": datetime.now().isoformat(),
        "config": {"num_seeds": args.seeds, "per_seed": args.per_seed, "matrix": args.matrix},
        "results": all_results,
    }
    output_path = os.path.join(EVAL_DIR, "results", "eval_results.json")
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)
    print(f"\n결과 저장: {output_path}")
