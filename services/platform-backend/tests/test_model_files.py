from __future__ import annotations

import hashlib
import json
import time
from pathlib import Path

import httpx
import pytest
from fastapi import FastAPI

from app.domains.ai import freeze_file_extraction_route
from app.errors import ApiError
from app.model_files import (
    _moonshot_file_purpose,
    conversation_file_ids,
    file_input_route,
    moonshot_file_endpoint,
    prepare_model_files,
    upload_manus_file,
    upload_moonshot_file,
)
from app.models import (
    AIRun,
    Asset,
    Document,
    Message,
    ModelDeployment,
    ModelProviderRecord,
    Task,
    User,
)
from app.production_providers import ManusModelProvider, OpenAICompatibleModelProvider
from app.providers import EnvironmentSecretProvider, MockStorageProvider, ProviderUnavailable


async def test_manus_original_file_is_attached_to_task(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    original = b"%PDF-1.4 original-user-document"
    calls: list[str] = []
    detail_polls = 0

    async def no_sleep(_: float) -> None:
        return None

    monkeypatch.setattr("app.model_files.asyncio.sleep", no_sleep)

    def respond(request: httpx.Request) -> httpx.Response:
        nonlocal detail_polls
        calls.append(request.method + " " + request.url.path)
        if request.url.path.endswith("file.upload"):
            assert json.loads(request.content)["filename"] == "reference.pdf"
            return httpx.Response(
                200,
                json={
                    "file": {"id": "file_original"},
                    "upload_url": "https://test-bucket.s3.amazonaws.com/original",
                },
            )
        if request.method == "PUT":
            assert request.content == original
            assert request.headers["content-type"] == "application/pdf"
            assert "x-manus-api-key" not in request.headers
            assert "authorization" not in request.headers
            return httpx.Response(200)
        if request.url.path.endswith("file.detail"):
            detail_polls += 1
            if detail_polls <= 10:
                return httpx.Response(200, json={"file": {"status": "pending"}})
            return httpx.Response(200, json={"file": {"status": "uploaded"}})
        if request.url.path.endswith("task.create"):
            parts = json.loads(request.content)["message"]["content"]
            assert {"type": "file", "file_id": "file_original"} in parts
            return httpx.Response(200, json={"task_id": "task_test"})
        return httpx.Response(
            200,
            json={
                "status": "completed",
                "messages": [{"role": "assistant", "content": "read"}],
            },
        )

    transport = httpx.MockTransport(respond)
    async with httpx.AsyncClient(transport=transport) as client:
        identifier = await upload_manus_file(
            client,
            api_base="https://api.manus.ai",
            headers={"x-manus-api-key": "test"},
            filename="reference.pdf",
            mime_type="application/pdf",
            content=original,
        )
    model = ManusModelProvider(
        api_base="https://api.manus.ai",
        api_key="test",
        agent_profile="lite",
        transport=transport,
    )
    file = {
        "delivery": "manus_files_api",
        "base_url": "https://api.manus.ai",
        "provider_file_id": identifier,
        "uploaded_at": time.time(),
    }
    assert (
        await model.generate(
            purpose="conversation",
            prompt="读取附件",
            context={"untrusted_model_files": [file]},
        )
    ).text == "read"
    assert calls[:2] == ["POST /v2/file.upload", "PUT /original"]
    assert detail_polls == 11
    file["base_url"] = "https://api.moonshot.cn/v1"
    before = len(calls)
    with pytest.raises(ProviderUnavailable):
        await model.generate(
            purpose="conversation", prompt="test", context={"untrusted_model_files": [file]}
        )
    assert len(calls) == before


@pytest.mark.parametrize(
    "destination",
    [
        "http://test.s3.amazonaws.com/file",
        "https://127.0.0.1/file",
        "https://s3.amazonaws.com.attacker.test/file",
    ],
)
async def test_manus_rejects_unsafe_upload_destinations(destination: str) -> None:
    def respond(request: httpx.Request) -> httpx.Response:
        assert request.method == "POST"
        return httpx.Response(200, json={"file": {"id": "file_test"}, "upload_url": destination})

    async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
        with pytest.raises(ProviderUnavailable):
            await upload_manus_file(
                client,
                api_base="https://api.manus.ai",
                headers={},
                filename="a.pdf",
                mime_type="application/pdf",
                content=b"original",
            )


def test_file_routes_are_provider_protocols_not_display_names() -> None:
    assert (
        file_input_route(
            {"adapter": "manus_v2", "base_url": "https://api.manus.ai/", "model_id": "lite"}
        )[0]
        == "manus_files_api"
    )
    assert (
        file_input_route(
            {"adapter": "manus_v2", "base_url": "https://api.manus.ai/", "model_id": "standard"}
        )[0]
        == "manus_files_api"
    )
    with pytest.raises(ApiError) as error:
        file_input_route(
            {
                "adapter": "openai_chat_completions",
                "base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1",
                "model_id": "qwen3.7-flash",
            }
        )
    assert error.value.code == "MODEL_FILE_INPUT_UNSUPPORTED"
    assert "管理端已配置" in error.value.message
    assert all(name not in error.value.message for name in ("Kimi", "Manus", "Qwen"))


async def test_file_extraction_route_discovers_enabled_protocol_not_model_name(
    app: FastAPI,
) -> None:
    async with app.state.database.session_maker() as session:
        file_provider = ModelProviderRecord(
            id="file-provider",
            code="renamable-file-provider",
            name="任意显示名称",
            adapter="manus_v2",
            base_url="https://api.manus.ai",
            secret_ref="env:FILE_PROVIDER_KEY",
            status="active",
        )
        text_provider = ModelProviderRecord(
            id="text-provider",
            code="renamable-text-provider",
            name="另一个任意名称",
            adapter="openai_chat_completions",
            base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
            secret_ref="env:TEXT_PROVIDER_KEY",
            status="active",
        )
        session.add_all([file_provider, text_provider])
        await session.flush()
        file_model = ModelDeployment(
            id="file-deployment",
            provider_id=file_provider.id,
            model_id="changeable-file-model-id",
            alias="可以改名的文件模型",
            model_type="chat",
            capabilities=[],
            context_window=100_000,
            max_output_tokens=16_384,
            input_cost=0,
            output_cost=0,
            status="available",
        )
        text_model = ModelDeployment(
            id="text-deployment",
            provider_id=text_provider.id,
            model_id="changeable-text-model-id",
            alias="可以改名的创作模型",
            model_type="chat",
            capabilities=[],
            context_window=100_000,
            max_output_tokens=16_384,
            input_cost=0,
            output_cost=0,
            status="available",
        )
        session.add_all([file_model, text_model])
        await session.flush()

        route = await freeze_file_extraction_route(session, settings=app.state.settings)

        assert route["purpose"] == "file_extraction"
        assert route["primary_deployment_id"] == file_model.id


async def test_original_bytes_uploaded_then_full_content_reaches_model() -> None:
    original = b"%PDF-1.4\noriginal-pdf-bytes-test"
    requests: list[str] = []
    full_text = "文件里的唯一信息：测试编号 FILE-7429。" * 30

    def respond(request: httpx.Request) -> httpx.Response:
        requests.append(request.method + " " + request.url.path)
        if request.url.path == "/v1/files":
            assert original in request.content
            assert b"file-extract" in request.content
            assert b"reference.pdf" in request.content
            return httpx.Response(200, json={"id": "file_test"})
        if request.url.path.endswith("/content"):
            return httpx.Response(200, text=full_text)
        if request.method == "DELETE":
            return httpx.Response(200, json={"deleted": True})
        payload = json.loads(request.content)
        assert full_text in payload["messages"][1]["content"]
        assert "file_test" in payload["messages"][1]["content"]
        return httpx.Response(200, json={"choices": [{"message": {"content": "FILE-7429"}}]})

    transport = httpx.MockTransport(respond)
    identifier, extracted = await upload_moonshot_file(
        base="https://api.moonshot.cn/v1",
        key="test-only",
        filename="reference.pdf",
        mime_type="application/pdf",
        content=original,
        purpose="file-extract",
        transport=transport,
    )
    model = OpenAICompatibleModelProvider(
        api_base="https://api.moonshot.cn/v1",
        api_key="test-only",
        model="kimi-test",
        api_style="chat_completions",
        transport=transport,
    )
    result = await model.generate(
        purpose="conversation",
        prompt="回答文件编号",
        context={
            "untrusted_model_files": [
                {
                    "base_url": "https://api.moonshot.cn/v1",
                    "provider_file_id": identifier,
                    "content": extracted,
                }
            ]
        },
    )
    assert result.text == "FILE-7429"
    assert requests == [
        "POST /v1/files",
        "GET /v1/files/file_test/content",
        "POST /v1/chat/completions",
    ]


async def test_moonshot_image_upload_does_not_request_extracted_content() -> None:
    image = b"PNGFAKE"
    requests: list[str] = []

    def respond(request: httpx.Request) -> httpx.Response:
        requests.append(request.method + " " + request.url.path)
        if request.url.path == "/v1/files":
            body = request.content
            assert b'name="purpose"' in body
            assert b"\r\nimage\r\n" in body
            assert b'image.png' in body
            return httpx.Response(200, json={"id": "img_001"})
        if request.url.path.endswith("/content"):
            raise AssertionError("图片文件不应触发官方 /content 获取")
        raise AssertionError(f"unexpected request {request.method} {request.url}")

    identifier, extracted = await upload_moonshot_file(
        base="https://api.moonshot.cn/v1",
        key="test-only",
        filename="image.png",
        mime_type="image/png",
        content=image,
        purpose="image",
        transport=httpx.MockTransport(respond),
    )
    assert identifier == "img_001"
    assert extracted == ""
    assert requests == ["POST /v1/files"]


async def test_moonshot_upload_reports_provider_limit_instead_of_generic_transfer_error() -> None:
    def respond(_: httpx.Request) -> httpx.Response:
        return httpx.Response(
            429,
            json={
                "error": {
                    "type": "exceeded_current_quota_error",
                    "message": "Quota suspended or budget exhausted.",
                }
            },
        )

    with pytest.raises(ApiError) as error:
        await upload_moonshot_file(
            base="https://api.moonshot.cn/v1",
            key="test-only",
            filename="large.pptx",
            mime_type="application/vnd.openxmlformats-officedocument.presentationml.presentation",
            content=b"pptx",
            purpose="file-extract",
            transport=httpx.MockTransport(respond),
        )

    assert error.value.status_code == 429
    assert error.value.code == "MODEL_FILE_PROVIDER_LIMITED"
    assert error.value.retryable is True


async def test_moonshot_upload_accepts_nested_file_id_field() -> None:
    def respond(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/v1/files":
            return httpx.Response(200, json={"file": {"id": "nested_001"}})
        if request.url.path.endswith("/content"):
            return httpx.Response(200, text="ok")
        raise AssertionError(f"unexpected request {request.method} {request.url}")

    identifier, extracted = await upload_moonshot_file(
        base="https://api.moonshot.cn/v1",
        key="test-only",
        filename="notes.txt",
        mime_type="text/plain",
        content=b"hello",
        purpose="file-extract",
        transport=httpx.MockTransport(respond),
    )
    assert identifier == "nested_001"
    assert extracted == "ok"


@pytest.mark.parametrize(
    "base",
    [
        "https://example.com/v1",
        "http://api.moonshot.cn/v1",
        "https://api.moonshot.cn.attacker.test/v1",
    ],
)
def test_unsupported_channels_never_receive_files(base: str) -> None:
    with pytest.raises(ApiError) as error:
        moonshot_file_endpoint({"adapter": "openai_chat_completions", "base_url": base})
    assert error.value.code == "MODEL_FILE_INPUT_UNSUPPORTED"


async def test_empty_official_extraction_fails_without_writing_article() -> None:
    def respond(request: httpx.Request) -> httpx.Response:
        if request.method == "POST":
            return httpx.Response(200, json={"id": "file_empty"})
        return httpx.Response(200, text="")

    with pytest.raises(ApiError) as error:
        await upload_moonshot_file(
            base="https://api.moonshot.cn/v1",
            key="test-only",
            filename="empty.pdf",
            mime_type="application/pdf",
            content=b"test",
            purpose="file-extract",
            transport=httpx.MockTransport(respond),
        )
    assert error.value.code == "MODEL_FILE_CONTENT_EMPTY"


async def test_development_original_files_survive_restart_and_delete(tmp_path: Path) -> None:
    content = b"original file"
    storage = MockStorageProvider(persistence_dir=tmp_path)
    await storage.put_bytes(
        object_key="owner/file",
        content=content,
        mime_type="text/plain",
        sha256=hashlib.sha256(content).hexdigest(),
    )
    restarted = MockStorageProvider(persistence_dir=tmp_path)
    assert await restarted.read_bytes(object_key="owner/file", max_bytes=100) == content
    await restarted.delete_object(object_key="owner/file")
    assert storage.object_bytes("not-there") is None
    assert MockStorageProvider(persistence_dir=tmp_path).object_bytes("owner/file") is None


async def test_followup_reuses_official_content_and_checks_owner(
    app: FastAPI,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async with app.state.database.session_maker() as session:
        session.add(User(id="owner", display_name="Owner", password_hash="test"))
        await session.flush()
        session.add(Task(id="task", owner_id="owner", title="File chat"))
        session.add(
            Asset(
                id="asset",
                owner_id="owner",
                filename="reference.pdf",
                mime_type="application/pdf",
                size_bytes=10,
                sha256="hash",
                object_key="object",
                scan_status="clean",
            )
        )
        await session.flush()
        session.add(Document(id="document", owner_id="owner", asset_id="asset", title="PDF"))
        session.add(
            Message(
                id="message",
                task_id="task",
                role="user",
                plain_text="写文章",
                content_json={"document_ids": ["document"]},
            )
        )
        file = {
            "document_id": "document",
            "sha256": "hash",
            "provider_id": "provider",
            "base_url": "https://api.moonshot.cn/v1",
            "provider_file_id": "file_prior",
            "content": "Complete official file content",
            "provider_file_purpose": "file-extract",
            "delivery": "moonshot_files_api",
        }
        session.add(
            AIRun(
                id="prior",
                owner_id="owner",
                task_id="task",
                idempotency_key="prior",
                context_snapshot={"untrusted_model_files": [file]},
            )
        )
        await session.flush()
        ids = await conversation_file_ids(session, task_id="task", content={})
        assert ids == ["document"]
        config = {
            "base_url": "https://api.moonshot.cn/v1",
            "adapter": "openai_chat_completions",
            "provider_id": "provider",
        }
        result = await prepare_model_files(
            session,
            owner_id="owner",
            task_id="task",
            document_ids=ids,
            config=config,
            storage=MockStorageProvider(),
            secrets=EnvironmentSecretProvider(),
            max_characters=1000,
        )
        assert result == [
            file
        ]  # No original bytes or credentials needed for a same-provider followup.
        with pytest.raises(ApiError) as error:
            await prepare_model_files(
                session,
                owner_id="other",
                task_id="task",
                document_ids=ids,
                config=config,
                storage=MockStorageProvider(),
                secrets=EnvironmentSecretProvider(),
                max_characters=1000,
            )
        assert error.value.code == "DOCUMENT_NOT_FOUND"
        long_files = await prepare_model_files(
            session,
            owner_id="owner",
            task_id="task",
            document_ids=ids,
            config=config,
            storage=MockStorageProvider(),
            secrets=EnvironmentSecretProvider(),
            max_characters=1,
        )
        assert len(long_files[0]["content"]) > 1  # Full source reaches worker map/reduce.
        # Changing provider carries the selected document, but uploads original bytes again.
        original = b"%PDF-1.4 original"
        asset = await session.get(Asset, "asset")
        assert asset is not None
        asset.size_bytes = len(original)
        asset.sha256 = hashlib.sha256(original).hexdigest()
        await session.flush()
        storage = MockStorageProvider()
        await storage.put_bytes(
            object_key="object",
            content=original,
            mime_type="application/pdf",
            sha256=asset.sha256,
        )
        received: list[bytes] = []

        async def upload(client: httpx.AsyncClient, **kwargs: object) -> str:
            assert kwargs["api_base"] == "https://api.manus.ai"
            assert kwargs["content"] == original
            received.append(original)
            return "manus_new_file"

        monkeypatch.setattr("app.model_files.upload_manus_file", upload)
        monkeypatch.setenv("TEST_FILE_API_KEY", "test-only")
        switched = await prepare_model_files(
            session,
            owner_id="owner",
            task_id="task",
            document_ids=ids,
            config={
                "base_url": "https://api.manus.ai",
                "adapter": "manus_v2",
                "provider_id": "manus",
                "secret_ref": "env:TEST_FILE_API_KEY",
            },
            storage=storage,
            secrets=EnvironmentSecretProvider(),
            max_characters=1000,
        )
        assert received == [original]
        assert switched[0]["provider_file_id"] == "manus_new_file"
        assert switched[0]["delivery"] == "manus_files_api"
        assert switched[0]["content"] == ""
        assert "file_prior" not in json.dumps(switched)


async def test_image_document_routes_to_moonshot_image_purpose(
    app: FastAPI,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async with app.state.database.session_maker() as session:
        session.add(User(id="owner", display_name="Owner", password_hash="test"))
        await session.flush()
        session.add(Task(id="task", owner_id="owner", title="Image chat"))
        await session.flush()
        raw = b"\x89PNG\r\n\x1a\nfake"
        session.add(
            Asset(
                id="asset",
                owner_id="owner",
                filename="cover.png",
                mime_type="image/png",
                size_bytes=len(raw),
                sha256=hashlib.sha256(raw).hexdigest(),
                object_key="object",
                scan_status="clean",
            )
        )
        await session.flush()
        session.add(Document(id="doc", owner_id="owner", asset_id="asset", title="封面"))
        await session.flush()

        storage = MockStorageProvider()
        await storage.put_bytes(
            object_key="object",
            content=raw,
            mime_type="image/png",
            sha256=hashlib.sha256(raw).hexdigest(),
        )

        async def upload(
            *,
            base: str,
            key: str,
            filename: str,
            mime_type: str,
            content: bytes,
            purpose: str,
            transport: httpx.AsyncBaseTransport | None = None,
        ) -> tuple[str, str]:
            assert purpose == "image"
            assert base == "https://api.moonshot.cn/v1"
            assert key == "test-only"
            return "img_file", ""

        monkeypatch.setenv("TEST_FILE_API_KEY", "test-only")
        monkeypatch.setattr("app.model_files.upload_moonshot_file", upload)
        result = await prepare_model_files(
            session,
            owner_id="owner",
            task_id="task",
            document_ids=["doc"],
            config={
                "base_url": "https://api.moonshot.cn/v1",
                "adapter": "openai_chat_completions",
                "provider_id": "provider",
                "secret_ref": "env:TEST_FILE_API_KEY",
            },
            storage=storage,
            secrets=EnvironmentSecretProvider(),
            max_characters=1000,
        )
        assert result[0]["provider_file_purpose"] == "image"
        assert result[0]["content"] == ""
        assert result[0].get("remote_copy") is None


def test_moonshot_file_purpose_prefers_document_extraction_for_text_like_types(
) -> None:
    assert _moonshot_file_purpose("report.py", "text/x-python") == "file-extract"
    assert (
        _moonshot_file_purpose(
            "slides.pptx",
            "application/vnd.openxmlformats-officedocument.presentationml.presentation",
        )
        == "file-extract"
    )
    assert _moonshot_file_purpose("chart.svg", "image/svg+xml") == "file-extract"
    assert _moonshot_file_purpose("scan.bmp", "image/bmp") == "file-extract"
    assert _moonshot_file_purpose("clip.mp4", "video/mp4") == "video"


async def test_svg_document_uses_file_extract_instead_of_visual_image_purpose(
    app: FastAPI,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async with app.state.database.session_maker() as session:
        session.add(User(id="owner", display_name="Owner", password_hash="test"))
        await session.flush()
        session.add(Task(id="task", owner_id="owner", title="SVG chat"))
        await session.flush()
        raw = b"<svg><text>bad</text></svg>"
        session.add(
            Asset(
                id="asset",
                owner_id="owner",
                filename="chart.svg",
                mime_type="image/svg+xml",
                size_bytes=len(raw),
                sha256=hashlib.sha256(raw).hexdigest(),
                object_key="object",
                scan_status="clean",
            )
        )
        await session.flush()
        session.add(Document(id="doc", owner_id="owner", asset_id="asset", title="vector"))
        await session.flush()

        storage = MockStorageProvider()
        await storage.put_bytes(
            object_key="object",
            content=raw,
            mime_type="image/svg+xml",
            sha256=hashlib.sha256(raw).hexdigest(),
        )
        monkeypatch.setenv("TEST_FILE_API_KEY", "test-only")

        async def upload(
            *,
            base: str,
            key: str,
            filename: str,
            mime_type: str,
            content: bytes,
            purpose: str,
            transport: httpx.AsyncBaseTransport | None = None,
        ) -> tuple[str, str]:
            assert purpose == "file-extract"
            return "svg_file", "bad"

        monkeypatch.setattr("app.model_files.upload_moonshot_file", upload)
        result = await prepare_model_files(
            session,
            owner_id="owner",
            task_id="task",
            document_ids=["doc"],
            config={
                "base_url": "https://api.moonshot.cn/v1",
                "adapter": "openai_chat_completions",
                "provider_id": "provider",
                "secret_ref": "env:TEST_FILE_API_KEY",
            },
            storage=storage,
            secrets=EnvironmentSecretProvider(),
            max_characters=1000,
        )
        assert result[0]["provider_file_purpose"] == "file-extract"
        assert result[0]["content"] == "bad"
