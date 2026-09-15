"""Task-specific context budgets and lightweight source checks, without another agent."""

import re
from typing import Any

from app.domains.article import extract_plain_text


def context_weights(run_type: str, has_article: bool, local: bool) -> dict[str, float]:
    if local:
        return {"documents": 0.10, "article": 0.60, "messages": 0.15, "styles": 0.08}
    if run_type == "article_generation" and has_article:
        return {"documents": 0.25, "article": 0.45, "messages": 0.15, "styles": 0.08}
    if run_type in {"summary", "outline"}:
        return {"documents": 0.60, "article": 0.15, "messages": 0.12, "styles": 0.05}
    if run_type in {"discussion", "titles"}:
        return {"documents": 0.25, "article": 0.20, "messages": 0.40, "styles": 0.05}
    return {"documents": 0.52, "article": 0.0, "messages": 0.22, "styles": 0.10}


def clean_delivery_blocks(document: dict[str, Any], request: str) -> dict[str, Any]:
    if re.search(r"保留.{0,10}(?:说明|原文)|逐字|原样", request):
        return document
    nodes = list(document.get("content", []))
    kept = []
    for index, node in enumerate(nodes):
        text = extract_plain_text(node).strip()
        boundary = index <= 1 or index == len(nodes) - 1
        if (
            boundary
            and node.get("type") == "paragraph"
            and len(text) <= 100
            and re.fullmatch(
                r"(?:以下(?:是|为).{0,30}(?:文章|正文)[：:。]?|"
                r"如需(?:调整|修改|补充).{0,70}|根据用户要求[，,].{0,40})",
                text,
            )
        ):
            continue
        kept.append(node)
    return {**document, "content": kept}


def source_findings(document: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
    sources: list[tuple[str, str]] = []
    current = context.get("current_article")
    if isinstance(current, dict) and current.get("plain_text"):
        sources.append(("current_article", str(current["plain_text"])))
    for item in context.get("untrusted_documents", []):
        if not isinstance(item, dict):
            continue
        source_id = str(item.get("document_id") or item.get("source_url") or "reference")
        for excerpt in item.get("excerpts", []):
            if isinstance(excerpt, dict):
                sources.append((source_id, str(excerpt.get("text") or "")))
    for item in context.get("untrusted_extracted_files", []):
        if isinstance(item, dict):
            sources.append((str(item.get("title") or "file"), str(item.get("text") or "")))
    if not sources:
        return {"status": "no_text_sources", "matched": [], "unmatched": []}
    text = extract_plain_text(document)
    facts = list(
        dict.fromkeys(
            re.findall(r"\d+(?:\.\d+)?(?:%|％|亿元|万元|万人|亿|万|年|月|日|人|倍)", text)
        )
    )[:60]
    # Direct quotations only; ordinary rhetorical quotes are not factual citations.
    facts += re.findall(r"(?:表示|指出|说|写道)[：:，,]?\s*[“\"]([^”\"]{8,100})[”\"]", text)[:20]
    matched, unmatched = [], []
    for fact in facts:
        ids = [source_id for source_id, value in sources if fact in value]
        if ids:
            matched.append({"fact": fact, "sources": list(dict.fromkeys(ids))})
        elif fact not in str(context.get("untrusted_user_input") or ""):
            unmatched.append(fact)
    return {
        "status": "review_needed" if unmatched else "matched",
        "matched": matched,
        "unmatched": unmatched,
    }
