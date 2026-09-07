from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass
from html.parser import HTMLParser
from typing import Any, cast
from urllib.parse import urljoin

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import ExternalKnowledgeSource
from app.providers import ProviderUnavailable, SecretProvider

LEXIANG_API_BASE = "https://lxapi.lexiangla.com"


@dataclass(frozen=True, slots=True)
class LexiangEntry:
    id: str
    name: str
    entry_type: str
    has_children: bool
    version: str | None


@dataclass(frozen=True, slots=True)
class LexiangEntryPage:
    entries: list[LexiangEntry]
    next_page_token: str | None


@dataclass(frozen=True, slots=True)
class LexiangSearchHit:
    title: str
    content: str
    url: str | None
    score: float | None


class _TextExtractor(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.fragments: list[str] = []

    def handle_data(self, data: str) -> None:
        value = " ".join(data.split())
        if value:
            self.fragments.append(value)


class LexiangKnowledgeProvider:
    """Permission-preserving adapter for the official Tencent Lexiang Open API."""

    def __init__(
        self,
        *,
        app_key: str,
        app_secret: str,
        api_base: str = LEXIANG_API_BASE,
        timeout_seconds: float = 20.0,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        if api_base.rstrip("/") != LEXIANG_API_BASE:
            raise ProviderUnavailable("Lexiang API base must use the official HTTPS endpoint")
        self._app_key = app_key
        self._app_secret = app_secret
        self._api_base = api_base.rstrip("/")
        self._timeout = timeout_seconds
        self._transport = transport
        self._access_token = ""
        self._token_expires_at = 0.0
        self._token_lock = asyncio.Lock()

    async def test_connection(self) -> None:
        await self._token(force=True)

    async def list_entries(
        self,
        *,
        space_id: str,
        parent_id: str | None = None,
        page_token: str | None = None,
        limit: int = 100,
    ) -> LexiangEntryPage:
        params: dict[str, str | int] = {"space_id": space_id, "limit": min(100, limit)}
        if parent_id:
            params["parent_id"] = parent_id
        if page_token:
            params["page_token"] = page_token
        body = await self._request("GET", "/cgi-bin/v1/kb/entries", params=params)
        raw_entries = body.get("data")
        if not isinstance(raw_entries, list):
            raise ProviderUnavailable("Lexiang entry listing returned invalid data")
        entries: list[LexiangEntry] = []
        for raw in raw_entries:
            if not isinstance(raw, dict) or not isinstance(raw.get("id"), str):
                continue
            attributes = raw.get("attributes")
            if not isinstance(attributes, dict):
                continue
            name = attributes.get("name")
            entry_type = attributes.get("entry_type")
            if not isinstance(name, str) or not isinstance(entry_type, str):
                continue
            version_value = attributes.get("updated_at") or attributes.get("version")
            entries.append(
                LexiangEntry(
                    id=str(raw["id"]),
                    name=name,
                    entry_type=entry_type,
                    has_children=bool(attributes.get("has_children", False)),
                    version=str(version_value) if version_value is not None else None,
                )
            )
        meta = body.get("meta")
        next_page_token = meta.get("page_token") if isinstance(meta, dict) else None
        return LexiangEntryPage(
            entries=entries,
            next_page_token=next_page_token if isinstance(next_page_token, str) else None,
        )

    async def page_content(self, entry_id: str) -> str:
        body = await self._request(
            "GET",
            f"/cgi-bin/v1/kb/entries/{entry_id}/content",
            params={"content_type": "html"},
        )
        raw = body.get("data")
        attributes = raw.get("attributes") if isinstance(raw, dict) else None
        html = attributes.get("html_content") if isinstance(attributes, dict) else None
        if not isinstance(html, str):
            raise ProviderUnavailable("Lexiang page content returned invalid data")
        parser = _TextExtractor()
        parser.feed(html)
        return "\n".join(parser.fragments)

    async def search(
        self,
        *,
        query: str,
        staff_id: str,
        targets: list[dict[str, str]],
        top_n: int = 8,
    ) -> list[LexiangSearchHit]:
        if not targets or len(targets) > 20:
            raise ProviderUnavailable("Lexiang search requires 1-20 permission-scoped targets")
        body = await self._request(
            "POST",
            "/cgi-bin/v1/ai/search",
            headers={"x-staff-id": staff_id},
            json={
                "query": query[:1024],
                "targets": targets,
                "top_n": min(50, top_n),
                "with_score": True,
            },
        )
        if body.get("code") not in {None, 0}:
            raise ProviderUnavailable("Lexiang AI search rejected the request")
        data = body.get("data")
        items = data.get("list") if isinstance(data, dict) else None
        if not isinstance(items, list):
            raise ProviderUnavailable("Lexiang AI search returned invalid data")
        hits: list[LexiangSearchHit] = []
        for item in items:
            if not isinstance(item, dict):
                continue
            title, content = item.get("title"), item.get("content")
            if not isinstance(title, str) or not isinstance(content, str):
                continue
            score = item.get("score")
            hits.append(
                LexiangSearchHit(
                    title=title,
                    content=content,
                    url=item.get("url") if isinstance(item.get("url"), str) else None,
                    score=float(score) if isinstance(score, int | float) else None,
                )
            )
        return hits

    async def _token(self, *, force: bool = False) -> str:
        if not force and self._access_token and time.monotonic() < self._token_expires_at:
            return self._access_token
        async with self._token_lock:
            if not force and self._access_token and time.monotonic() < self._token_expires_at:
                return self._access_token
            try:
                async with httpx.AsyncClient(
                    timeout=self._timeout, transport=self._transport
                ) as client:
                    response = await client.post(
                        urljoin(self._api_base + "/", "cgi-bin/token"),
                        json={
                            "grant_type": "client_credentials",
                            "app_key": self._app_key,
                            "app_secret": self._app_secret,
                        },
                    )
                    response.raise_for_status()
                    body = response.json()
            except (httpx.HTTPError, ValueError) as exc:
                raise ProviderUnavailable("Lexiang token request failed") from exc
            if not isinstance(body, dict) or not isinstance(body.get("access_token"), str):
                raise ProviderUnavailable("Lexiang token response was invalid")
            expires_in = body.get("expires_in", 7200)
            seconds = int(expires_in) if isinstance(expires_in, int | float) else 7200
            self._access_token = str(body["access_token"])
            self._token_expires_at = time.monotonic() + max(60, seconds - 120)
            return self._access_token

    async def _request(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, str | int] | None = None,
        headers: dict[str, str] | None = None,
        json: dict[str, Any] | None = None,
        retry_auth: bool = True,
    ) -> dict[str, Any]:
        token = await self._token()
        request_headers = {"Authorization": f"Bearer {token}", **(headers or {})}
        try:
            async with httpx.AsyncClient(
                timeout=self._timeout, transport=self._transport
            ) as client:
                response = await client.request(
                    method,
                    urljoin(self._api_base + "/", path.lstrip("/")),
                    params=params,
                    headers=request_headers,
                    json=json,
                )
                if response.status_code == 401 and retry_auth:
                    await self._token(force=True)
                    return await self._request(
                        method,
                        path,
                        params=params,
                        headers=headers,
                        json=json,
                        retry_auth=False,
                    )
                response.raise_for_status()
                body = response.json()
        except (httpx.HTTPError, ValueError) as exc:
            raise ProviderUnavailable("Lexiang API request failed") from exc
        if not isinstance(body, dict):
            raise ProviderUnavailable("Lexiang API returned invalid JSON")
        return cast(dict[str, Any], body)


async def search_external_knowledge(
    session: AsyncSession,
    *,
    owner_id: str,
    query: str,
    secrets: SecretProvider,
) -> list[dict[str, Any]]:
    sources = list(
        (
            await session.scalars(
                select(ExternalKnowledgeSource).where(
                    ExternalKnowledgeSource.source_type == "lexiang",
                    ExternalKnowledgeSource.status == "active",
                )
            )
        ).all()
    )
    calls: list[
        tuple[ExternalKnowledgeSource, LexiangKnowledgeProvider, str, list[dict[str, str]]]
    ] = []
    for source in sources:
        owner_staff_ids = source.scope.get("owner_staff_ids", {})
        staff_id = owner_staff_ids.get(owner_id) if isinstance(owner_staff_ids, dict) else None
        targets = source.scope.get("targets", [])
        if not isinstance(staff_id, str) or not isinstance(targets, list) or not targets:
            continue
        safe_targets = [
            {"type": str(item["type"]), "id": str(item["id"])}
            for item in targets
            if isinstance(item, dict)
            and item.get("type") in {"team", "space", "kb_entry"}
            and isinstance(item.get("id"), str)
        ]
        app_key = source.configuration.get("app_key")
        if not source.secret_ref or not isinstance(app_key, str) or not safe_targets:
            continue
        try:
            provider = LexiangKnowledgeProvider(
                app_key=app_key,
                app_secret=secrets.resolve(source.secret_ref),
            )
        except ProviderUnavailable:
            continue
        calls.append((source, provider, staff_id, safe_targets))
    if not calls:
        return []
    results = await asyncio.gather(
        *(
            provider.search(query=query, staff_id=staff_id, targets=targets)
            for _, provider, staff_id, targets in calls[:3]
        ),
        return_exceptions=True,
    )
    context: list[dict[str, Any]] = []
    for (source, _, _, _), result in zip(calls[:3], results, strict=True):
        if isinstance(result, BaseException):
            context.append(
                {
                    "source_id": source.id,
                    "source_name": source.name,
                    "status": "unavailable",
                    "hits": [],
                }
            )
            continue
        context.append(
            {
                "source_id": source.id,
                "source_name": source.name,
                "status": "available",
                "hits": [
                    {
                        "title": hit.title,
                        "text": hit.content[:4000],
                        "url": hit.url,
                        "score": hit.score,
                        "source_type": "lexiang",
                    }
                    for hit in result[:8]
                ],
            }
        )
    return context
