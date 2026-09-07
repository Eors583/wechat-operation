from __future__ import annotations

from typing import Any

from app.models import Article, ArticleVersion, Document, DocumentChunk
from app.providers import EmbeddingResult, RerankResult
from app.retrieval import RetrievalHit, RetrievalService


class StaticEmbeddingProvider:
    async def embed(self, texts: list[str]) -> EmbeddingResult:
        return EmbeddingResult(
            vectors=[[float(index), 0.5] for index, _ in enumerate(texts, start=1)],
            model="embedding-test",
            provider_request_id="embedding-request",
            simulated=False,
        )


class StaticRerankProvider:
    async def rerank(self, *, query: str, documents: list[str]) -> RerankResult:
        del query
        scores = [float(len(documents) - index) for index in range(len(documents))]
        if len(scores) >= 2:
            scores[0], scores[1] = scores[1], scores[0]
        return RerankResult(scores, "rerank-request", False)


class MemoryRetrievalBackend:
    enabled = True

    def __init__(self, hits: list[RetrievalHit]) -> None:
        self.hits = hits
        self.candidate_arguments: dict[str, Any] = {}
        self.record_arguments: dict[str, Any] = {}
        self.index_arguments: dict[str, Any] = {}

    async def replace_document(self, **kwargs: Any) -> None:
        self.index_arguments = kwargs

    async def replace_article(self, **kwargs: Any) -> None:
        self.index_arguments = kwargs

    async def candidates(self, **kwargs: Any) -> list[RetrievalHit]:
        self.candidate_arguments = kwargs
        return list(self.hits)

    async def record_query(self, **kwargs: Any) -> None:
        self.record_arguments = kwargs

    async def delete_owner(self, owner_id: str) -> None:
        del owner_id

    async def check_ready(self) -> None:
        return None

    async def dispose(self) -> None:
        return None


def hit(identifier: int, document_id: str) -> RetrievalHit:
    return RetrievalHit(
        chunk_id=f"chunk-{identifier}",
        document_id=document_id,
        source_name=f"资料 {document_id}",
        source_type="document",
        section_id=None,
        section_title=None,
        page_no=identifier,
        start_ms=None,
        end_ms=None,
        chunk_no=identifier,
        text=f"候选内容 {identifier}",
        fulltext_score=0.1,
        vector_score=0.2,
        fused_score=1 / (60 + identifier),
    )


async def test_hybrid_retrieval_filters_reranks_diversifies_and_records_context() -> None:
    backend = MemoryRetrievalBackend(
        [hit(1, "doc-a"), hit(2, "doc-a"), hit(3, "doc-a"), hit(4, "doc-b")]
    )
    service = RetrievalService(
        backend=backend,
        embedding=StaticEmbeddingProvider(),
        rerank=StaticRerankProvider(),
    )
    results = await service.search(
        owner_id="owner-1",
        task_id="task-1",
        project_id="project-1",
        document_ids=["doc-a", "doc-b"],
        query="  检索   问题  ",
        context_count=3,
    )
    assert [item.chunk_id for item in results] == ["chunk-2", "chunk-1", "chunk-4"]
    assert backend.candidate_arguments["owner_id"] == "owner-1"
    assert backend.candidate_arguments["document_ids"] == ["doc-a", "doc-b"]
    assert backend.candidate_arguments["query"] == "检索 问题"
    assert backend.record_arguments["embedding_request_id"] == "embedding-request"
    assert backend.record_arguments["rerank_request_id"] == "rerank-request"
    assert backend.record_arguments["context_count"] == 3


async def test_document_indexing_batches_embeddings_and_preserves_chunk_ids() -> None:
    backend = MemoryRetrievalBackend([])
    service = RetrievalService(
        backend=backend,
        embedding=StaticEmbeddingProvider(),
        rerank=StaticRerankProvider(),
    )
    document = Document(
        id="document-1",
        owner_id="owner-1",
        asset_id="asset-1",
        title="测试资料",
    )
    chunks = [
        DocumentChunk(
            id=f"chunk-{index}",
            owner_id="owner-1",
            document_id=document.id,
            chunk_no=index,
            text=f"内容 {index}",
            token_count=2,
        )
        for index in range(1, 4)
    ]
    model = await service.index_document(document=document, chunks=chunks)
    assert model == "embedding-test"
    assert backend.index_arguments["chunks"] == chunks
    assert backend.index_arguments["vectors"] == [[1.0, 0.5], [2.0, 0.5], [3.0, 0.5]]


async def test_article_indexing_reuses_versioned_chunking_and_embedding_batches() -> None:
    backend = MemoryRetrievalBackend([])
    service = RetrievalService(
        backend=backend,
        embedding=StaticEmbeddingProvider(),
        rerank=StaticRerankProvider(),
    )
    article = Article(id="article-1", owner_id="owner-1", title="已保存文章")
    version = ArticleVersion(
        id="article-version-1",
        article_id=article.id,
        version_no=2,
        content_json={"type": "doc", "content": []},
        plain_text="甲乙丙丁戊己庚辛壬癸",
        content_hash="hash",
        source="editor",
        created_by_type="user",
        created_by_id="owner-1",
    )
    model = await service.index_article(
        article=article,
        version=version,
        target_characters=6,
        overlap_characters=2,
        chunking_version="zh-char-test-v1",
    )
    assert model == "embedding-test"
    assert backend.index_arguments["chunks"] == ["甲乙丙丁戊己", "戊己庚辛壬癸"]
    assert backend.index_arguments["chunking_version"] == "zh-char-test-v1"
    assert len(backend.index_arguments["vectors"]) == 2
