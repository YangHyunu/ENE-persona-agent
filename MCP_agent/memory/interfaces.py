"""
memory/interfaces.py - 메모리 시스템 인터페이스 정의

책임 분리 원칙(SRP)에 따른 인터페이스:
- MemoryRetriever: 검색만
- MemoryRepository: 저장/삭제만
- TextSummarizer: 요약만
- WindowTrimmer: 슬라이딩 윈도우만
"""

from abc import ABC, abstractmethod
from typing import List, Dict, Any, Tuple, Optional
from dataclasses import dataclass
from datetime import datetime


@dataclass
class MemoryDocument:
    """메모리 문서 데이터 클래스"""
    content: str
    metadata: Dict[str, Any]
    id: Optional[str] = None
    score: Optional[float] = None

    @property
    def created_at(self) -> Optional[str]:
        return self.metadata.get("created_at")

    @property
    def user_id(self) -> Optional[str]:
        return self.metadata.get("user_id")


class MemoryRetriever(ABC):
    """
    메모리 검색 인터페이스

    책임: 벡터 유사도 검색만 수행
    """

    @abstractmethod
    def search(
        self,
        query: str,
        k: int = 5,
        filter: Optional[Dict[str, Any]] = None
    ) -> List[MemoryDocument]:
        """
        유사도 검색

        Args:
            query: 검색 쿼리
            k: 반환할 문서 수
            filter: 메타데이터 필터 (예: {"user_id": "user_123"})

        Returns:
            점수가 포함된 MemoryDocument 리스트 (높은 점수순)
        """
        pass

    @abstractmethod
    def search_with_threshold(
        self,
        query: str,
        k: int = 5,
        threshold: float = 0.3,
        filter: Optional[Dict[str, Any]] = None
    ) -> List[MemoryDocument]:
        """
        임계값 기반 유사도 검색

        Args:
            query: 검색 쿼리
            k: 최대 반환 문서 수
            threshold: 최소 유사도 점수 (0-1)
            filter: 메타데이터 필터

        Returns:
            임계값 이상인 MemoryDocument 리스트
        """
        pass


class MemoryRepository(ABC):
    """
    메모리 저장소 인터페이스

    책임: 문서 저장/삭제만 수행
    """

    @abstractmethod
    def add(
        self,
        content: str,
        metadata: Optional[Dict[str, Any]] = None
    ) -> str:
        """
        문서 추가

        Args:
            content: 문서 내용
            metadata: 메타데이터 (user_id, created_at 등)

        Returns:
            생성된 문서 ID
        """
        pass

    @abstractmethod
    def add_batch(
        self,
        documents: List[Tuple[str, Dict[str, Any]]]
    ) -> List[str]:
        """
        여러 문서 일괄 추가

        Args:
            documents: (content, metadata) 튜플 리스트

        Returns:
            생성된 문서 ID 리스트
        """
        pass

    @abstractmethod
    def delete(self, doc_id: str) -> bool:
        """
        문서 삭제

        Args:
            doc_id: 삭제할 문서 ID

        Returns:
            삭제 성공 여부
        """
        pass

    @abstractmethod
    def clear(self, filter: Optional[Dict[str, Any]] = None) -> int:
        """
        문서 전체 삭제 또는 필터 기반 삭제

        Args:
            filter: 삭제할 문서 필터 (None이면 전체 삭제)

        Returns:
            삭제된 문서 수
        """
        pass


class TextSummarizer(ABC):
    """
    텍스트 요약 인터페이스

    책임: 텍스트 요약만 수행
    """

    @abstractmethod
    def summarize(self, text: str) -> str:
        """
        텍스트 요약

        Args:
            text: 요약할 텍스트

        Returns:
            요약된 텍스트
        """
        pass

    @abstractmethod
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
        pass


class WindowTrimmer(ABC):
    """
    슬라이딩 윈도우 인터페이스

    책임: 메시지 토큰 관리 (트리밍)만 수행
    """

    @abstractmethod
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
        pass

    @abstractmethod
    def estimate_tokens(self, messages: List[Dict[str, str]]) -> int:
        """
        토큰 수 추정

        Args:
            messages: 메시지 리스트

        Returns:
            추정 토큰 수
        """
        pass


# ============================================================
# 팩토리 인터페이스 (의존성 주입용)
# ============================================================

class MemorySystemFactory(ABC):
    """
    메모리 시스템 컴포넌트 팩토리

    모든 컴포넌트를 일관되게 생성
    """

    @abstractmethod
    def create_retriever(self) -> MemoryRetriever:
        """Retriever 생성"""
        pass

    @abstractmethod
    def create_repository(self) -> MemoryRepository:
        """Repository 생성"""
        pass

    @abstractmethod
    def create_summarizer(self) -> TextSummarizer:
        """Summarizer 생성"""
        pass

    @abstractmethod
    def create_window_trimmer(self) -> WindowTrimmer:
        """WindowTrimmer 생성"""
        pass
