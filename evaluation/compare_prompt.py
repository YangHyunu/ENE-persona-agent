"""v1 vs v2 시스템 프롬프트 비교 스크립트"""
import sys, os
EVAL_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(EVAL_DIR, "..", "MCP_agent"))

from nodes.context_builder import ContextBuilderNode, ContextBuilderConfig
from agent.persona_logic import PersonaManager

# 더미 retriever (메모리 검색 없이 테스트)
class DummyRetriever:
    def search_with_threshold(self, **kwargs):
        return []

# 테스트 데이터
profile = {"nickname": "오빠", "relation_type": "단짝 비서 ENE(에네)", "first_meet_date": "2025-01-27"}
fake_memories = [
    {"content": "사용자가 강남 맛집을 물어봄", "score": 0.85, "created_at": "2025-02-08", "metadata": {}},
    {"content": "사용자가 서울에 산다고 언급", "score": 0.62, "created_at": "2025-02-06", "metadata": {}},
    {"content": "사용자가 매운 음식을 좋아한다고 말함", "score": 0.45, "created_at": "2025-02-03", "metadata": {}},
]

for strategy in ["v1", "v2"]:
    config = ContextBuilderConfig(strategy=strategy)
    node = ContextBuilderNode(retriever=DummyRetriever(), persona_manager_cls=PersonaManager, config=config)

    prompt = node._build_system_prompt(
        retrieved_memories=fake_memories,
        user_profile=profile,
        intimacy_level=72,
        current_emotion="happy"
    )

    print(f"\n{'='*60}")
    print(f"  STRATEGY: {strategy}  |  길이: {len(prompt)}자  |  ~{int(len(prompt)/1.5)} 토큰")
    print(f"{'='*60}")
    print(prompt)
    print()
