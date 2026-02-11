"""
memory/clova_adapters.py - Clova Studio API 어댑터

기존 executor들을 인터페이스에 맞게 래핑:
- ClovaSummarizer: SummarizationExecutor 래핑
- ClovaWindowTrimmer: SlidingWindowExecutor 래핑
"""

import sys
import os
from typing import List, Dict, Optional

# 상위 디렉토리의 executor 임포트를 위해 MCP_agent 디렉토리를 path에 추가
_MCP_AGENT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _MCP_AGENT_DIR not in sys.path:
    sys.path.insert(0, _MCP_AGENT_DIR)

from memory.interfaces import TextSummarizer, WindowTrimmer


class ClovaSummarizer(TextSummarizer):
    """
    Clova 요약 API 어댑터

    기존 SummarizationExecutor를 TextSummarizer 인터페이스로 래핑
    엔드포인트: /v1/api-tools/summarization/v2
    """

    def __init__(
        self,
        api_key: str,
        request_id: str,
        host: str = 'clovastudio.stream.ntruss.com'
    ):
        """
        Args:
            api_key: Clova Studio API 키
            request_id: 요청 ID
            host: API 호스트
        """
        from utils.summary_executor import SummarizationExecutor

        self._executor = SummarizationExecutor(
            host=host,
            api_key=api_key,
            request_id=request_id
        )
        self._default_config = {
            "autoSentenceSplitter": True,
            "segCount": -1,
            "segMaxSize": 1000,
            "segMinSize": 300,
            "includeAiFilters": False
        }

    def summarize(self, text: str) -> str:
        """
        텍스트 요약

        Args:
            text: 요약할 텍스트

        Returns:
            요약된 텍스트

        Raises:
            ValueError: API 오류 발생 시
        """
        if not text or not text.strip():
            return ""

        request = {
            "texts": [text],
            **self._default_config
        }

        try:
            result = self._executor.execute(request)
            return result if isinstance(result, str) else str(result)
        except Exception:
            # 폴백: 원본의 앞부분 반환
            return text[:500] + "..." if len(text) > 500 else text

    def summarize_conversation(
        self,
        messages: List[Dict[str, str]]
    ) -> str:
        """
        대화 요약

        Args:
            messages: [{"role": "user", "content": "..."}, ...] 형식

        Returns:
            요약된 대화 내용
        """
        # 대화를 텍스트로 변환
        lines = []
        for msg in messages:
            role = msg.get("role", "user")
            content = msg.get("content", "")

            if role == "system":
                continue

            role_label = "사용자" if role == "user" else "AI"
            lines.append(f"{role_label}: {content}")

        conversation_text = " ".join(lines)
        return self.summarize(conversation_text)


class ClovaWindowTrimmer(WindowTrimmer):
    """
    Clova 슬라이딩 윈도우 API 어댑터

    기존 SlidingWindowExecutor를 WindowTrimmer 인터페이스로 래핑
    엔드포인트: /v1/api-tools/sliding/chat-messages/{modelName}
    """

    def __init__(
        self,
        api_key: str,
        request_id: str,
        host: str = 'clovastudio.stream.ntruss.com',
        model_name: str = 'HCX-003'
    ):
        """
        Args:
            api_key: Clova Studio API 키
            request_id: 요청 ID
            host: API 호스트
            model_name: 사용할 모델 (HCX-003 등)
        """
        from utils.sliding_window_executor import SlidingWindowExecutor

        self._executor = SlidingWindowExecutor(
            host=host,
            api_key=api_key,
            request_id=request_id
        )
        self._model_name = model_name
        self._chars_per_token = 1.5  # 한글 기준

    def trim(
        self,
        messages: List[Dict[str, str]],
        max_tokens: int = 1000
    ) -> List[Dict[str, str]]:
        """
        메시지 트리밍

        Args:
            messages: [{"role": "user", "content": "..."}, ...] 형식
            max_tokens: 최대 토큰 수

        Returns:
            트리밍된 메시지 리스트
        """
        if not messages:
            return []

        # 시스템 메시지 확인 및 추가
        formatted = self._ensure_system_message(messages)

        request = {
            "modelName": self._model_name,
            "messages": formatted,
            "maxTokens": max_tokens
        }

        try:
            result = self._executor.execute(request)

            if result == 'Error':
                return messages

            return result if isinstance(result, list) else messages

        except Exception:
            return messages

    def estimate_tokens(self, messages: List[Dict[str, str]]) -> int:
        """
        토큰 수 추정 (로컬 계산)

        Args:
            messages: 메시지 리스트

        Returns:
            추정 토큰 수
        """
        total_chars = sum(
            len(msg.get("content", ""))
            for msg in messages
        )
        return int(total_chars / self._chars_per_token)

    def _ensure_system_message(
        self,
        messages: List[Dict[str, str]]
    ) -> List[Dict[str, str]]:
        """시스템 메시지가 없으면 추가"""
        if not messages:
            return [{"role": "system", "content": "System"}]

        if messages[0].get("role") != "system":
            return [{"role": "system", "content": "System"}] + messages

        return messages


# ============================================================
# 로컬 폴백 구현 (API 없이 동작)
# ============================================================

class LocalWindowTrimmer(WindowTrimmer):
    """
    로컬 슬라이딩 윈도우 (API 호출 없음)

    Clova API를 사용하지 않고 로컬에서 토큰 계산 및 트리밍
    테스트용 또는 API 비용 절감용
    """

    def __init__(
        self,
        chars_per_token: float = 1.5,
        keep_recent: int = 6
    ):
        """
        Args:
            chars_per_token: 토큰당 문자 수 (한글 기준 1.5)
            keep_recent: 최소 유지할 최근 메시지 수
        """
        self._chars_per_token = chars_per_token
        self._keep_recent = keep_recent

    def trim(
        self,
        messages: List[Dict[str, str]],
        max_tokens: int = 1000
    ) -> List[Dict[str, str]]:
        """로컬 트리밍"""
        if not messages:
            return []

        current_tokens = self.estimate_tokens(messages)

        if current_tokens <= max_tokens:
            return messages

        # 오래된 메시지부터 제거
        result = messages.copy()

        while (
            len(result) > self._keep_recent
            and self.estimate_tokens(result) > max_tokens
        ):
            # 시스템 메시지는 유지
            for i, msg in enumerate(result):
                if msg.get("role") != "system":
                    result.pop(i)
                    break

        return result

    def estimate_tokens(self, messages: List[Dict[str, str]]) -> int:
        """토큰 추정"""
        total_chars = sum(
            len(msg.get("content", ""))
            for msg in messages
        )
        return int(total_chars / self._chars_per_token)


class LocalSummarizer(TextSummarizer):
    """
    로컬 요약기 (API 호출 없음)

    단순 규칙 기반 요약 - 테스트용 또는 폴백용
    """

    def __init__(self, max_length: int = 300):
        self._max_length = max_length

    def summarize(self, text: str) -> str:
        """단순 잘라내기 기반 요약"""
        if len(text) <= self._max_length:
            return text

        # 문장 단위로 자르기
        sentences = text.replace(".", ".\n").split("\n")
        result = []
        current_length = 0

        for sentence in sentences:
            if current_length + len(sentence) > self._max_length:
                break
            result.append(sentence)
            current_length += len(sentence)

        return " ".join(result) + "..."

    def summarize_conversation(
        self,
        messages: List[Dict[str, str]]
    ) -> str:
        """대화 요약"""
        # 핵심 교환만 추출
        exchanges = []

        for i, msg in enumerate(messages):
            if msg.get("role") == "user":
                user_content = msg.get("content", "")[:100]

                # 다음 AI 응답 찾기
                for next_msg in messages[i+1:]:
                    if next_msg.get("role") == "assistant":
                        ai_content = next_msg.get("content", "")[:150]
                        exchanges.append(f"Q: {user_content}\nA: {ai_content}")
                        break

        return "\n---\n".join(exchanges[-3:])  # 최근 3개만
