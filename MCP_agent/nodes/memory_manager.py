"""
nodes/memory_manager.py - 통합 메모리 관리 노드

슬라이딩 윈도우 + 요약 + 아카이브를 통합:
- Clova Sliding API로 토큰 관리
- Clova Summary API로 제거된 메시지 요약
- ChromaDB로 요약본 저장
"""

from typing import Dict, Any, List, Optional
from datetime import datetime
from dataclasses import dataclass

from langchain_core.messages import (
    BaseMessage,
    HumanMessage,
    AIMessage,
    SystemMessage,
    ToolMessage,
    RemoveMessage
)


@dataclass
class MemoryManagerConfig:
    """메모리 관리 설정"""
    token_threshold: int = 2000
    max_tokens_after_trim: int = 1000
    chars_per_token: float = 1.5
    archive_removed: bool = True


class MemoryManagerNode:
    """
    통합 메모리 관리 노드

    Clova API 활용:
    1. WindowTrimmer: 슬라이딩 윈도우 (토큰 관리)
    2. Summarizer: 제거된 메시지 요약
    3. Repository: 요약본 저장

    기존 memory_management_node 대비 개선:
    - 인터페이스 기반 (테스트 용이)
    - 책임 분리 (각 컴포넌트 교체 가능)
    """

    def __init__(
        self,
        window_trimmer: "WindowTrimmer",
        summarizer: "TextSummarizer",
        repository: "MemoryRepository",
        config: Optional[MemoryManagerConfig] = None
    ):
        """
        Args:
            window_trimmer: 슬라이딩 윈도우 인터페이스
            summarizer: 요약 인터페이스
            repository: 저장소 인터페이스
            config: 관리 설정
        """
        self.window_trimmer = window_trimmer
        self.summarizer = summarizer
        self.repository = repository
        self.config = config or MemoryManagerConfig()

    async def __call__(self, state: Dict[str, Any]) -> Dict[str, Any]:
        """
        메모리 관리 실행

        Args:
            state: 그래프 상태

        Returns:
            {"messages": [RemoveMessage, ...]} 또는 {}
        """
        messages = state.get("messages", [])
        user_id = state.get("user_id", "default")

        # 0. 도구 실행 중간 메시지 정리 (항상 실행 - 컨텍스트 오염 방지)
        tool_cleanup_ops = self._cleanup_tool_messages(messages)

        # 1. 토큰 추정
        estimated_tokens = self._estimate_tokens(messages)

        if estimated_tokens < self.config.token_threshold:
            # 토큰 임계값 미만이어도 도구 정리는 수행
            if tool_cleanup_ops:
                return {"messages": tool_cleanup_ops}
            return {}

        # 2. 메시지 포맷 변환
        formatted = self._to_api_format(messages)

        # 3. 슬라이딩 윈도우 API 호출
        trimmed = self.window_trimmer.trim(
            formatted,
            self.config.max_tokens_after_trim
        )

        # 4. 제거된 메시지 식별
        removed_messages = self._identify_removed(messages, trimmed)

        if not removed_messages:
            # 슬라이딩 윈도우에서 제거할 메시지가 없어도 도구 정리 결과는 반환
            if tool_cleanup_ops:
                return {"messages": tool_cleanup_ops}
            return {}

        # 5. 제거된 메시지 요약 및 저장
        if self.config.archive_removed:
            await self._archive_messages(removed_messages, user_id)

        # 6. RemoveMessage 반환
        remove_ops = [
            RemoveMessage(id=m.id)
            for m in removed_messages
            if m.id
        ]

        # 도구 정리 결과와 슬라이딩 윈도우 결과 병합
        all_remove_ops = tool_cleanup_ops + remove_ops
        return {"messages": all_remove_ops}

    def _cleanup_tool_messages(self, messages: List[BaseMessage]) -> List[RemoveMessage]:
        """
        도구 실행 중간 메시지 정리

        제거 대상:
        1. ToolMessage (도구 실행 결과)
        2. tool_calls가 있는 AIMessage (도구 호출 요청)

        이유:
        - 다음 턴에서 LLM이 이전 도구 결과를 보고 "이미 처리됨"으로 판단하는 것 방지
        - 컨텍스트 오염 방지
        """
        remove_ops = []

        for msg in messages:
            # ToolMessage 제거
            if isinstance(msg, ToolMessage):
                if msg.id:
                    remove_ops.append(RemoveMessage(id=msg.id))

            # tool_calls가 있는 AIMessage 제거
            elif isinstance(msg, AIMessage):
                if getattr(msg, 'tool_calls', None) and msg.id:
                    remove_ops.append(RemoveMessage(id=msg.id))

        return remove_ops

    def _estimate_tokens(self, messages: List[BaseMessage]) -> int:
        """토큰 추정 (로컬)"""
        total_chars = sum(
            len(str(m.content))
            for m in messages
            if isinstance(m.content, str)
        )
        return int(total_chars / self.config.chars_per_token)

    def _to_api_format(self, messages: List[BaseMessage]) -> List[Dict[str, str]]:
        """LangChain 메시지 → API 포맷"""
        formatted = []

        for m in messages:
            if isinstance(m, ToolMessage):
                continue

            role = "user"
            if isinstance(m, AIMessage):
                role = "assistant"
            elif isinstance(m, SystemMessage):
                role = "system"

            formatted.append({
                "role": role,
                "content": str(m.content)
            })

        # 첫 메시지가 system이 아니면 추가
        if formatted and formatted[0]["role"] != "system":
            formatted.insert(0, {"role": "system", "content": "System"})

        return formatted

    def _identify_removed(
        self,
        original: List[BaseMessage],
        trimmed: List[Dict[str, str]]
    ) -> List[BaseMessage]:
        """제거된 메시지 식별"""
        # 트리밍된 메시지 내용 집합
        trimmed_contents = {
            m["content"]
            for m in trimmed
            if m["role"] != "system"
        }

        # 원본에서 트리밍 결과에 없는 메시지 찾기
        removed = []
        for m in original:
            if isinstance(m, (HumanMessage, AIMessage)):
                content = str(m.content)
                if content not in trimmed_contents:
                    removed.append(m)

        return removed

    async def _archive_messages(
        self,
        messages: List[BaseMessage],
        user_id: str
    ):
        """제거된 메시지 요약 및 저장"""
        if not messages:
            return

        # 1. 대화 포맷팅
        text_to_summarize = self._format_for_summary(messages)

        # 2. 요약 (Clova Summary API)
        try:
            summary = self.summarizer.summarize(text_to_summarize)
        except Exception:
            # 폴백: 원본의 일부만 저장
            summary = text_to_summarize[:500]

        # 3. 저장 (ChromaDB)
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        self.repository.add(
            content=f"[{timestamp}] 아카이브:\n{summary}",
            metadata={
                "user_id": user_id,
                "type": "conversation_archive",
                "message_count": len(messages),
                "created_at": timestamp
            }
        )

    def _format_for_summary(self, messages: List[BaseMessage]) -> str:
        """요약용 텍스트 포맷"""
        lines = []
        for m in messages:
            if isinstance(m, HumanMessage):
                lines.append(f"User: {m.content}")
            elif isinstance(m, AIMessage):
                lines.append(f"AI: {m.content}")

        return " ".join(lines)


# ============================================================
# 동기 버전 (필요 시)
# ============================================================

class SyncMemoryManagerNode(MemoryManagerNode):
    """동기 버전 메모리 관리 노드"""

    def __call__(self, state: Dict[str, Any]) -> Dict[str, Any]:
        """동기 실행"""
        import asyncio

        # 이벤트 루프가 있으면 사용, 없으면 새로 생성
        try:
            loop = asyncio.get_event_loop()
            if loop.is_running():
                # 이미 실행 중인 루프에서는 직접 호출
                return self._sync_call(state)
            else:
                return loop.run_until_complete(
                    super().__call__(state)
                )
        except RuntimeError:
            return asyncio.run(super().__call__(state))

    def _sync_call(self, state: Dict[str, Any]) -> Dict[str, Any]:
        """동기 내부 호출"""
        messages = state.get("messages", [])
        user_id = state.get("user_id", "default")

        estimated_tokens = self._estimate_tokens(messages)

        if estimated_tokens < self.config.token_threshold:
            return {}

        formatted = self._to_api_format(messages)
        trimmed = self.window_trimmer.trim(
            formatted,
            self.config.max_tokens_after_trim
        )

        removed_messages = self._identify_removed(messages, trimmed)

        if not removed_messages:
            return {}

        if self.config.archive_removed:
            self._sync_archive_messages(removed_messages, user_id)

        remove_ops = [
            RemoveMessage(id=m.id)
            for m in removed_messages
            if m.id
        ]

        return {"messages": remove_ops}

    def _sync_archive_messages(
        self,
        messages: List[BaseMessage],
        user_id: str
    ):
        """동기 아카이브"""
        if not messages:
            return

        text_to_summarize = self._format_for_summary(messages)

        try:
            summary = self.summarizer.summarize(text_to_summarize)
        except Exception:
            summary = text_to_summarize[:500]

        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        self.repository.add(
            content=f"[{timestamp}] 아카이브:\n{summary}",
            metadata={
                "user_id": user_id,
                "type": "conversation_archive",
                "message_count": len(messages),
                "created_at": timestamp
            }
        )
