"""
memory - 메모리 시스템 모듈

책임 분리된 메모리 관리 컴포넌트:
- interfaces: 추상 인터페이스 정의
- clova_adapters: Clova Studio API 어댑터
- chroma_adapters: ChromaDB 구현체
"""

from memory.interfaces import (
    MemoryDocument,
    MemoryRetriever,
    MemoryRepository,
    TextSummarizer,
    WindowTrimmer,
    MemorySystemFactory
)

from memory.chroma_adapters import (
    ChromaRetriever,
    ChromaRepository,
    ChromaMemoryFactory,
    create_memory_system
)

from memory.clova_adapters import (
    ClovaSummarizer,
    ClovaWindowTrimmer,
    LocalSummarizer,
    LocalWindowTrimmer
)

__all__ = [
    # Interfaces
    "MemoryDocument",
    "MemoryRetriever",
    "MemoryRepository",
    "TextSummarizer",
    "WindowTrimmer",
    "MemorySystemFactory",
    # Chroma
    "ChromaRetriever",
    "ChromaRepository",
    "ChromaMemoryFactory",
    "create_memory_system",
    # Clova
    "ClovaSummarizer",
    "ClovaWindowTrimmer",
    # Local fallbacks
    "LocalSummarizer",
    "LocalWindowTrimmer",
]
