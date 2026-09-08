import asyncio
import json

import httpx
import pytest

from app.domains.ai import article_output_contract
from app.model_gateway import ModelExecutionAttempt, ModelRouteExhausted
from app.production_providers import OpenAICompatibleModelProvider
from app.providers import ModelContractViolation, ProviderTimeoutError


@pytest.mark.parametrize(
    "purpose", ["intent_detection", "article_planning", "content_check", "article_generation"]
)
async def test_kimi_stage_output_controls(purpose: str) -> None:
    def respond(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        if purpose != "article_generation":
            assert body["thinking"] == {"type": "disabled"}
            assert body["max_tokens"] <= 3072
        else:
            assert body["response_format"] == {"type": "json_object"}
            assert body["thinking"] == {"type": "disabled"}
        return httpx.Response(
            200, json={"choices": [{"message": {"content": "{}"}, "finish_reason": "stop"}]}
        )

    model = OpenAICompatibleModelProvider(
        api_base="https://api.moonshot.cn/v1",
        api_key="test",
        model="kimi-k2.6",
        api_style="chat_completions",
        transport=httpx.MockTransport(respond),
    )
    await model.generate(purpose=purpose, prompt="test", context={})


@pytest.mark.parametrize(
    ("purpose", "expected_limit"),
    [("article_planning", 3072), ("content_check", 256), ("memory_summary", 512)],
)
async def test_qwen_fast_stages_disable_thinking_and_bound_output(
    purpose: str, expected_limit: int
) -> None:
    def respond(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        assert body["enable_thinking"] is False
        assert body["max_tokens"] == expected_limit
        return httpx.Response(
            200,
            json={
                "id": "qwen-stage",
                "choices": [{"message": {"content": "PASS"}, "finish_reason": "stop"}],
            },
        )

    model = OpenAICompatibleModelProvider(
        api_base="https://dashscope.example/compatible-mode/v1",
        api_key="test",
        model="qwen3.7-flash",
        api_style="chat_completions",
        max_output_tokens=8_192,
        transport=httpx.MockTransport(respond),
    )
    await model.generate(purpose=purpose, prompt="test", context={})


async def test_qwen_article_uses_configured_limit_and_json_mode() -> None:
    def respond(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        assert body["enable_thinking"] is False
        assert body["max_tokens"] == 6_000
        assert body["response_format"] == {"type": "json_object"}
        assert "assistant_message" in body["messages"][0]["content"]
        assert "article" in body["messages"][0]["content"]
        return httpx.Response(
            200,
            json={
                "id": "qwen-article",
                "choices": [{"message": {"content": "{}"}, "finish_reason": "stop"}],
            },
        )

    model = OpenAICompatibleModelProvider(
        api_base="https://dashscope.example/compatible-mode/v1",
        api_key="test",
        model="qwen3.7-flash",
        api_style="chat_completions",
        max_output_tokens=6_000,
        transport=httpx.MockTransport(respond),
    )
    await model.generate(purpose="article_generation", prompt="test", context={})


async def test_timeout_is_not_lost_as_generic_connection_failure() -> None:
    def respond(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("test", request=request)

    model = OpenAICompatibleModelProvider(
        api_base="https://api.moonshot.cn/v1",
        api_key="test",
        model="kimi-k2.6",
        api_style="chat_completions",
        transport=httpx.MockTransport(respond),
    )
    with pytest.raises(ProviderTimeoutError):
        await model.generate(purpose="article_planning", prompt="test", context={})


async def test_total_deadline_limits_even_a_transport_without_idle_timeout() -> None:
    async def respond(request: httpx.Request) -> httpx.Response:
        await asyncio.sleep(1)
        return httpx.Response(200, json={})

    model = OpenAICompatibleModelProvider(
        api_base="https://api.moonshot.cn/v1",
        api_key="test",
        model="kimi-k2.6",
        api_style="chat_completions",
        timeout_seconds=0.01,
        transport=httpx.MockTransport(respond),
    )
    with pytest.raises(ProviderTimeoutError):
        await model.generate(purpose="article_generation", prompt="test", context={})


async def test_truncated_output_cannot_be_saved_as_completed_article() -> None:
    model = OpenAICompatibleModelProvider(
        api_base="https://api.moonshot.cn/v1",
        api_key="test",
        model="kimi-k2.6",
        api_style="chat_completions",
        transport=httpx.MockTransport(
            lambda _: httpx.Response(
                200,
                json={
                    "choices": [
                        {"message": {"content": '{"type":"doc"'}, "finish_reason": "length"}
                    ]
                },
            )
        ),
    )
    with pytest.raises(ModelContractViolation) as error:
        await model.generate(purpose="article_generation", prompt="test", context={})
    assert error.value.code == "MODEL_OUTPUT_TRUNCATED"


def test_failure_message_does_not_claim_unattempted_fallback() -> None:
    attempt = ModelExecutionAttempt(
        attempt_no=1,
        deployment_id="kimi",
        status="transient_failed",
        duration_ms=180000,
        purpose="article_planning",
        error_code="ProviderTimeoutError",
    )
    message = ModelRouteExhausted((attempt,)).user_message()
    assert "规划文章" in message and "超时" in message
    assert "已尝试备用模型" not in message


def test_article_prompt_uses_editor_supported_contract() -> None:
    prompt = article_output_contract()
    assert "tableHeader" in prompt and "tableCell" in prompt
    assert "textAlign" in prompt and "白名单" in prompt
    assert "assistant_message" in prompt and "article" in prompt
    assert "只会把 article 字段放入文章预览" in prompt
