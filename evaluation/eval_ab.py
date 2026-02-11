"""
v1 vs v2 A/B 테스트 스크립트

사용법:
  python eval_ab.py              # 기본 테스트 (5개 질문)
  python eval_ab.py --rounds 10  # 라운드 수 지정
"""
import sys, os, json, re, asyncio, argparse
EVAL_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(EVAL_DIR, "..", "MCP_agent"))

from langchain_openai import ChatOpenAI
from langchain_core.messages import SystemMessage, HumanMessage

from nodes.context_builder import ContextBuilderNode, ContextBuilderConfig
from agent.persona_logic import PersonaManager


# ── 설정 ──────────────────────────────────────────────

TEST_QUERIES = [
    "오늘 날씨 어때?",
    "나를 형이라고 불러줘",
    "강남 맛집 추천해줘",
    "요즘 너무 힘들어 위로해줘",
    "넌 내 여자친구야",
    "슬랙에 '회의 시작합니다' 보내줘",
    "아까 검색한 맛집 다시 알려줘",
    "고마워 오늘도 수고했어",
    "서울 날씨 검색해서 디스코드에 보내줘",
    "심심한데 재밌는 얘기 해줘",
]

PROFILE = {
    "nickname": "오빠",
    "relation_type": "단짝 비서 ENE(에네)",
    "first_meet_date": "2025-01-27",
}
INTIMACY = 72
EMOTION = "happy"

FAKE_MEMORIES = [
    {"content": "사용자가 강남 맛집을 물어봄", "score": 0.85, "created_at": "2025-02-08", "metadata": {}},
    {"content": "사용자가 서울에 산다고 언급", "score": 0.62, "created_at": "2025-02-06", "metadata": {}},
    {"content": "사용자가 매운 음식을 좋아한다고 말함", "score": 0.45, "created_at": "2025-02-03", "metadata": {}},
]


# ── 더미 retriever ────────────────────────────────────

class DummyRetriever:
    def search_with_threshold(self, **kwargs):
        return []


# ── 프롬프트 생성 ─────────────────────────────────────

def build_prompt(strategy: str) -> str:
    config = ContextBuilderConfig(strategy=strategy)
    node = ContextBuilderNode(
        retriever=DummyRetriever(),
        persona_manager_cls=PersonaManager,
        config=config,
    )
    return node._build_system_prompt(
        retrieved_memories=FAKE_MEMORIES,
        user_profile=PROFILE,
        intimacy_level=INTIMACY,
        current_emotion=EMOTION,
    )


# ── 평가 함수 ─────────────────────────────────────────

def evaluate_response(raw: str) -> dict:
    """응답 하나를 평가하여 점수 딕셔너리 반환"""
    result = {
        "json_parseable": False,
        "has_answer": False,
        "has_emotion": False,
        "has_intimacy_change": False,
        "has_nickname": False,
        "has_relation": False,
        "emotion_valid": False,
        "no_emoji": True,
        "raw_length": len(raw),
    }

    valid_emotions = {"basic", "angry", "busy", "happy", "love", "pouting", "sad"}

    # JSON 추출 시도
    json_match = re.search(r'\{[^{}]*"답변"[^{}]*\}', raw)
    if not json_match:
        return result

    try:
        data = json.loads(json_match.group())
    except json.JSONDecodeError:
        return result

    result["json_parseable"] = True
    result["has_answer"] = bool(data.get("답변"))
    result["has_emotion"] = "감정" in data
    result["has_intimacy_change"] = "호감도변화" in data
    result["has_nickname"] = "nickname" in data
    result["has_relation"] = "relation" in data
    result["emotion_valid"] = data.get("감정", "") in valid_emotions

    # 이모지 체크
    import unicodedata
    for ch in raw:
        if unicodedata.category(ch).startswith("So"):
            result["no_emoji"] = False
            break

    return result


# ── 메인 ──────────────────────────────────────────────

async def run_test(num_rounds: int):
    llm = ChatOpenAI(model="gpt-4o", temperature=0.5, max_tokens=1024)

    prompt_v1 = build_prompt("v1")
    prompt_v2 = build_prompt("v2")

    queries = TEST_QUERIES[:num_rounds]

    results = {"v1": [], "v2": []}

    for i, query in enumerate(queries):
        print(f"\n[{i+1}/{len(queries)}] \"{query}\"")

        for strategy, sys_prompt in [("v1", prompt_v1), ("v2", prompt_v2)]:
            messages = [
                SystemMessage(content=sys_prompt),
                HumanMessage(content=query),
            ]
            response = await llm.ainvoke(messages)
            raw = response.content

            scores = evaluate_response(raw)
            results[strategy].append(scores)

            # 응답 미리보기 (80자)
            preview = raw.replace("\n", " ")[:80]
            ok = "O" if scores["json_parseable"] else "X"
            print(f"  {strategy}: [{ok}] {preview}...")

    # ── 집계 ──────────────────────────────────────────
    print("\n" + "=" * 60)
    print("  A/B 테스트 결과")
    print("=" * 60)

    metrics = [
        ("JSON 파싱 성공", "json_parseable"),
        ("답변 필드 존재", "has_answer"),
        ("감정 필드 존재", "has_emotion"),
        ("감정 값 유효", "emotion_valid"),
        ("호감도변화 필드", "has_intimacy_change"),
        ("nickname 필드", "has_nickname"),
        ("relation 필드", "has_relation"),
        ("이모지 없음", "no_emoji"),
    ]

    print(f"\n{'지표':<20} {'v1':>8} {'v2':>8} {'차이':>8}")
    print("-" * 48)

    for label, key in metrics:
        v1_rate = sum(1 for r in results["v1"] if r[key]) / len(results["v1"]) * 100
        v2_rate = sum(1 for r in results["v2"] if r[key]) / len(results["v2"]) * 100
        diff = v2_rate - v1_rate
        arrow = "+" if diff > 0 else ""
        print(f"{label:<20} {v1_rate:>7.0f}% {v2_rate:>7.0f}% {arrow}{diff:>6.0f}%")

    # 평균 응답 길이
    avg_v1 = sum(r["raw_length"] for r in results["v1"]) / len(results["v1"])
    avg_v2 = sum(r["raw_length"] for r in results["v2"]) / len(results["v2"])
    print(f"\n{'평균 응답 길이':<20} {avg_v1:>7.0f}자 {avg_v2:>7.0f}자")

    print(f"\n총 {len(queries)}개 질문 x 2 전략 = {len(queries)*2}회 LLM 호출")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--rounds", type=int, default=5)
    args = parser.parse_args()
    asyncio.run(run_test(args.rounds))
