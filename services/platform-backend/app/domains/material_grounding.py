"""Collect reference text for user-requested style statistics."""

from __future__ import annotations

import re
from typing import Any


def material_sources(
    context: dict[str, Any], *, chunk_characters: int = 6000
) -> list[dict[str, Any]]:
    """Keep supplied text and real locators; never invent PDF page numbers."""
    sources: list[dict[str, Any]] = []
    seen: set[str] = set()

    def add(text: Any, locator: dict[str, Any]) -> None:
        if not isinstance(text, str) or not text.strip() or text in seen:
            return
        seen.add(text)
        # ponytail: bounded exact-text chunks; use parser paragraph boundaries if needed later.
        for offset in range(0, len(text), chunk_characters):
            sources.append({
                "id": f"s{len(sources) + 1:04d}",
                "text": text[offset:offset + chunk_characters],
                "locator": {**locator, "character_offset": offset},
            })

    for document in context.get("untrusted_documents", []):
        for excerpt in document.get("excerpts", []):
            add(excerpt.get("text"), {
                "document_id": document.get("document_id"),
                "title": document.get("title"),
                "source_url": document.get("source_url"),
                **{key: excerpt.get(key) for key in (
                    "chunk_id", "chunk_no", "page_no", "section_id", "section_title"
                )},
            })
    for item in context.get("untrusted_extracted_files", []):
        add(item.get("text"), {"title": item.get("title"), "kind": "extracted_text"})
    for item in context.get("untrusted_model_files", []):
        add(item.get("content"), {
            "document_id": item.get("document_id"), "title": item.get("filename"),
            "kind": "provider_extracted_text",
        })
    request = str(context.get("untrusted_user_input") or "")
    pasted = re.search(r"(?:资料|原文|素材|参考内容|参考文本)\s*[:：]\s*([\s\S]+)", request)
    if pasted:
        add(pasted.group(1), {"kind": "pasted_text", "message_offset": pasted.start(1)})
    elif not sources and "\n" in request and len(request) >= 300 and re.search(
        r"(?:根据|依据|参考|基于).{0,12}(?:以下|下面|上述|资料|素材|原文)", request
    ):
        add(request, {"kind": "mixed_user_message"})
    return sources

