"""
nodes - LangGraph 노드 모듈

개선된 그래프 노드:
- ContextBuilderNode: 기억 검색 + 프롬프트 조립 (LLM 없음)
- AnalyzerNode: 감정/호감도 분석 (LLM 사용)
- MemoryManagerNode: 슬라이딩 윈도우 + 요약 + 저장
"""

from nodes.context_builder import (
    ContextBuilderNode,
    ContextBuilderConfig
)

from nodes.analyzer import (
    AnalyzerNode,
    AnalyzerConfig,
    create_analyzer_node
)

from nodes.memory_manager import (
    MemoryManagerNode,
    MemoryManagerConfig,
    SyncMemoryManagerNode
)

__all__ = [
    # Context Builder
    "ContextBuilderNode",
    "ContextBuilderConfig",
    # Analyzer
    "AnalyzerNode",
    "AnalyzerConfig",
    "create_analyzer_node",
    # Memory Manager
    "MemoryManagerNode",
    "MemoryManagerConfig",
    "SyncMemoryManagerNode",
]
