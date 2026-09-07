from __future__ import annotations

from app.config import Settings
from app.database import Database
from app.model_gateway import (
    FrozenEmbeddingRouteProvider,
    FrozenRerankRouteProvider,
    active_route_snapshot,
)
from app.providers import EmbeddingProvider, RerankProvider, SecretProvider
from app.retrieval import RetrievalService, build_retrieval_service


def build_route_aware_retrieval_service(
    *,
    database: Database,
    settings: Settings,
    secrets: SecretProvider,
    embedding: EmbeddingProvider,
    rerank: RerankProvider,
) -> RetrievalService:
    """Resolve and freeze published retrieval routes once per index/search operation."""

    async def embedding_factory() -> EmbeddingProvider:
        async with database.session_maker() as session:
            snapshot = await active_route_snapshot(session, purpose="embedding", settings=settings)
        return FrozenEmbeddingRouteProvider(
            snapshot=snapshot,
            fallback=embedding,
            secrets=secrets,
            dimension=settings.embedding_dimension,
        )

    async def rerank_factory() -> RerankProvider:
        async with database.session_maker() as session:
            snapshot = await active_route_snapshot(session, purpose="rerank", settings=settings)
        return FrozenRerankRouteProvider(
            snapshot=snapshot,
            fallback=rerank,
            secrets=secrets,
        )

    return build_retrieval_service(
        settings.retrieval_database_url,
        embedding=embedding,
        rerank=rerank,
        embedding_factory=embedding_factory,
        rerank_factory=rerank_factory,
    )
