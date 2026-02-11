"""
memory/chroma_adapters.py - ChromaDB 어댑터

기존 LangChainRAGExecutor의 vectorstore를 분리하여 구현:
- ChromaRetriever: 검색 전용
- ChromaRepository: 저장/삭제 전용
"""

import os
import uuid
import time
from typing import List, Dict, Any, Tuple, Optional

from memory.interfaces import (
    MemoryRetriever,
    MemoryRepository,
    MemoryDocument,
    MemorySystemFactory,
    TextSummarizer,
    WindowTrimmer
)


class ChromaRetriever(MemoryRetriever):
    """
    ChromaDB 기반 메모리 검색

    책임: 벡터 유사도 검색만 수행
    """

    def __init__(
        self,
        vectorstore,  # Chroma instance
    ):
        """
        Args:
            vectorstore: LangChain Chroma vectorstore 인스턴스
        """
        self._vectorstore = vectorstore

    def search(
        self,
        query: str,
        k: int = 5,
        filter: Optional[Dict[str, Any]] = None
    ) -> List[MemoryDocument]:
        """유사도 검색"""
        if not query or not query.strip():
            return []

        try:
            # similarity_search_with_score 사용
            results = self._vectorstore.similarity_search_with_score(
                query,
                k=k,
                filter=filter
            )

            documents = []
            for doc, score in results:
                # Chroma는 거리를 반환하므로 유사도로 변환 (1 - distance)
                # cosine 거리일 경우 0~2 범위, 1-score/2로 정규화
                similarity = max(0, 1 - score / 2) if score > 0 else 1.0

                documents.append(MemoryDocument(
                    content=doc.page_content,
                    metadata=doc.metadata,
                    id=doc.metadata.get("id"),
                    score=similarity
                ))

            return documents

        except Exception:
            return []

    def search_with_threshold(
        self,
        query: str,
        k: int = 5,
        threshold: float = 0.3,
        filter: Optional[Dict[str, Any]] = None
    ) -> List[MemoryDocument]:
        """임계값 기반 검색"""
        results = self.search(query, k=k * 2, filter=filter)  # 더 많이 검색

        # 임계값 필터링
        filtered = [
            doc for doc in results
            if doc.score is not None and doc.score >= threshold
        ]

        return filtered[:k]


class ChromaRepository(MemoryRepository):
    """
    ChromaDB 기반 메모리 저장소

    책임: 문서 저장/삭제만 수행
    """

    def __init__(
        self,
        vectorstore,  # Chroma instance
    ):
        """
        Args:
            vectorstore: LangChain Chroma vectorstore 인스턴스
        """
        self._vectorstore = vectorstore

    def add(
        self,
        content: str,
        metadata: Optional[Dict[str, Any]] = None
    ) -> str:
        """문서 추가"""
        if not content or not content.strip():
            return ""

        doc_id = str(uuid.uuid4())

        # 메타데이터 준비
        final_metadata = metadata.copy() if metadata else {}
        final_metadata["id"] = doc_id
        final_metadata.setdefault("created_at", time.strftime("%Y-%m-%d %H:%M:%S"))

        try:
            from langchain_core.documents import Document

            doc = Document(
                page_content=content,
                metadata=final_metadata
            )

            self._vectorstore.add_documents([doc])

            return doc_id

        except Exception:
            return ""

    def add_batch(
        self,
        documents: List[Tuple[str, Dict[str, Any]]]
    ) -> List[str]:
        """여러 문서 일괄 추가"""
        if not documents:
            return []

        try:
            from langchain_core.documents import Document

            ids = []
            docs = []

            for content, metadata in documents:
                if not content or not content.strip():
                    continue

                doc_id = str(uuid.uuid4())

                final_metadata = metadata.copy() if metadata else {}
                final_metadata["id"] = doc_id
                final_metadata.setdefault("created_at", time.strftime("%Y-%m-%d %H:%M:%S"))

                docs.append(Document(
                    page_content=content,
                    metadata=final_metadata
                ))
                ids.append(doc_id)

            if docs:
                self._vectorstore.add_documents(docs)

            return ids

        except Exception:
            return []

    def delete(self, doc_id: str) -> bool:
        """문서 삭제"""
        try:
            self._vectorstore.delete([doc_id])
            return True
        except Exception:
            return False

    def clear(self, filter: Optional[Dict[str, Any]] = None) -> int:
        """문서 전체/조건부 삭제"""
        try:
            # 기존 문서 ID 조회
            existing = self._vectorstore.get()
            ids = existing.get("ids", [])

            if not ids:
                return 0

            # 필터가 있으면 조건에 맞는 것만 삭제
            if filter:
                metadatas = existing.get("metadatas", [])
                ids_to_delete = []

                for doc_id, metadata in zip(ids, metadatas):
                    match = all(
                        metadata.get(k) == v
                        for k, v in filter.items()
                    )
                    if match:
                        ids_to_delete.append(doc_id)

                if ids_to_delete:
                    self._vectorstore.delete(ids_to_delete)
                    return len(ids_to_delete)
                return 0

            # 전체 삭제
            self._vectorstore.delete(ids)
            return len(ids)

        except Exception:
            return 0


# ============================================================
# 팩토리 구현
# ============================================================

class ChromaMemoryFactory(MemorySystemFactory):
    """
    ChromaDB + Clova 기반 메모리 시스템 팩토리

    모든 컴포넌트를 일관되게 생성
    """

    def __init__(
        self,
        api_key: str,
        request_id: str,
        host: str = 'clovastudio.stream.ntruss.com',
        persist_directory: str = "./chroma_db",
        collection_name: str = "conversation_memory",
        embeddings=None
    ):
        """
        Args:
            api_key: Clova Studio API 키
            request_id: 요청 ID
            host: API 호스트
            persist_directory: ChromaDB 저장 경로
            collection_name: 컬렉션 이름
            embeddings: 커스텀 임베딩 (None이면 ClovaXEmbeddings 사용)
        """
        self._api_key = api_key
        self._request_id = request_id
        self._host = host
        self._persist_directory = persist_directory
        self._collection_name = collection_name
        self._custom_embeddings = embeddings

        # 공유 vectorstore 초기화
        self._vectorstore = None

    def _get_vectorstore(self):
        """Vectorstore lazy initialization"""
        if self._vectorstore is None:
            try:
                from langchain_chroma import Chroma
                import chromadb

                if self._custom_embeddings is not None:
                    embeddings = self._custom_embeddings
                else:
                    from langchain_community.embeddings import ClovaXEmbeddings
                    embeddings = ClovaXEmbeddings(
                        model="bge-m3",
                        ncp_clovastudio_api_key=self._api_key,
                        ncp_clovastudio_request_id=self._request_id
                    )

                client = chromadb.PersistentClient(path=self._persist_directory)

                self._vectorstore = Chroma(
                    client=client,
                    collection_name=self._collection_name,
                    embedding_function=embeddings,
                    collection_metadata={"hnsw:space": "cosine"}
                )

            except Exception:
                raise

        return self._vectorstore

    def create_retriever(self) -> MemoryRetriever:
        """Retriever 생성"""
        return ChromaRetriever(self._get_vectorstore())

    def create_repository(self) -> MemoryRepository:
        """Repository 생성"""
        return ChromaRepository(self._get_vectorstore())

    def create_summarizer(self) -> TextSummarizer:
        """Summarizer 생성 (Clova API)"""
        from memory.clova_adapters import ClovaSummarizer

        return ClovaSummarizer(
            api_key=self._api_key,
            request_id=self._request_id,
            host=self._host
        )

    def create_window_trimmer(self) -> WindowTrimmer:
        """WindowTrimmer 생성 (Clova API)"""
        from memory.clova_adapters import ClovaWindowTrimmer

        return ClovaWindowTrimmer(
            api_key=self._api_key,
            request_id=self._request_id,
            host=self._host
        )


# ============================================================
# 편의 함수
# ============================================================

def create_memory_system(
    api_key: str,
    request_id: str,
    host: str = 'clovastudio.stream.ntruss.com',
    persist_directory: str = "./chroma_db",
    embeddings=None
) -> Dict[str, Any]:
    """
    메모리 시스템 컴포넌트 일괄 생성

    Args:
        embeddings: 커스텀 임베딩 (None이면 ClovaXEmbeddings 사용)

    Returns:
        {
            "retriever": MemoryRetriever,
            "repository": MemoryRepository,
            "summarizer": TextSummarizer,
            "window_trimmer": WindowTrimmer
        }
    """
    factory = ChromaMemoryFactory(
        api_key=api_key,
        request_id=request_id,
        host=host,
        persist_directory=persist_directory,
        embeddings=embeddings
    )

    return {
        "retriever": factory.create_retriever(),
        "repository": factory.create_repository(),
        "summarizer": factory.create_summarizer(),
        "window_trimmer": factory.create_window_trimmer()
    }
