from __future__ import annotations

import json
import time
import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, replace
from typing import Any, Protocol

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

from app.models import Article, ArticleVersion, Document, DocumentChunk
from app.providers import EmbeddingProvider, ProviderUnavailable, RerankProvider
from app.text_chunking import iter_text_chunks


@dataclass(frozen=True, slots=True)
class RetrievalHit:
    chunk_id: str
    document_id: str
    source_name: str
    source_type: str
    section_id: str | None
    section_title: str | None
    page_no: int | None
    start_ms: int | None
    end_ms: int | None
    chunk_no: int
    text: str
    fulltext_score: float
    vector_score: float
    fused_score: float
    rerank_score: float | None = None


class RetrievalBackend(Protocol):
    enabled: bool

    async def replace_document(
        self,
        *,
        document: Document,
        chunks: list[DocumentChunk],
        vectors: list[list[float]],
        embedding_model: str,
    ) -> None: ...

    async def replace_article(
        self,
        *,
        article: Article,
        version: ArticleVersion,
        chunks: list[str],
        vectors: list[list[float]],
        embedding_model: str,
        chunking_version: str,
    ) -> None: ...

    async def candidates(
        self,
        *,
        owner_id: str,
        project_id: str | None,
        document_ids: list[str],
        query: str,
        query_vector: list[float],
        limit: int,
    ) -> list[RetrievalHit]: ...

    async def record_query(
        self,
        *,
        query_id: str,
        owner_id: str,
        task_id: str | None,
        original_query: str,
        normalized_query: str,
        filters: dict[str, Any],
        embedding_model: str,
        embedding_request_id: str,
        rerank_request_id: str | None,
        duration_ms: int,
        hits: list[RetrievalHit],
        context_count: int,
    ) -> None: ...

    async def delete_owner(self, owner_id: str) -> None: ...

    async def check_ready(self) -> None: ...

    async def dispose(self) -> None: ...


def _vector_literal(vector: list[float]) -> str:
    if not vector or any(not isinstance(value, int | float) for value in vector):
        raise ProviderUnavailable("Embedding vector is empty or invalid")
    return "[" + ",".join(format(float(value), ".9g") for value in vector) + "]"


class PostgresRetrievalBackend:
    enabled = True

    def __init__(self, database_url: str, *, engine: AsyncEngine | None = None) -> None:
        self._engine = engine or create_async_engine(database_url, pool_pre_ping=True)

    async def replace_document(
        self,
        *,
        document: Document,
        chunks: list[DocumentChunk],
        vectors: list[list[float]],
        embedding_model: str,
    ) -> None:
        if len(chunks) != len(vectors):
            raise ProviderUnavailable("Chunk and embedding counts do not match")
        async with self._engine.begin() as connection:
            await connection.execute(
                text("DELETE FROM retrieval_chunks WHERE document_id = :document_id"),
                {"document_id": document.id},
            )
            for chunk, vector in zip(chunks, vectors, strict=True):
                await connection.execute(
                    text(
                        """
                        INSERT INTO retrieval_chunks (
                          id, owner_id, project_id, document_id, source_type, source_name,
                          section_id, section_title, page_no, start_ms, end_ms,
                          chunk_no, chunking_version, text, token_count,
                          embedding, embedding_model
                        ) VALUES (
                          :id, :owner_id, :project_id, :document_id, 'document', :source_name,
                          :section_id, :section_title, :page_no, :start_ms, :end_ms,
                          :chunk_no, :chunking_version, :text, :token_count,
                          CAST(:embedding AS halfvec), :embedding_model
                        )
                        """
                    ),
                    {
                        "id": chunk.id,
                        "owner_id": chunk.owner_id,
                        "project_id": chunk.project_id,
                        "document_id": document.id,
                        "source_name": document.title,
                        "section_id": chunk.section_id,
                        "section_title": chunk.section_title,
                        "page_no": chunk.page_no,
                        "start_ms": chunk.start_ms,
                        "end_ms": chunk.end_ms,
                        "chunk_no": chunk.chunk_no,
                        "chunking_version": chunk.chunking_version,
                        "text": chunk.text,
                        "token_count": chunk.token_count,
                        "embedding": _vector_literal(vector),
                        "embedding_model": embedding_model,
                    },
                )

    async def replace_article(
        self,
        *,
        article: Article,
        version: ArticleVersion,
        chunks: list[str],
        vectors: list[list[float]],
        embedding_model: str,
        chunking_version: str,
    ) -> None:
        if len(chunks) != len(vectors):
            raise ProviderUnavailable("Article chunk and embedding counts do not match")
        async with self._engine.begin() as connection:
            await connection.execute(
                text(
                    "DELETE FROM retrieval_chunks "
                    "WHERE source_type = 'article' AND document_id = :article_id"
                ),
                {"article_id": article.id},
            )
            for chunk_no, (chunk, vector) in enumerate(zip(chunks, vectors, strict=True), start=1):
                chunk_id = str(
                    uuid.uuid5(
                        uuid.NAMESPACE_URL,
                        f"wechat-ai:article:{version.id}:chunk:{chunk_no}",
                    )
                )
                await connection.execute(
                    text(
                        """
                        INSERT INTO retrieval_chunks (
                          id, owner_id, project_id, document_id, source_type, source_name,
                          section_id, section_title, page_no, start_ms, end_ms,
                          chunk_no, chunking_version, text, token_count,
                          embedding, embedding_model
                        ) VALUES (
                          :id, :owner_id, :project_id, :article_id, 'article', :source_name,
                          NULL, :section_title, NULL, NULL, NULL,
                          :chunk_no, :chunking_version, :text, :token_count,
                          CAST(:embedding AS halfvec), :embedding_model
                        )
                        """
                    ),
                    {
                        "id": chunk_id,
                        "owner_id": article.owner_id,
                        "project_id": article.project_id,
                        "article_id": article.id,
                        "source_name": article.title,
                        "section_title": f"文章版本 v{version.version_no}",
                        "chunk_no": chunk_no,
                        "chunking_version": chunking_version,
                        "text": chunk,
                        "token_count": max(1, len(chunk) // 4),
                        "embedding": _vector_literal(vector),
                        "embedding_model": embedding_model,
                    },
                )

    async def candidates(
        self,
        *,
        owner_id: str,
        project_id: str | None,
        document_ids: list[str],
        query: str,
        query_vector: list[float],
        limit: int,
    ) -> list[RetrievalHit]:
        if not document_ids:
            return []
        candidate_limit = max(50, limit)
        statement = text(
            """
            WITH fulltext AS (
              SELECT id,
                     greatest(
                       ts_rank_cd(search_vector, plainto_tsquery('simple', :query)),
                       similarity(text, :query)
                     ) AS score,
                     row_number() OVER (
                       ORDER BY greatest(
                         ts_rank_cd(search_vector, plainto_tsquery('simple', :query)),
                         similarity(text, :query)
                       ) DESC, id
                     ) AS rank
              FROM retrieval_chunks
              WHERE owner_id = :owner_id
                AND document_id = ANY(CAST(:document_ids AS varchar[]))
                AND (CAST(:project_id AS varchar) IS NULL
                     OR project_id = CAST(:project_id AS varchar))
              ORDER BY score DESC, id
              LIMIT :candidate_limit
            ), vector AS (
              SELECT id,
                     1 - (embedding <=> CAST(:embedding AS halfvec)) AS score,
                     row_number() OVER (
                       ORDER BY embedding <=> CAST(:embedding AS halfvec), id
                     ) AS rank
              FROM retrieval_chunks
              WHERE owner_id = :owner_id
                AND document_id = ANY(CAST(:document_ids AS varchar[]))
                AND (CAST(:project_id AS varchar) IS NULL
                     OR project_id = CAST(:project_id AS varchar))
              ORDER BY embedding <=> CAST(:embedding AS halfvec), id
              LIMIT :candidate_limit
            ), fused AS (
              SELECT coalesce(fulltext.id, vector.id) AS id,
                     coalesce(fulltext.score, 0) AS fulltext_score,
                     coalesce(vector.score, 0) AS vector_score,
                     coalesce(1.0 / (60 + fulltext.rank), 0) +
                       coalesce(1.0 / (60 + vector.rank), 0) AS fused_score
              FROM fulltext FULL OUTER JOIN vector ON fulltext.id = vector.id
            )
            SELECT chunk.id AS chunk_id, chunk.document_id, chunk.source_name,
                   chunk.source_type, chunk.section_id, chunk.section_title,
                   chunk.page_no, chunk.start_ms, chunk.end_ms, chunk.chunk_no,
                   chunk.text, fused.fulltext_score, fused.vector_score, fused.fused_score
            FROM fused JOIN retrieval_chunks AS chunk ON chunk.id = fused.id
            ORDER BY fused.fused_score DESC, chunk.id
            LIMIT :limit
            """
        )
        async with self._engine.connect() as connection:
            rows = (
                await connection.execute(
                    statement,
                    {
                        "owner_id": owner_id,
                        "project_id": project_id,
                        "document_ids": document_ids,
                        "query": query,
                        "embedding": _vector_literal(query_vector),
                        "candidate_limit": candidate_limit,
                        "limit": limit,
                    },
                )
            ).mappings()
        return [
            RetrievalHit(
                chunk_id=str(row["chunk_id"]),
                document_id=str(row["document_id"]),
                source_name=str(row["source_name"]),
                source_type=str(row["source_type"]),
                section_id=str(row["section_id"]) if row["section_id"] else None,
                section_title=(str(row["section_title"]) if row["section_title"] else None),
                page_no=int(row["page_no"]) if row["page_no"] is not None else None,
                start_ms=int(row["start_ms"]) if row["start_ms"] is not None else None,
                end_ms=int(row["end_ms"]) if row["end_ms"] is not None else None,
                chunk_no=int(row["chunk_no"]),
                text=str(row["text"]),
                fulltext_score=float(row["fulltext_score"]),
                vector_score=float(row["vector_score"]),
                fused_score=float(row["fused_score"]),
            )
            for row in rows
        ]

    async def record_query(
        self,
        *,
        query_id: str,
        owner_id: str,
        task_id: str | None,
        original_query: str,
        normalized_query: str,
        filters: dict[str, Any],
        embedding_model: str,
        embedding_request_id: str,
        rerank_request_id: str | None,
        duration_ms: int,
        hits: list[RetrievalHit],
        context_count: int,
    ) -> None:
        async with self._engine.begin() as connection:
            await connection.execute(
                text(
                    """
                    INSERT INTO retrieval_queries (
                      id, owner_id, task_id, original_query, normalized_query, filters,
                      embedding_model, embedding_request_id, rerank_request_id,
                      total_duration_ms
                    ) VALUES (
                      :id, :owner_id, :task_id, :original_query, :normalized_query,
                      CAST(:filters AS jsonb), :embedding_model, :embedding_request_id,
                      :rerank_request_id, :total_duration_ms
                    )
                    """
                ),
                {
                    "id": query_id,
                    "owner_id": owner_id,
                    "task_id": task_id,
                    "original_query": original_query,
                    "normalized_query": normalized_query,
                    "filters": json.dumps(filters, ensure_ascii=False),
                    "embedding_model": embedding_model,
                    "embedding_request_id": embedding_request_id,
                    "rerank_request_id": rerank_request_id,
                    "total_duration_ms": duration_ms,
                },
            )
            for rank, hit in enumerate(hits, start=1):
                await connection.execute(
                    text(
                        """
                        INSERT INTO retrieval_results (
                          query_id, chunk_id, fulltext_score, vector_score, fused_score,
                          rerank_score, rank, entered_context
                        ) VALUES (
                          :query_id, :chunk_id, :fulltext_score, :vector_score,
                          :fused_score, :rerank_score, :rank, :entered_context
                        )
                        """
                    ),
                    {
                        "query_id": query_id,
                        "chunk_id": hit.chunk_id,
                        "fulltext_score": hit.fulltext_score,
                        "vector_score": hit.vector_score,
                        "fused_score": hit.fused_score,
                        "rerank_score": hit.rerank_score,
                        "rank": rank,
                        "entered_context": rank <= context_count,
                    },
                )

    async def delete_owner(self, owner_id: str) -> None:
        async with self._engine.begin() as connection:
            query_ids = text("SELECT id FROM retrieval_queries WHERE owner_id = :owner_id")
            await connection.execute(
                text(
                    "DELETE FROM retrieval_results WHERE query_id IN "
                    "(SELECT id FROM retrieval_queries WHERE owner_id = :owner_id)"
                ),
                {"owner_id": owner_id},
            )
            del query_ids
            await connection.execute(
                text("DELETE FROM retrieval_queries WHERE owner_id = :owner_id"),
                {"owner_id": owner_id},
            )
            await connection.execute(
                text("DELETE FROM retrieval_chunks WHERE owner_id = :owner_id"),
                {"owner_id": owner_id},
            )

    async def check_ready(self) -> None:
        async with self._engine.connect() as connection:
            await connection.execute(text("SELECT 1 FROM retrieval_chunks LIMIT 1"))

    async def dispose(self) -> None:
        await self._engine.dispose()


class DisabledRetrievalBackend:
    enabled = False

    async def replace_document(self, **_: Any) -> None:
        return None

    async def replace_article(self, **_: Any) -> None:
        return None

    async def candidates(self, **_: Any) -> list[RetrievalHit]:
        return []

    async def record_query(self, **_: Any) -> None:
        return None

    async def delete_owner(self, owner_id: str) -> None:
        del owner_id

    async def check_ready(self) -> None:
        return None

    async def dispose(self) -> None:
        return None


EMBEDDING_BATCH_SIZE = 10


class RetrievalService:
    def __init__(
        self,
        *,
        backend: RetrievalBackend,
        embedding: EmbeddingProvider,
        rerank: RerankProvider,
        embedding_factory: Callable[[], Awaitable[EmbeddingProvider]] | None = None,
        rerank_factory: Callable[[], Awaitable[RerankProvider]] | None = None,
    ) -> None:
        self.backend = backend
        self._embedding = embedding
        self._rerank = rerank
        self._embedding_factory = embedding_factory
        self._rerank_factory = rerank_factory

    @property
    def enabled(self) -> bool:
        return self.backend.enabled

    async def index_document(
        self, *, document: Document, chunks: list[DocumentChunk]
    ) -> str | None:
        if not self.enabled or not chunks:
            return None
        embedding = await self._embedding_factory() if self._embedding_factory else self._embedding
        vectors: list[list[float]] = []
        model = ""
        for offset in range(0, len(chunks), EMBEDDING_BATCH_SIZE):
            result = await embedding.embed(
                [chunk.text for chunk in chunks[offset : offset + EMBEDDING_BATCH_SIZE]]
            )
            vectors.extend(result.vectors)
            model = result.model
        await self.backend.replace_document(
            document=document,
            chunks=chunks,
            vectors=vectors,
            embedding_model=model,
        )
        return model

    async def index_article(
        self,
        *,
        article: Article,
        version: ArticleVersion,
        target_characters: int,
        overlap_characters: int,
        chunking_version: str,
    ) -> str | None:
        if not self.enabled:
            return None
        embedding = await self._embedding_factory() if self._embedding_factory else self._embedding
        chunks = list(
            iter_text_chunks(
                version.plain_text,
                target_characters=target_characters,
                overlap_characters=overlap_characters,
            )
        )
        if not chunks:
            return None
        vectors: list[list[float]] = []
        model = ""
        for offset in range(0, len(chunks), EMBEDDING_BATCH_SIZE):
            result = await embedding.embed(chunks[offset : offset + EMBEDDING_BATCH_SIZE])
            vectors.extend(result.vectors)
            model = result.model
        await self.backend.replace_article(
            article=article,
            version=version,
            chunks=chunks,
            vectors=vectors,
            embedding_model=model,
            chunking_version=chunking_version,
        )
        return model

    async def search(
        self,
        *,
        owner_id: str,
        task_id: str | None,
        project_id: str | None,
        document_ids: list[str],
        query: str,
        context_count: int = 8,
    ) -> list[RetrievalHit]:
        normalized = " ".join(query.split())[:4000]
        if not self.enabled or not normalized or not document_ids:
            return []
        embedding = await self._embedding_factory() if self._embedding_factory else self._embedding
        rerank = await self._rerank_factory() if self._rerank_factory else self._rerank
        started = time.perf_counter()
        embedded = await embedding.embed([normalized])
        candidates = await self.backend.candidates(
            owner_id=owner_id,
            project_id=project_id,
            document_ids=document_ids,
            query=normalized,
            query_vector=embedded.vectors[0],
            limit=30,
        )
        rerank_request_id: str | None = None
        if candidates:
            reranked = await rerank.rerank(
                query=normalized, documents=[hit.text for hit in candidates]
            )
            rerank_request_id = reranked.provider_request_id
            candidates = [
                replace(hit, rerank_score=reranked.scores[index])
                for index, hit in enumerate(candidates)
            ]
            candidates.sort(
                key=lambda hit: (
                    hit.rerank_score if hit.rerank_score is not None else hit.fused_score,
                    hit.fused_score,
                ),
                reverse=True,
            )
            candidates = self._diversify(candidates, context_count)
        query_id = str(uuid.uuid4())
        await self.backend.record_query(
            query_id=query_id,
            owner_id=owner_id,
            task_id=task_id,
            original_query=query,
            normalized_query=normalized,
            filters={"project_id": project_id, "document_ids": document_ids},
            embedding_model=embedded.model,
            embedding_request_id=embedded.provider_request_id,
            rerank_request_id=rerank_request_id,
            duration_ms=int((time.perf_counter() - started) * 1000),
            hits=candidates,
            context_count=context_count,
        )
        return candidates[:context_count]

    @staticmethod
    def _diversify(hits: list[RetrievalHit], context_count: int) -> list[RetrievalHit]:
        if context_count <= 1:
            return hits
        per_document_limit = max(2, (context_count + 1) // 2)
        selected: list[RetrievalHit] = []
        deferred: list[RetrievalHit] = []
        counts: dict[str, int] = {}
        for hit in hits:
            count = counts.get(hit.document_id, 0)
            if len(selected) < context_count and count < per_document_limit:
                selected.append(hit)
                counts[hit.document_id] = count + 1
            else:
                deferred.append(hit)
        return [*selected, *deferred]


def build_retrieval_service(
    database_url: str,
    *,
    embedding: EmbeddingProvider,
    rerank: RerankProvider,
    embedding_factory: Callable[[], Awaitable[EmbeddingProvider]] | None = None,
    rerank_factory: Callable[[], Awaitable[RerankProvider]] | None = None,
) -> RetrievalService:
    backend: RetrievalBackend = (
        PostgresRetrievalBackend(database_url) if database_url else DisabledRetrievalBackend()
    )
    return RetrievalService(
        backend=backend,
        embedding=embedding,
        rerank=rerank,
        embedding_factory=embedding_factory,
        rerank_factory=rerank_factory,
    )
