from __future__ import annotations

import json

import httpx
import pytest
from fastapi import FastAPI
from httpx import AsyncClient
from sqlalchemy import select

from app.config import Settings
from app.domains.ai import classify_run_type, readable_model_result
from app.models import AIRun, Asset, Document, DocumentSection, LibraryItem
from app.provider_factory import build_providers
from app.providers import (
    MockStorageProvider,
    MockWebReferenceProvider,
    ModelResult,
    ProviderUnavailable,
    WebReferenceContent,
)
from app.web_references import SafeHttpWebReferenceProvider, extract_message_links

from .conftest import bearer, register_and_login


async def _public_resolver(_hostname: str) -> list[str]:
    return ["93.184.216.34"]


def test_mock_bundle_keeps_real_read_only_web_fetching_outside_tests() -> None:
    development = build_providers(Settings(environment="development", mock_external_services=True))
    testing = build_providers(Settings(environment="test", mock_external_services=True))

    assert isinstance(development.web_reference, SafeHttpWebReferenceProvider)
    assert isinstance(testing.web_reference, MockWebReferenceProvider)


async def test_safe_fetcher_extracts_text_and_ignores_executable_content() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.host == "example.com"
        return httpx.Response(
            200,
            headers={"Content-Type": "text/html; charset=utf-8"},
            text=(
                "<html><head><title>测试网页</title><script>恶意指令</script></head>"
                "<body><nav>菜单</nav><main>周边内容<article><h1>正文标题</h1>"
                "<p>这是网页正文。</p></article></main><footer>页脚</footer></body></html>"
            ),
        )

    provider = SafeHttpWebReferenceProvider(
        transport=httpx.MockTransport(handler), resolver=_public_resolver
    )
    result = await provider.fetch("https://example.com/article")
    assert result.title == "测试网页"
    assert "正文标题" in result.text
    assert "恶意指令" not in result.text
    assert "菜单" not in result.text
    assert "周边内容" not in result.text
    assert "页脚" not in result.text


async def test_safe_fetcher_uses_wechat_article_body_instead_of_guard_page_text() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.host == "mp.weixin.qq.com"
        assert "MicroMessenger" in request.headers["User-Agent"]
        return httpx.Response(
            200,
            headers={"Content-Type": "text/html; charset=utf-8"},
            text=(
                '<html><head><meta property="og:title" content="真实文章标题"></head>'
                "<body><div>页面导航和环境提示不属于正文</div>"
                '<div id="js_content"><img src="cover.png"><br/><script>不要执行</script><p>'
                "这是公众号正文第一段，包含足够多的有效内容用于文章改写。</p>"
                "<p>这是公众号正文第二段，继续提供事实、观点和完整的上下文信息。</p>"
                "<p>这是公众号正文第三段，确保正文长度通过完整性检查并可供模型使用。</p>"
                "</div><div>阅读原文之外的导航</div></body></html>"
            ),
        )

    provider = SafeHttpWebReferenceProvider(
        transport=httpx.MockTransport(handler), resolver=_public_resolver
    )
    result = await provider.fetch("https://mp.weixin.qq.com/s/example")

    assert result.title == "真实文章标题"
    assert "公众号正文第一段" in result.text
    assert "页面导航" not in result.text
    assert "阅读原文之外" not in result.text
    assert "不要执行" not in result.text


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        (
            "https://mp.weixin.qq.com/s/abc-def帮我改写这个文章",
            ["https://mp.weixin.qq.com/s/abc-def"],
        ),
        (
            "参考[原文](https://mp.weixin.qq.com/s?__biz=A%3D%3D&amp;mid=123&sn=abc)。",
            ["https://mp.weixin.qq.com/s?__biz=A%3D%3D&mid=123&sn=abc"],
        ),
        ("<https://example.com/a> 和 https://example.com/a", ["https://example.com/a"]),
        (
            "参考 https://example.com/文章 和 [二](https://example.com/a_(b))",
            ["https://example.com/文章", "https://example.com/a_(b)"],
        ),
        ("没有链接", []),
    ],
)
def test_extract_inline_links(text: str, expected: list[str]) -> None:
    assert extract_message_links(text) == expected


def test_reference_rewrite_intent_and_readable_editor_output() -> None:
    assert (
        classify_run_type("https://mp.weixin.qq.com/s/abc帮我改写", has_current_article=False)
        == "article_generation"
    )
    assert (
        classify_run_type("总结 https://mp.weixin.qq.com/s/abc", has_current_article=False)
        == "summary"
    )
    doc = {
        "type": "doc",
        "content": [{"type": "paragraph", "content": [{"type": "text", "text": "真正的正文"}]}],
    }
    result = ModelResult(json.dumps(doc), doc, 1, 1, "test", False)
    assert readable_model_result(result).text == "真正的正文"
    assert readable_model_result(result).structured == doc
    markdown = ModelResult("**正常回复**", doc, 1, 1, "test", False)
    assert readable_model_result(markdown) == markdown


@pytest.mark.parametrize("target", ["http://127.0.0.1/private", "https://example.com/private"])
async def test_wechat_redirect_rejected_before_requesting_target(target: str) -> None:
    requests: list[str] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        requests.append(str(request.url))
        return httpx.Response(302, headers={"location": target})

    provider = SafeHttpWebReferenceProvider(
        transport=httpx.MockTransport(handler), resolver=_public_resolver
    )
    with pytest.raises(ProviderUnavailable):
        await provider.fetch("https://mp.weixin.qq.com/s/article")
    assert requests == ["https://mp.weixin.qq.com/s/article"]


@pytest.mark.parametrize("intent", ["帮我改写", "总结要点"])
async def test_inline_article_body_reaches_model_before_rewrite(
    app: FastAPI, client: AsyncClient, intent: str
) -> None:
    source = "https://mp.weixin.qq.com/s/source"
    body = "这是实际抓取的文章正文，不是链接，也不是模型编造的说明。" * 8
    calls: list[str] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        calls.append("fetch")
        return httpx.Response(
            200,
            headers={"content-type": "text/html; charset=utf-8"},
            text=f'<html><title>原文</title><div id="js_content">{body}</div></html>',
        )

    class RecordingModel:
        async def generate(self, *, purpose, prompt, context):
            calls.append(purpose)
            if purpose in {
                "intent_detection",
                "article_planning",
                "article_generation",
                "fast_task",
            }:
                assert context["untrusted_documents"][0]["excerpts"][0]["text"] == body
                assert context["untrusted_links"] == [source]
            if purpose in {"article_generation", "fast_task"}:
                assert "已由后端提取正文" in prompt
            doc = {
                "type": "doc",
                "content": [
                    {
                        "type": "paragraph",
                        "content": [
                            {
                                "type": "text",
                                "text": "改写后的真正正文"
                                * (200 if purpose == "article_generation" else 1),
                            }
                        ],
                    }
                ],
            }
            return ModelResult(json.dumps(doc), doc, 10, 10, "recording-test", False)

    app.state.web_reference_provider = SafeHttpWebReferenceProvider(
        transport=httpx.MockTransport(handler), resolver=_public_resolver
    )
    app.state.model_provider = RecordingModel()
    login = await register_and_login(client, "inline-reference@example.com")
    headers = bearer(login["access_token"])
    response = await client.post(
        "/api/v1/tasks",
        headers={**headers, "Idempotency-Key": "inline-reference"},
        json={
            "first_message": {
                "text": f"{source}{intent}",
                "content": {"links": [source]},
                "client_message_id": "inline-reference",
            }
        },
    )
    assert response.status_code == 202, response.text
    assert response.json()["ai_run"]["run_type"] == (
        "article_generation" if intent == "帮我改写" else "summary"
    )
    assert calls[0] == "fetch"
    assert calls.count("fetch") == 1
    assert ("article_generation" if intent == "帮我改写" else "fast_task") in calls
    task = await client.get(f"/api/v1/tasks/{response.json()['task']['id']}", headers=headers)
    if intent == "帮我改写":
        assert task.json()["current_article_id"]
        assert task.json()["messages"][-1]["plain_text"] == "文章已生成，可以打开预览并继续修改。"
    else:
        assert task.json()["current_article_id"] is None
        assert task.json()["messages"][-1]["plain_text"] == "改写后的真正正文"


@pytest.mark.parametrize("failure", ["blocked", "partial", "oversized", "disabled"])
async def test_inline_reference_failure_never_starts_model(
    app: FastAPI, client: AsyncClient, monkeypatch: pytest.MonkeyPatch, failure: str
) -> None:
    from app.domains import ai

    calls: list[str] = []

    class References:
        async def fetch(self, url: str) -> WebReferenceContent:
            calls.append(url)
            if failure == "blocked" or url.endswith("blocked"):
                raise ProviderUnavailable("验证码")
            return WebReferenceContent(
                url,
                url,
                "原文",
                "文章正文" * (20_000 if failure == "oversized" else 20),
                "text/html",
            )

    class NoModel:
        async def generate(self, **kwargs):
            calls.append("MODEL_CALLED")
            raise AssertionError("Failed extraction must not invoke any model")

    if failure == "disabled":
        original = ai.published_setting_section

        async def settings(session, section):
            return (
                {"link_fetch_enabled": False}
                if section == "files"
                else await original(session, section)
            )

        monkeypatch.setattr(ai, "published_setting_section", settings)
    app.state.web_reference_provider = References()
    app.state.model_provider = NoModel()
    login = await register_and_login(client, f"inline-{failure}@example.com")
    text = "总结 https://example.com/article"
    if failure == "partial":
        text += " 和 https://example.com/blocked"
    response = await client.post(
        "/api/v1/tasks",
        headers={**bearer(login["access_token"]), "Idempotency-Key": failure},
        json={"first_message": {"text": text, "content": {}, "client_message_id": failure}},
    )
    assert response.status_code == (403 if failure == "disabled" else 422), response.text
    expected = {
        "disabled": "LINK_FETCH_DISABLED",
        "oversized": "REFERENCE_CONTENT_CONTEXT_LIMIT_EXCEEDED",
    }.get(failure, "REFERENCE_CONTENT_UNAVAILABLE")
    assert response.json()["code"] == expected
    assert "MODEL_CALLED" not in calls
    if failure == "disabled":
        assert calls == []
    async with app.state.database.session_maker() as session:
        assert await session.scalar(select(AIRun)) is None


async def test_article_generation_stops_when_every_reference_fetch_fails(
    app: FastAPI, client: AsyncClient
) -> None:
    class FailingWebReferences:
        async def fetch(self, _url: str):
            raise ProviderUnavailable("blocked")

    original = app.state.web_reference_provider
    app.state.web_reference_provider = FailingWebReferences()
    try:
        login = await register_and_login(client, "failed-web-reference@example.com")
        response = await client.post(
            "/api/v1/tasks",
            headers={
                **bearer(login["access_token"]),
                "Idempotency-Key": "failed-web-reference-task",
            },
            json={
                "first_message": {
                    "text": "请参考这个链接改写成一篇完整文章",
                    "content": {
                        "attachments": [
                            {
                                "id": "failed-reference-attachment",
                                "name": "公众号原文",
                                "kind": "link",
                                "url": "https://mp.weixin.qq.com/s/blocked",
                            }
                        ]
                    },
                    "client_message_id": "failed-web-reference-message",
                }
            },
        )
    finally:
        app.state.web_reference_provider = original

    assert response.status_code == 422
    assert response.json()["code"] == "REFERENCE_CONTENT_UNAVAILABLE"


async def test_safe_fetcher_rejects_private_network_targets() -> None:
    async def private_resolver(_hostname: str) -> list[str]:
        return ["127.0.0.1"]

    provider = SafeHttpWebReferenceProvider(resolver=private_resolver)
    with pytest.raises(ProviderUnavailable, match="not public"):
        await provider.fetch("http://internal.example/admin")


async def test_task_fetches_and_persists_link_body_and_original_url(
    app: FastAPI, client: AsyncClient
) -> None:
    login = await register_and_login(client, "web-reference@example.com")
    headers = bearer(login["access_token"])
    source_url = "https://example.com/reference"
    created = await client.post(
        "/api/v1/tasks",
        headers={**headers, "Idempotency-Key": "web-reference-task"},
        json={
            "first_message": {
                "text": "参考这个网页写一篇行业观察文章",
                "content": {
                    "attachments": [
                        {
                            "id": "web-reference-attachment",
                            "name": "网页参考",
                            "kind": "link",
                            "url": source_url,
                            "save_to_library": True,
                        }
                    ]
                },
                "client_message_id": "web-reference-message",
            }
        },
    )
    assert created.status_code == 202, created.text
    snapshot = created.json()["ai_run"]["context_snapshot"]
    assert snapshot["untrusted_links"] == [source_url]
    web_context = next(
        item for item in snapshot["untrusted_documents"] if item.get("source_url") == source_url
    )
    assert web_context["fetch_status"] == "completed"
    assert "模拟网页正文" in web_context["excerpts"][0]["text"]

    async with app.state.database.session_maker() as session:
        document = await session.scalar(select(Document).where(Document.source_type == "web"))
        assert document is not None
        assert "模拟网页正文" in (document.extracted_text or "")
        asset = await session.get(Asset, document.asset_id)
        assert asset is not None
        storage = app.state.storage_provider
        assert isinstance(storage, MockStorageProvider)
        stored_body = storage.object_bytes(asset.object_key)
        assert stored_body is not None
        assert "模拟网页正文" in stored_body.decode()
        assert await storage.verify_object(
            object_key=asset.object_key,
            size_bytes=asset.size_bytes,
            sha256=asset.sha256,
        )
        section = await session.scalar(
            select(DocumentSection).where(DocumentSection.document_id == document.id)
        )
        assert section is not None
        assert section.data["source_url"] == source_url
        library_item = await session.scalar(
            select(LibraryItem).where(LibraryItem.source_id == document.id)
        )
        assert library_item is not None
