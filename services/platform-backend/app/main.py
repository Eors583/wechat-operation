from __future__ import annotations

import logging
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import PlainTextResponse

from app.api.admin import router as admin_router
from app.api.callbacks import router as callbacks_router
from app.api.user import router as user_router
from app.config import Settings
from app.database import Database
from app.errors import install_error_handlers
from app.provider_factory import build_providers
from app.providers import EnvironmentSecretProvider
from app.retrieval_routing import build_route_aware_retrieval_service
from app.security import RateLimiter, new_uuid
from app.wechat_open_platform import seed_wechat_config_from_environment


def create_app(app_settings: Settings | None = None) -> FastAPI:
    # Never let dependency INFO logs expose presigned upload query strings.
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)
    config = app_settings or Settings.from_env()
    database = Database(config)
    secret_provider = EnvironmentSecretProvider(
        config.model_secret_master_key or config.token_secret
    )
    providers = build_providers(config, secret_provider)
    retrieval = build_route_aware_retrieval_service(
        database=database,
        settings=config,
        secrets=secret_provider,
        embedding=providers.embedding,
        rerank=providers.rerank,
    )

    @asynccontextmanager
    async def lifespan(application: FastAPI) -> AsyncIterator[None]:
        if config.auto_create_schema:
            await database.create_schema()
        async with database.session_maker() as session:
            await seed_wechat_config_from_environment(session, settings=config)
        yield
        await retrieval.backend.dispose()
        await database.dispose()

    application = FastAPI(
        title="WeChat AI Operations Platform",
        version="0.1.0",
        lifespan=lifespan,
        docs_url="/docs" if config.environment != "production" else None,
        redoc_url=None,
    )
    application.state.settings = config
    application.state.database = database
    application.state.rate_limiter = RateLimiter()
    application.state.secret_provider = secret_provider
    application.state.retrieval = retrieval
    application.state.verification_provider = providers.verification
    application.state.storage_provider = providers.storage
    application.state.document_processing_provider = providers.document_processing
    application.state.layout_extraction_provider = providers.layout_extraction
    application.state.model_provider = providers.model
    application.state.embedding_provider = providers.embedding
    application.state.rerank_provider = providers.rerank
    application.state.content_safety_provider = providers.content_safety
    application.state.wechat_provider = providers.wechat
    application.state.web_reference_provider = providers.web_reference

    application.add_middleware(
        CORSMiddleware,
        allow_origins=list(config.allowed_origins),
        allow_credentials=True,
        allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
        allow_headers=[
            "Authorization",
            "Content-Type",
            "Idempotency-Key",
            "Last-Event-ID",
            "X-CSRF-Token",
        ],
        expose_headers=["X-Request-ID", "ETag"],
    )

    @application.middleware("http")
    async def request_context(
        request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        incoming = request.headers.get("X-Request-ID", "")
        request.state.request_id = (
            incoming[:80] if incoming.isascii() and incoming else f"req_{new_uuid()}"
        )
        response = await call_next(request)
        response.headers["X-Request-ID"] = request.state.request_id
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers.setdefault("Referrer-Policy", "same-origin")
        return response

    @application.get("/health/live", tags=["health"])
    async def liveness() -> dict[str, str]:
        return {"status": "ok"}

    @application.get("/health/ready", tags=["health"])
    async def readiness() -> dict[str, str]:
        async with database.engine.connect() as connection:
            await connection.exec_driver_sql("SELECT 1")
        if retrieval.enabled:
            await retrieval.backend.check_ready()
        return {"status": "ready"}

    application.include_router(user_router, tags=["user"])
    application.include_router(admin_router, tags=["admin"])
    application.include_router(callbacks_router, tags=["callbacks"])

    @application.get("/{filename}", include_in_schema=False, response_class=PlainTextResponse)
    async def wechat_domain_verification(filename: str) -> PlainTextResponse:
        if not config.wechat_domain_verification_filename or (
            filename != config.wechat_domain_verification_filename
        ):
            raise HTTPException(status_code=404)
        return PlainTextResponse(
            config.wechat_domain_verification_content,
            headers={"Cache-Control": "no-store"},
        )

    install_error_handlers(application)
    return application


app = create_app()
