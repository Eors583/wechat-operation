import copy

import pytest

from app.errors import ApiError
from app.long_context import (
    _split_text_to_budget,
    encoded_size,
    fit_context,
    requires_local_compaction,
    summary_prompt,
)


def test_summary_prompt_has_explicit_limit_and_retry_policy():
    part = {"max_summary_characters": 128}
    assert "最多128个字符" in summary_prompt(part)
    assert "最多写5条" not in summary_prompt(part)
    assert "最多写5条" in summary_prompt({**part, "compression_retry": 1})


def test_text_chunks_fill_the_real_encoded_byte_budget_without_losing_content():
    source = ("华为闭环战略管理。\n" * 8_000) + "末页结论"

    chunks = _split_text_to_budget(source, 6_144)

    assert "".join(chunks) == source
    assert all(encoded_size(chunk) <= 6_144 for chunk in chunks)
    assert len(chunks) < 50


def test_manus_uses_its_native_context_file_instead_of_local_compaction():
    assert not requires_local_compaction(
        {"execution_configs": [{"adapter": "manus_v2", "model_id": "lite"}]}
    )
    assert requires_local_compaction(
        {"execution_configs": [{"adapter": "openai_chat_completions", "model_id": "kimi-k2.6"}]}
    )


async def test_full_source_coverage_budget_original_and_cache():
    source = "完整资料包含论点和数据。" * 1000 + "最后一页独有结论"
    context = {
        "untrusted_model_files": [{"content": source, "filename": "资料.pdf"}],
        "preferences": [{"value": "正式专业"}],
    }
    original = copy.deepcopy(context)
    seen = []
    events = []

    async def summarize(part):
        seen.append(part)
        return "资料论点与数据，保留出处"

    async def progress(event):
        events.append(event)

    cache = {}
    result = await fit_context(
        context, budget=8192, summarize=summarize, progress=progress, cache=cache
    )
    assert "".join(p["untrusted_source"] for p in seen) == source
    assert seen[-1]["untrusted_source"].endswith("最后一页独有结论")
    assert encoded_size(result) <= 8192
    assert result["preferences"] == original["preferences"]
    assert context == original
    assert "有损汇总" in result["untrusted_model_files"][0]["content"]
    previous = len(seen)
    await fit_context(context, budget=8192, summarize=summarize, progress=progress, cache=cache)
    assert len(seen) == previous
    assert events[-1]["part"] == events[-1]["total"]


async def test_presentation_sized_source_converges_without_excessive_model_calls():
    source = ("华为闭环战略管理。\n" * 4_000) + "末页独有结论"
    seen = []

    async def summarize(part):
        seen.append(part)
        return "核心结论。" * 50

    async def progress(event):
        pass

    result = await fit_context(
        {"untrusted_model_files": [{"content": source, "filename": "战略管理.pptx"}]},
        budget=8192,
        summarize=summarize,
        progress=progress,
        cache={},
    )

    first_pass = [part for part in seen if "/汇总" not in part["source"]]
    assert "".join(part["untrusted_source"] for part in first_pass) == source
    assert len(seen) <= 30
    assert encoded_size(result) <= 8192


async def test_incomplete_article_is_compressed_as_content_during_completion_retry():
    seen = []

    async def summarize(part):
        seen.append(part)
        return "保留核心事实与文章结构。" * 20

    async def progress(event):
        pass

    result = await fit_context(
        {
            "untrusted_model_files": [{"content": "参考资料" * 2_000}],
            "incomplete_article": {
                "type": "doc",
                "content": [
                    {
                        "type": "paragraph",
                        "content": [{"type": "text", "text": "未完成正文" * 2_000}],
                    }
                ],
            },
        },
        budget=8192,
        summarize=summarize,
        progress=progress,
        cache={},
    )

    assert any(part["source"].startswith("incomplete_article/") for part in seen)
    assert encoded_size(result) <= 8192


async def test_long_pasted_input_and_empty_summary_fail_closed():
    text = "用户粘贴的长文" * 2000

    async def progress(event):
        pass

    async def empty(part):
        return ""

    with pytest.raises(ApiError, match="未能完成"):
        await fit_context(
            {"untrusted_user_input": text},
            budget=8192,
            summarize=empty,
            progress=progress,
            cache={},
        )

    async def summarize(part):
        return "用户要求写作，资料关键事实已归纳"

    result = await fit_context(
        {"untrusted_user_input": text},
        budget=8192,
        summarize=summarize,
        progress=progress,
        cache={},
    )
    assert encoded_size(result) <= 8192


async def test_small_context_does_not_call_model():
    async def unexpected(part):
        raise AssertionError("No summarization for small context")

    context = {"untrusted_user_input": "写一篇文章"}
    assert (
        await fit_context(context, budget=8192, summarize=unexpected, progress=unexpected, cache={})
        is context
    )


async def test_oversized_summary_retries_and_covers_source():
    seen = []

    async def summarize(part):
        seen.append(part)
        return "过长摘要" * 200 if not part["compression_retry"] else "关键事实与结论"

    async def progress(event):
        pass

    source = "正文资料" * 1500
    result = await fit_context(
        {"untrusted_user_input": source},
        budget=8192,
        summarize=summarize,
        progress=progress,
        cache={},
    )
    assert encoded_size(result) <= 8192
    assert any(p["compression_retry"] == 1 for p in seen)
    assert (
        "".join(
            p["untrusted_source"]
            for p in seen
            if not p["compression_retry"] and "/汇总" not in p["source"]
        )
        == source
    )


async def test_large_chunks_avoid_an_unnecessary_reduce_call():
    seen = []

    async def summarize(part):
        seen.append(part)
        return "事实" * 15

    async def progress(event):
        pass

    result = await fit_context(
        {"untrusted_user_input": "A" * 50_000},
        budget=8192,
        summarize=summarize,
        progress=progress,
        cache={},
    )
    assert not [p for p in seen if "/汇总" in p["source"]]
    assert len(seen) < 10
    assert encoded_size(result) <= 8192


async def test_noncompliant_model_stops_after_three_attempts():
    calls = []

    async def summarize(part):
        calls.append(part)
        return part["untrusted_source"] * 2

    async def progress(event):
        pass

    with pytest.raises(ApiError, match="3次"):
        await fit_context(
            {"untrusted_user_input": "长文" * 10_000},
            budget=8192,
            summarize=summarize,
            progress=progress,
            cache={},
        )
    assert len(calls) == 3


async def test_over_target_but_shrinking_notes_continue_reducing():
    calls = []

    async def summarize(part):
        calls.append(part)
        # Simulate a provider missing the requested limit but reducing every input.
        return part["untrusted_source"][: max(1, len(part["untrusted_source"]) * 3 // 5)]

    async def progress(event):
        pass

    result = await fit_context(
        {"untrusted_user_input": "A" * 12_000},
        budget=8192,
        summarize=summarize,
        progress=progress,
        cache={},
    )
    assert encoded_size(result) <= 8192
    assert any(p["compression_retry"] == 2 for p in calls)


async def test_retries_count_toward_later_chunk_work_limit(monkeypatch):
    monkeypatch.setattr("app.long_context.MAX_SUMMARY_CALLS", 12)
    calls = []

    async def summarize(part):
        calls.append(part)
        if "/汇总" not in part["source"] and part["part"] == 1 and part["compression_retry"] < 2:
            return part["untrusted_source"] * 2
        return "关键事实" * 100

    async def progress(event):
        pass

    with pytest.raises(ApiError, match="上限"):
        await fit_context(
            {"untrusted_user_input": "A" * 60_000},
            budget=8192,
            summarize=summarize,
            progress=progress,
            cache={},
        )
    assert len(calls) == 12


async def test_metadata_only_overflow_drops_excess_meta_but_keeps_files():
    model_files = [
        {
            "document_id": f"doc-{index:03d}",
            "filename": f"doc-{index:03d}.pdf",
            "sha256": "a" * 64,
            "provider_id": "provider-x",
            "base_url": "https://api.moonshot.cn",
            "provider_file_id": f"file-{index:03d}",
            "delivery": "moonshot_files_api",
            "credential_fingerprint": "secret-" + ("x" * 32),
            "content": "材料正文" * 40,
            "remote_copy": "provider_expires_48h",
            "uploaded_at": index,
        }
        for index in range(40)
    ]

    documents = [
        {
            "title": f"材料-{index}",
            "source_url": f"https://example.com/doc/{index}",
            "excerpts": [{"text": f"第{index}条短摘要，内容仅作为引用", "source": "extractor"}],
            "fetch_status": "completed",
            "source_characters": 30,
            "metadata": {"size": 30, "page": index},
        }
        for index in range(40)
    ]

    async def summarize(part):
        pytest.fail(f"不应触发正文压缩: {part}")

    async def progress(event):
        pass

    result = await fit_context(
        {
            "untrusted_model_files": model_files,
            "untrusted_documents": documents,
            "untrusted_message_content": {
                "text": "生成一篇文章",
                "attachments": [{"id": "x"}] * 30,
            },
            "project_requirements": "这是一段很长的项目要求" * 100,
            "recent_messages": [
                {"id": f"m{i}", "role": "user", "text": "历史消息" * 20} for i in range(30)
            ],
        },
        budget=6000,
        summarize=summarize,
        progress=progress,
        cache={},
    )

    assert encoded_size(result) <= 6000
    assert len(result["untrusted_model_files"]) <= 8
    assert len(result["untrusted_documents"]) <= 8
    assert result["untrusted_documents"][0]["excerpts"][0]["text"]
    # 非正文元数据应已被压缩为核心字段
    assert result["untrusted_model_files"][0].get("remote_copy") is None
