import json

import pytest

from app.domains.ai import (
    article_output_contract,
    generated_article_content,
    generated_article_message,
    strip_unrequested_article_byline,
)
from app.errors import ApiError
from app.production_providers import _structured_output

DOC = {
    "type": "doc",
    "content": [
        {
            "type": "heading",
            "attrs": {"level": 1},
            "content": [{"type": "text", "text": "独立标题"}],
        },
        {"type": "paragraph", "content": [{"type": "text", "text": "完整正文"}]},
    ],
}


@pytest.mark.parametrize("encoding", ["plain", "fenced", "double", "wrapped"])
def test_model_document_serialization_is_not_article_prose(encoding):
    text = json.dumps(DOC, ensure_ascii=False)
    if encoding == "fenced":
        text = f"```json\n{text}\n```"
    elif encoding == "double":
        text = json.dumps(text)
    elif encoding == "wrapped":
        text = json.dumps(
            {
                "type": "doc",
                "content": [{"type": "paragraph", "content": [{"type": "text", "text": text}]}],
            }
        )
    assert generated_article_content(_structured_output(text)) == DOC


@pytest.mark.parametrize(
    "text",
    [
        json.dumps(DOC) + ',{"type":"heading","content":[]}]}',
        '{"type":"doc","content":[',
        '```json\n{"type":"doc","content":[\n```',
    ],
)
def test_broken_document_requires_repair_instead_of_plaintext_fallback(text):
    # Reproduces v4: a premature root closing, followed by more article nodes.
    with pytest.raises(ApiError, match="JSON"):
        generated_article_content(_structured_output(text))


def test_normal_prose_and_explicit_code_examples_are_unchanged():
    doc = _structured_output("普通文章包含 JSON 示例，不是序列化文档。")
    assert generated_article_content(doc) == doc
    code = {
        "type": "doc",
        "content": [{"type": "codeBlock", "content": [{"type": "text", "text": json.dumps(DOC)}]}],
    }
    assert generated_article_content(code) == code


def test_article_envelope_separates_chat_message_from_preview_document():
    payload = {
        "assistant_message": "已按你的要求调整，下面是更新后的文章。",
        "article": DOC,
    }
    structured = _structured_output(json.dumps(payload, ensure_ascii=False), article_output=True)

    assert generated_article_message(structured) == payload["assistant_message"]
    assert generated_article_content(structured) == DOC
    assert payload["assistant_message"] not in json.dumps(
        generated_article_content(structured), ensure_ascii=False
    )


def test_plain_explanation_cannot_be_saved_as_an_article():
    structured = _structured_output("这行是对生成结果的解释，不是文章正文。", article_output=True)

    with pytest.raises(ApiError, match="文章"):
        generated_article_content(structured)


def test_unrequested_leading_byline_is_silently_removed():
    byline = {"type": "paragraph", "content": [{"type": "text", "text": "作者｜蓝血创作组"}]}
    document = {"type": "doc", "content": [DOC["content"][0], byline, DOC["content"][1]]}

    cleaned = strip_unrequested_article_byline(
        document,
        {"untrusted_user_input": "根据这个PPT写一篇公众号文章"},
    )

    assert cleaned == DOC
    assert document["content"][1] == byline
    assert "署名元数据" in article_output_contract()


def test_explicit_body_byline_request_is_preserved():
    byline = {"type": "paragraph", "content": [{"type": "text", "text": "作者：张三"}]}
    document = {"type": "doc", "content": [DOC["content"][0], byline, DOC["content"][1]]}

    assert (
        strip_unrequested_article_byline(
            document,
            {"untrusted_user_input": "请在标题下添加作者署名"},
        )
        == document
    )
