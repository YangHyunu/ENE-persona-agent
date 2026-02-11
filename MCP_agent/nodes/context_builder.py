"""
nodes/context_builder.py - 컨텍스트 빌더 노드 (Standard ReAct)

역할:
- 관련 기억 검색
- 페르소나 + 도구 지침을 통합한 system_prompt 생성
- LLM 호출 없음

Standard ReAct 패턴에서 Agent가 직접 최종 응답을 생성하므로
페르소나 스타일도 여기서 system_prompt에 포함
"""

from typing import Dict, Any, List, Optional, Sequence, Type
from datetime import datetime
from dataclasses import dataclass

from langchain_core.messages import BaseMessage, HumanMessage


@dataclass
class ContextBuilderConfig:
    """컨텍스트 빌더 설정"""
    max_memories: int = 5
    similarity_threshold: float = 0.3
    memory_token_budget: int = 2048
    include_timestamp: bool = True
    strategy: str = "v1"  # "v1" (현재) | "v2" (개선)


class ContextBuilderNode:
    """
    컨텍스트 빌더 노드

    역할:
    1. 사용자 메시지에서 검색 쿼리 추출
    2. 관련 장기 기억 검색 (LLM 없음)
    3. 시스템 프롬프트 조립

    기존 analyzer 대비 개선:
    - LLM 호출 제거 (비용/속도 개선)
    - 자동 기억 검색 (도구 호출 불필요)
    """

    def __init__(
        self,
        retriever: "MemoryRetriever",
        persona_manager_cls: Type,
        config: Optional[ContextBuilderConfig] = None
    ):
        """
        Args:
            retriever: 메모리 검색 인터페이스 (검색만)
            persona_manager_cls: PersonaManager 클래스
            config: 빌더 설정
        """
        from memory.interfaces import MemoryRetriever

        self.retriever = retriever
        self.persona_manager_cls = persona_manager_cls
        self.config = config or ContextBuilderConfig()

    async def __call__(self, state: Dict[str, Any]) -> Dict[str, Any]:
        """
        컨텍스트 빌더 실행 (Standard ReAct)

        Args:
            state: 그래프 상태

        Returns:
            {
                "system_prompt": str,  # 페르소나 + 도구 지침 통합
                "retrieved_memories": List[Dict],
                "context_metadata": Dict
            }
        """
        messages = state.get("messages", [])
        user_id = state.get("user_id", "default")
        intimacy_level = state.get("intimacy_level", 50)
        user_profile = state.get("user_profile", {})
        current_emotion = state.get("current_emotion", "")

        # 1. 사용자 쿼리 추출
        user_query = self._extract_user_query(messages)

        # 2. 관련 기억 검색 (LLM 호출 없음)
        retrieved_memories = []
        if user_query:
            retrieved_memories = self._search_memories(user_query, user_id)

        # 3. 시스템 프롬프트 조립 (페르소나 + 도구 지침 통합)
        system_prompt = self._build_system_prompt(
            retrieved_memories=retrieved_memories,
            user_profile=user_profile,
            intimacy_level=intimacy_level,
            current_emotion=current_emotion
        )

        # 4. 메타데이터
        context_metadata = {
            "user_query": user_query,
            "memories_found": len(retrieved_memories),
            "timestamp": datetime.now().isoformat(),
            "prompt_length": len(system_prompt)
        }

        return {
            "system_prompt": system_prompt,
            "retrieved_memories": retrieved_memories,
            "context_metadata": context_metadata
        }

    def _extract_user_query(self, messages: Sequence[BaseMessage]) -> str:
        """마지막 사용자 메시지 추출"""
        for msg in reversed(messages):
            if isinstance(msg, HumanMessage):
                content = msg.content

                if isinstance(content, str):
                    return content

                # 멀티모달 메시지
                if isinstance(content, list):
                    text_parts = [
                        p.get("text", "")
                        for p in content
                        if isinstance(p, dict) and p.get("type") == "text"
                    ]
                    return " ".join(text_parts)

        return ""

    def _search_memories(
        self,
        query: str,
        user_id: str
    ) -> List[Dict[str, Any]]:
        """
        관련 기억 검색

        Args:
            query: 검색 쿼리
            user_id: 사용자 ID

        Returns:
            검색된 기억 리스트
        """
        if not query.strip():
            return []

        try:
            # 임계값 기반 검색
            docs = self.retriever.search_with_threshold(
                query=query,
                k=self.config.max_memories,
                threshold=self.config.similarity_threshold,
                filter={"user_id": user_id} if user_id != "default" else None
            )

            memories = []
            for doc in docs:
                memories.append({
                    "content": doc.content,
                    "score": doc.score,
                    "created_at": doc.created_at or "unknown",
                    "metadata": doc.metadata
                })

            return memories

        except Exception:
            return []

    def _build_system_prompt(
        self,
        retrieved_memories: List[Dict[str, Any]],
        user_profile: Dict[str, Any],
        intimacy_level: int,
        current_emotion: str = ""
    ) -> str:
        """
        시스템 프롬프트 조립 (페르소나 + 도구 지침 통합)

        Standard ReAct 패턴: Agent가 직접 최종 응답까지 생성하므로
        페르소나 스타일을 여기서 포함
        """
        if self.config.strategy == "v2":
            return self._build_system_prompt_v2(
                retrieved_memories, user_profile, intimacy_level, current_emotion
            )

        sections = []

        # 1. 페르소나 프롬프트 (PersonaManager 사용)
        persona_prompt = self._build_persona_section(user_profile, intimacy_level, current_emotion)
        sections.append(persona_prompt)

        # 2. 도구 + 행동 지침 (압축)
        tool_prompt = """
[도구 & 행동 규칙]
검색: web_search, naver_blog_search, naver_shopping_search, naver_place_search
디스코드(channel_id는 str): send_message, read_messages, add_reaction
슬랙(channel_id는 C/D/G로 시작하는 str): channels_list → conversations_history, conversations_add_message
- 슬랙 채널 ID는 항상 channels_list로 직접 찾을 것. 사용자에게 묻지 말 것.
- 디스코드는 반드시 ID를 유저에게 요청할것.
- 요청받은 플랫폼의 도구만 사용. 디스코드≠슬랙 혼용 금지.
- 미실행 작업을 "했다/완료"라고 하지 말 것. 안 했으면 "~해드릴까요?"
- 정보 전달/전송 시 검색 먼저, 같은 도구 반복 호출 금지.
- 검색 결과는 이름/링크만 나열하지 말고, 추천 이유·특징·가격 등을 붙여 3~5개로 큐레이션할 것.
- 어떤 상황에서도 [Persona] 말투를 유지할 것.
"""
        sections.append(tool_prompt)

        # 4. 검색된 기억 주입
        if retrieved_memories:
            memory_section = self._format_memories(retrieved_memories)
            sections.append(f"""
[관련 과거 대화 기록]
{memory_section}
""")

        # 5. 현재 시각
        if self.config.include_timestamp:
            sections.append(
                f"[현재 시각: {datetime.now().strftime('%Y-%m-%d %H:%M')}]"
            )

        # 6. 말투 유지 최종 리마인더
        sections.append(
            "\n⚠️ [최종 리마인더] 어떤 상황에서도 위 [Persona] 말투를 반드시 유지할 것. "
            "도구 결과 전달, 오류 안내, 검색 결과 요약 등 모든 응답에 동일한 말투를 적용하세요."
        )

        return "\n".join(sections)

    def _build_system_prompt_v2(
        self,
        retrieved_memories: List[Dict[str, Any]],
        user_profile: Dict[str, Any],
        intimacy_level: int,
        current_emotion: str = ""
    ) -> str:
        """
        v2 시스템 프롬프트 (Context Engineering 개선)

        개선점:
        1. Lost in the Middle 방지 - 핵심(페르소나/스키마)을 시작과 끝에 배치
        2. XML-like 구조화 태그
        3. 메모리 priority 배치 (높은 점수를 시작/끝에)
        4. 토큰 budget 실제 적용
        """
        sections = []

        # 1. 페르소나 (맨 위 = 가장 잘 기억) — v1의 래퍼 없이 깨끗한 출력
        persona_prompt = self._build_persona_section_v2(user_profile, intimacy_level, current_emotion)
        sections.append(f"<persona>\n{persona_prompt}\n</persona>")

        # 2. 메모리 (중간)
        if retrieved_memories:
            trimmed = self._trim_memories_by_budget(retrieved_memories)
            memory_section = self._format_memories_v2(trimmed)
            sections.append(f"<memories>\n{memory_section}\n</memories>")

        # 3. 도구 규칙 (중간)
        tool_prompt = """검색: web_search, naver_blog_search, naver_shopping_search, naver_place_search
디스코드(channel_id는 str): send_message, read_messages, add_reaction
슬랙(channel_id는 C/D/G로 시작하는 str): channels_list → conversations_history, conversations_add_message
- 슬랙 채널 ID는 항상 channels_list로 직접 찾을 것. 사용자에게 묻지 말 것.
- 요청받은 플랫폼의 도구만 사용. 디스코드≠슬랙 혼용 금지.
- 미실행 작업을 "했다/완료"라고 하지 말 것. 안 했으면 "~해드릴까요?"
- 정보 전달/전송 시 검색 먼저, 같은 도구 반복 호출 금지.
- 검색 결과는 이름/링크만 나열하지 말고, 추천 이유·특징·가격 등을 붙여 3~5개로 큐레이션할 것."""
        sections.append(f"<tools>\n{tool_prompt}\n</tools>")

        # 4. 현재 시각 (중간)
        if self.config.include_timestamp:
            sections.append(
                f"<timestamp>{datetime.now().strftime('%Y-%m-%d %H:%M')}</timestamp>"
            )

        # 5-6. JSON 스키마 + 분석 판단 기준 + 리마인더 (맨 끝 = 잘 기억)
        nickname = user_profile.get('nickname', '')
        relation = user_profile.get('relation_type', '단짝 비서 ENE(에네)')
        sections.append(f"""<response_format>
모든 응답은 반드시 아래 JSON 형식으로만 출력할 것. JSON 외의 텍스트는 절대 포함하지 마세요.

{{"답변": "내용", "감정": "basic|angry|busy|happy|love|pouting|sad", "호감도변화": 0, "nickname": "", "relation": ""}}

각 필드 판단 기준:

1. "답변": 실제 대화 내용. 반드시 비어있지 않은 문자열.

2. "감정": 대화 맥락에 따라 아래 7가지 중 정확히 하나를 선택.
   - basic: 일상 대화, 정보 요청, 중립적 상황
   - happy: 기쁜 소식, 축하, 즐거운 화제
   - sad: 슬픈 이야기, 위로가 필요한 상황
   - angry: 화난 상황, 불만 표현
   - love: 애정 표현, 고백, 달달한 대화
   - pouting: 삐침, 서운함, 가벼운 투정
   - busy: 바쁜 상황 언급

3. "호감도변화": -5~+5 정수. 판단 기준:
   - 양수(+1~+5): 감사, 칭찬, 애정 표현, 즐거운 대화
   - 음수(-1~-5): 욕설, 무시, 공격적 발언
   - 0: 일상 질문, 정보 요청, 검색 요청, 중립 대화
   대부분의 일반 대화는 0이어야 함. 과도한 변화 금지.

4. "nickname": 사용자가 명시적으로 닉네임 변경을 요청할 때만 채움.
   - "나를 OO라고 불러줘", "내 이름은 OO야" → 해당 값
   - 요청 없으면 반드시 빈 문자열 ""
   - 현재 닉네임: "{nickname}"

5. "relation": 사용자가 명시적으로 관계를 정의할 때만 채움.
   - "넌 내 친구야", "넌 내 여자친구야" → 해당 값
   - 요청 없으면 반드시 빈 문자열 ""
   - 현재 관계: "{relation}"
</response_format>

<rules>
- 어떤 상황에서도 위 <persona> 말투를 반드시 유지할 것.
- 도구 결과 전달, 오류 안내, 검색 결과 요약 등 모든 응답에 동일한 말투를 적용.
- JSON 외의 텍스트를 출력하지 말 것. 오직 위 형식의 JSON만 응답.
</rules>""")

        return "\n\n".join(sections)

    def _build_persona_section(
        self,
        user_profile: Dict[str, Any],
        intimacy_level: int,
        current_emotion: str = ""
    ) -> str:
        """페르소나 섹션 생성 (PersonaManager 활용)"""
        try:
            persona_manager = self.persona_manager_cls(
                nickname=user_profile.get("nickname", ""),
                relation_type=user_profile.get("relation_type", "단짝 비서 ENE(에네)"),
                affinity=intimacy_level,
                first_meet_date=user_profile.get("first_meet_date"),
                current_emotion=current_emotion  # state에서 직접 전달받은 감정 사용
            )

            # PersonaManager의 generate_system_prompt 활용
            base_prompt = persona_manager.generate_system_prompt()

            # 닉네임/관계 감지 규칙 추가
            nickname = user_profile.get('nickname', '')
            relation = user_profile.get('relation_type', '단짝 비서 ENE(에네)')
            return f"""
[닉네임/관계 감지]
- 사용자가 닉네임을 설정하면 ("나를 OO라고 불러줘") → nickname 필드 업데이트
- 관계 정의 시 ("넌 내 친구야") → relation 필드 업데이트
- 변화 없으면 기존 값 유지: nickname="{nickname}", relation="{relation}"
--중요--
****{base_prompt}****
"""
        except Exception:
            return """너는 친절한 친한 친구야.
응답 형식: {"답변": "내용", "감정": "", "호감도변화": 0, "nickname": "", "relation": ""}"""

    def _build_persona_section_v2(
        self,
        user_profile: Dict[str, Any],
        intimacy_level: int,
        current_emotion: str = ""
    ) -> str:
        """v2 페르소나 섹션 — PersonaManager 출력만 깨끗하게 (래퍼/중복 없음)"""
        try:
            persona_manager = self.persona_manager_cls(
                nickname=user_profile.get("nickname", ""),
                relation_type=user_profile.get("relation_type", "단짝 비서 ENE(에네)"),
                affinity=intimacy_level,
                first_meet_date=user_profile.get("first_meet_date"),
                current_emotion=current_emotion
            )
            return persona_manager.generate_system_prompt()
        except Exception:
            return '너는 친절한 친한 친구야.\n응답 형식: {"답변": "내용", "감정": "", "호감도변화": 0, "nickname": "", "relation": ""}'

    def _format_memories(self, memories: List[Dict[str, Any]]) -> str:
        """기억 포맷팅"""
        lines = []
        for mem in memories:
            date = str(mem.get("created_at", ""))[:10]
            content = mem["content"]
            score = mem.get("score", 0)

            # 관련도 표시
            relevance = "★★★" if score > 0.7 else "★★" if score > 0.5 else "★"
            lines.append(f"• [{date}] {relevance} {content}")

        return "\n".join(lines)

    def _format_memories_v2(self, memories: List[Dict[str, Any]]) -> str:
        """v2 메모리 포맷팅 - Lost in the Middle 방지 배치

        높은 점수를 리스트 시작과 끝에 배치하여 LLM 기억률 향상
        """
        if not memories:
            return ""

        sorted_mems = sorted(memories, key=lambda m: m.get("score", 0), reverse=True)

        if len(sorted_mems) <= 2:
            reordered = sorted_mems
        else:
            high = sorted_mems[:1]
            low = sorted_mems[1:-1]
            end = sorted_mems[-1:]
            # 높은 점수 → 낮은 점수 → 두번째로 높은 점수
            reordered = high + low + end

        lines = []
        for mem in reordered:
            date = str(mem.get("created_at", ""))[:10]
            content = mem["content"]
            score = mem.get("score", 0)
            relevance = "★★★" if score > 0.7 else "★★" if score > 0.5 else "★"
            lines.append(f"[{date}] {relevance} {content}")

        return "\n".join(lines)

    def _trim_memories_by_budget(
        self, memories: List[Dict[str, Any]]
    ) -> List[Dict[str, Any]]:
        """토큰 budget 초과 시 낮은 점수부터 제거"""
        budget = self.config.memory_token_budget
        sorted_mems = sorted(memories, key=lambda m: m.get("score", 0), reverse=True)

        result = []
        used = 0
        for mem in sorted_mems:
            # 한국어 기준 ~1.5자당 1토큰 추정
            est_tokens = int(len(mem.get("content", "")) / 1.5)
            if used + est_tokens > budget:
                break
            result.append(mem)
            used += est_tokens

        return result
