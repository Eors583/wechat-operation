from __future__ import annotations

import hashlib
import json
from typing import Any
from urllib.parse import urlparse

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.domains.common import create_job, emit_outbox
from app.domains.user_preference_memory import enqueue_preference_summary
from app.errors import ApiError
from app.models import (
    Article,
    ArticleConfirmation,
    ArticleRender,
    ArticleVersion,
    LayoutTemplate,
    LayoutTemplateVersion,
    LibraryItem,
    Task,
    utcnow,
)

TIPTAP_BLOCK_NODE_TYPES = {
    "table",
    "tableRow",
    "tableCell",
    "tableHeader",
    "paragraph",
    "heading",
    "bulletList",
    "orderedList",
    "listItem",
    "blockquote",
    "hardBreak",
    "horizontalRule",
    "codeBlock",
    "image",
}
TIPTAP_MARK_TYPES = {"bold", "italic", "strike", "code", "link"}
TIPTAP_PARAGRAPH_MODULES = {"lead", "body", "highlight", "caption"}
TIPTAP_NODE_ATTRS = {
    "tableCell": {"colspan", "rowspan", "colwidth"},
    "tableHeader": {"colspan", "rowspan", "colwidth"},
    "paragraph": {"module"},
    "heading": {"level"},
    "orderedList": {"start"},
    "codeBlock": {"language"},
    "image": {"src", "alt", "title", "asset_id"},
}
TIPTAP_LINK_ATTRS = {"href", "target", "rel", "class"}
TIPTAP_DOCUMENT_BLOCKS = {
    "table",
    "paragraph",
    "heading",
    "bulletList",
    "orderedList",
    "blockquote",
    "horizontalRule",
    "codeBlock",
    "image",
}
TIPTAP_ALLOWED_CHILDREN = {
    "table": {"tableRow"},
    "tableRow": {"tableCell", "tableHeader"},
    "tableCell": TIPTAP_DOCUMENT_BLOCKS - {"table"},
    "tableHeader": TIPTAP_DOCUMENT_BLOCKS - {"table"},
    "paragraph": {"text", "hardBreak"},
    "heading": {"text", "hardBreak"},
    "bulletList": {"listItem"},
    "orderedList": {"listItem"},
    "listItem": TIPTAP_DOCUMENT_BLOCKS,
    "blockquote": TIPTAP_DOCUMENT_BLOCKS,
    "codeBlock": {"text"},
}


def normalized_content_hash(content: dict[str, Any]) -> str:
    serialized = json.dumps(content, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(serialized.encode()).hexdigest()


def canonical_article_content(content: dict[str, Any]) -> dict[str, Any]:
    """Return canonical ProseMirror/Tiptap JSON, accepting the legacy direct-text shape."""

    def normalize_node(node: Any, *, is_root: bool = False) -> dict[str, Any]:
        if not isinstance(node, dict) or not isinstance(node.get("type"), str):
            raise ApiError(422, "ARTICLE_CONTENT_INVALID", "文章内容不是有效的编辑器文档。")
        node_type = node["type"]
        allowed_types = {"doc"} if is_root else TIPTAP_BLOCK_NODE_TYPES | {"text"}
        if node_type not in allowed_types:
            raise ApiError(422, "ARTICLE_CONTENT_INVALID", "文章包含不受支持的编辑器节点。")
        normalized: dict[str, Any] = {"type": node_type}
        attrs = node.get("attrs")
        if attrs is not None:
            if not isinstance(attrs, dict):
                raise ApiError(422, "ARTICLE_CONTENT_INVALID", "文章节点属性格式无效。")
            clean_attrs = {key: value for key, value in attrs.items() if value is not None}
            allowed_attrs = TIPTAP_NODE_ATTRS.get(node_type, set())
            if set(clean_attrs) - allowed_attrs:
                raise ApiError(422, "ARTICLE_CONTENT_INVALID", "文章节点包含不受支持的属性。")
            if node_type in {"tableCell", "tableHeader"}:
                # Basic rectangular tables; don't silently flatten merged cells.
                if any(
                    type(clean_attrs.get(key, 1)) is not int or clean_attrs.get(key, 1) != 1
                    for key in ("colspan", "rowspan")
                ):
                    raise ApiError(422, "ARTICLE_CONTENT_INVALID", "当前表格不支持合并单元格。")
                widths = clean_attrs.get("colwidth")
                if widths is not None and (
                    not isinstance(widths, list)
                    or len(widths) != 1
                    or any(type(width) is not int or not 1 <= width <= 2000 for width in widths)
                ):
                    raise ApiError(422, "ARTICLE_CONTENT_INVALID", "表格列宽无效。")
            if node_type == "paragraph" and (
                (module := clean_attrs.get("module")) is not None
                and (not isinstance(module, str) or module not in TIPTAP_PARAGRAPH_MODULES)
            ):
                raise ApiError(422, "ARTICLE_CONTENT_INVALID", "文章段落模块无效。")
            if node_type == "heading" and (
                isinstance((level := clean_attrs.get("level")), bool)
                or not isinstance(level, int)
                or level not in {1, 2, 3}
            ):
                raise ApiError(422, "ARTICLE_CONTENT_INVALID", "文章标题层级无效。")
            if node_type == "orderedList" and (
                isinstance((start := clean_attrs.get("start", 1)), bool)
                or not isinstance(start, int)
                or not 1 <= start <= 1_000_000
            ):
                raise ApiError(422, "ARTICLE_CONTENT_INVALID", "文章有序列表起始值无效。")
            if node_type == "codeBlock" and (
                (language := clean_attrs.get("language")) is not None
                and (not isinstance(language, str) or len(language) > 80)
            ):
                raise ApiError(422, "ARTICLE_CONTENT_INVALID", "文章代码语言属性无效。")
            if node_type == "image":
                source = clean_attrs.get("src")
                asset_id = clean_attrs.get("asset_id")
                if not source:
                    raise ApiError(422, "ARTICLE_CONTENT_INVALID", "文章图片缺少来源。")
                if source is not None:
                    try:
                        parsed_source = urlparse(source) if isinstance(source, str) else None
                        source_host = parsed_source.hostname if parsed_source else None
                    except ValueError:
                        parsed_source = None
                        source_host = None
                    if (
                        not parsed_source
                        or parsed_source.scheme != "https"
                        or not source_host
                        or parsed_source.username
                        or parsed_source.password
                    ):
                        raise ApiError(422, "ARTICLE_CONTENT_INVALID", "文章图片地址无效。")
                for name in {"alt", "title"}:
                    value = clean_attrs.get(name)
                    if value is not None and (not isinstance(value, str) or len(value) > 500):
                        raise ApiError(422, "ARTICLE_CONTENT_INVALID", "文章图片属性无效。")
                if asset_id is not None and (
                    not isinstance(asset_id, str) or not 1 <= len(asset_id) <= 64
                ):
                    raise ApiError(422, "ARTICLE_CONTENT_INVALID", "文章图片资源标识无效。")
            if clean_attrs:
                normalized["attrs"] = clean_attrs
        elif node_type == "heading":
            raise ApiError(422, "ARTICLE_CONTENT_INVALID", "文章标题缺少层级属性。")
        elif node_type == "image":
            raise ApiError(422, "ARTICLE_CONTENT_INVALID", "文章图片缺少来源。")
        marks = node.get("marks")
        if marks is not None:
            if node_type != "text":
                raise ApiError(422, "ARTICLE_CONTENT_INVALID", "文章标记只能用于文本节点。")
            if not isinstance(marks, list) or any(
                not isinstance(mark, dict) or mark.get("type") not in TIPTAP_MARK_TYPES
                for mark in marks
            ):
                raise ApiError(422, "ARTICLE_CONTENT_INVALID", "文章文本标记格式无效。")
            normalized_marks: list[dict[str, Any]] = []
            for mark in marks:
                mark_type = mark["type"]
                mark_attrs = mark.get("attrs")
                if mark_type != "link":
                    if mark_attrs is not None and mark_attrs != {}:
                        raise ApiError(422, "ARTICLE_CONTENT_INVALID", "文章文本标记属性无效。")
                    normalized_marks.append({"type": mark_type})
                    continue
                if not isinstance(mark_attrs, dict) or set(mark_attrs) - TIPTAP_LINK_ATTRS:
                    raise ApiError(422, "ARTICLE_CONTENT_INVALID", "文章链接属性无效。")
                clean_mark_attrs = {
                    key: value for key, value in mark_attrs.items() if value is not None
                }
                href = clean_mark_attrs.get("href")
                try:
                    parsed = urlparse(href) if isinstance(href, str) else None
                    hostname = parsed.hostname if parsed else None
                except ValueError:
                    parsed = None
                    hostname = None
                if (
                    not parsed
                    or parsed.scheme not in {"http", "https"}
                    or not hostname
                    or parsed.username
                    or parsed.password
                ):
                    raise ApiError(422, "ARTICLE_CONTENT_INVALID", "文章链接地址无效。")
                target = clean_mark_attrs.get("target")
                if target is not None and target not in {"_blank", "_self"}:
                    raise ApiError(422, "ARTICLE_CONTENT_INVALID", "文章链接打开方式无效。")
                for name, max_length in {"rel": 80, "class": 120}.items():
                    value = clean_mark_attrs.get(name)
                    if value is not None and (
                        not isinstance(value, str) or len(value) > max_length
                    ):
                        raise ApiError(422, "ARTICLE_CONTENT_INVALID", "文章链接属性无效。")
                normalized_marks.append({"type": mark_type, "attrs": clean_mark_attrs})
            normalized["marks"] = normalized_marks
        if node_type == "text":
            if not isinstance(node.get("text"), str):
                raise ApiError(422, "ARTICLE_CONTENT_INVALID", "文章文本节点格式无效。")
            normalized["text"] = node["text"]
            return normalized
        children = node.get("content", [])
        if not isinstance(children, list):
            raise ApiError(422, "ARTICLE_CONTENT_INVALID", "文章子节点格式无效。")
        direct_text = node.get("text")
        if direct_text is not None:
            if not isinstance(direct_text, str):
                raise ApiError(422, "ARTICLE_CONTENT_INVALID", "文章文本内容格式无效。")
            children = [{"type": "text", "text": direct_text}, *children]
        if children or node_type == "doc":
            normalized["content"] = [normalize_node(child) for child in children]
        return normalized

    normalized = normalize_node(content, is_root=True)
    if normalized["type"] != "doc":
        raise ApiError(422, "ARTICLE_CONTENT_INVALID", "文章内容必须以 doc 节点为根。")

    def validate_tree(node: dict[str, Any], parent_type: str) -> None:
        children = node.get("content", [])
        node_type = node["type"]
        expected = (
            TIPTAP_DOCUMENT_BLOCKS
            if parent_type == "doc"
            else TIPTAP_ALLOWED_CHILDREN.get(parent_type)
        )
        if expected is None or node_type not in expected:
            raise ApiError(422, "ARTICLE_CONTENT_INVALID", "文章节点层级无效。")
        if node_type in {"bulletList", "orderedList", "listItem", "blockquote"} and not children:
            raise ApiError(422, "ARTICLE_CONTENT_INVALID", "文章列表节点不能为空。")
        if node_type == "listItem" and children[0]["type"] != "paragraph":
            raise ApiError(422, "ARTICLE_CONTENT_INVALID", "文章列表项必须以段落开始。")
        if node_type in {"table", "tableRow", "tableCell", "tableHeader"} and not children:
            raise ApiError(422, "ARTICLE_CONTENT_INVALID", "表格行和单元格不能为空。")
        if node_type == "table":
            counts = [len(row.get("content", [])) for row in children]
            if len(children) > 200 or len(set(counts)) != 1 or not 1 <= counts[0] <= 20:
                raise ApiError(
                    422, "ARTICLE_CONTENT_INVALID", "表格必须为规则行列，最多 200 行、20 列。"
                )
        for child in children:
            validate_tree(child, node_type)

    for child in normalized["content"]:
        validate_tree(child, "doc")
    return normalized


def extract_plain_text(node: Any) -> str:
    if isinstance(node, str):
        return node
    if isinstance(node, list):
        return "\n".join(part for item in node if (part := extract_plain_text(item)))
    if not isinstance(node, dict):
        return ""
    own_text = str(node.get("text", ""))
    child_text = extract_plain_text(node.get("content", []))
    if own_text and child_text:
        return f"{own_text}\n{child_text}"
    return own_text or child_text


async def owned_article(
    session: AsyncSession, *, owner_id: str, article_id: str, for_update: bool = False
) -> Article:
    statement = select(Article).where(
        Article.id == article_id,
        Article.owner_id == owner_id,
        Article.deleted_at.is_(None),
    )
    if for_update:
        statement = statement.with_for_update()
    article = await session.scalar(statement)
    if not article:
        raise ApiError(404, "ARTICLE_NOT_FOUND", "文章不存在。")
    return article


async def current_article_version(session: AsyncSession, *, article: Article) -> ArticleVersion:
    version = await session.scalar(
        select(ArticleVersion).where(
            ArticleVersion.article_id == article.id,
            ArticleVersion.version_no == article.current_version_no,
        )
    )
    if not version:
        raise ApiError(500, "ARTICLE_VERSION_MISSING", "文章当前版本不存在。")
    return version


async def create_article(
    session: AsyncSession,
    *,
    owner_id: str,
    project_id: str | None,
    task_id: str | None,
    title: str,
    summary: str | None,
    content: dict[str, Any],
    source: str,
    created_by_type: str,
    created_by_id: str,
) -> tuple[Article, ArticleVersion]:
    content = canonical_article_content(content)
    plain_text = extract_plain_text(content).strip()
    article = Article(
        owner_id=owner_id,
        project_id=project_id,
        source_task_id=task_id,
        title=title.strip(),
        summary=summary,
        current_version_no=1,
    )
    session.add(article)
    await session.flush()
    version = ArticleVersion(
        article_id=article.id,
        version_no=1,
        content_json=content,
        plain_text=plain_text,
        content_hash=normalized_content_hash(content),
        source=source,
        created_by_type=created_by_type,
        created_by_id=created_by_id,
    )
    session.add(version)
    await session.flush()
    return article, version


async def save_article_version(
    session: AsyncSession,
    *,
    owner_id: str,
    article_id: str,
    base_version_no: int,
    title: str,
    summary: str | None,
    content: dict[str, Any],
    source: str,
    created_by_type: str,
    created_by_id: str,
    template_version_id: str | None = None,
    restored_layout: dict[str, Any] | None = None,
) -> tuple[Article, ArticleVersion]:
    article = await owned_article(
        session, owner_id=owner_id, article_id=article_id, for_update=True
    )
    if article.current_version_no != base_version_no:
        raise ApiError(
            409,
            "ARTICLE_VERSION_CONFLICT",
            "文章已在其他设备更新，请刷新后继续。",
            details={"current_version": article.current_version_no},
        )
    previous = await current_article_version(session, article=article)
    # Layout belongs to the immutable article version, not editor HTML or browser storage.
    # Only internal restoration may replace it from an existing version's snapshot.
    layout = restored_layout if source == "restore" else previous.layout_snapshot
    if template_version_id and (
        not layout or layout.get("template_version_id") != template_version_id
    ):
        row = (
            await session.execute(
                select(LayoutTemplate, LayoutTemplateVersion)
                .join(LayoutTemplateVersion, LayoutTemplateVersion.template_id == LayoutTemplate.id)
                .where(
                    LayoutTemplate.owner_id == owner_id,
                    LayoutTemplate.deleted_at.is_(None),
                    LayoutTemplateVersion.id == template_version_id,
                )
            )
        ).first()
        if not row:
            raise ApiError(404, "LAYOUT_TEMPLATE_NOT_FOUND", "排版模板版本不存在。")
        template, template_version = row
        layout = {
            "template_id": template.id,
            "template_version_id": template_version.id,
            "name": template.name,
            "official_account_id": template.official_account_id,
            "style_tokens": template_version.style_tokens,
        }
    content = canonical_article_content(content)
    next_no = article.current_version_no + 1
    version = ArticleVersion(
        article_id=article.id,
        version_no=next_no,
        content_json=content,
        layout_snapshot=layout,
        plain_text=extract_plain_text(content).strip(),
        content_hash=normalized_content_hash(content),
        source=source,
        created_by_type=created_by_type,
        created_by_id=created_by_id,
    )
    session.add(version)
    article.current_version_no = next_no
    article.title = title.strip()
    article.summary = summary
    await session.flush()
    await invalidate_article_renders(session, article.id)
    return article, version


async def restore_article_version(
    session: AsyncSession,
    *,
    owner_id: str,
    article_id: str,
    version_no: int,
    base_version_no: int,
) -> tuple[Article, ArticleVersion]:
    article = await owned_article(session, owner_id=owner_id, article_id=article_id)
    source_version = await session.scalar(
        select(ArticleVersion).where(
            ArticleVersion.article_id == article.id,
            ArticleVersion.version_no == version_no,
        )
    )
    if not source_version:
        raise ApiError(404, "ARTICLE_VERSION_NOT_FOUND", "历史版本不存在。")
    return await save_article_version(
        session,
        owner_id=owner_id,
        article_id=article_id,
        base_version_no=base_version_no,
        title=article.title,
        summary=article.summary,
        content=source_version.content_json,
        source="restore",
        restored_layout=source_version.layout_snapshot,
        created_by_type="user",
        created_by_id=owner_id,
    )


async def invalidate_article_renders(session: AsyncSession, article_id: str) -> None:
    now = utcnow()
    render_ids = select(ArticleRender.id).where(ArticleRender.article_id == article_id)
    await session.execute(
        update(ArticleConfirmation)
        .where(
            ArticleConfirmation.render_id.in_(render_ids),
            ArticleConfirmation.invalidated_at.is_(None),
        )
        .values(invalidated_at=now)
    )
    await session.execute(
        update(ArticleRender)
        .where(ArticleRender.article_id == article_id, ArticleRender.stale_at.is_(None))
        .values(stale_at=now)
    )


async def upsert_article_library_item(
    session: AsyncSession, *, article: Article, version: ArticleVersion, status: str
) -> LibraryItem:
    item = await session.scalar(
        select(LibraryItem).where(
            LibraryItem.owner_id == article.owner_id,
            LibraryItem.item_type == "article",
            LibraryItem.source_id == article.id,
        )
    )
    if not item:
        item = LibraryItem(
            owner_id=article.owner_id,
            item_type="article",
            source_id=article.id,
            project_id=article.project_id,
            title=article.title,
            summary=article.summary,
            display_status=status,
            search_text=f"{article.title}\n{version.plain_text}",
        )
        session.add(item)
    else:
        item.project_id = article.project_id
        item.title = article.title
        item.summary = article.summary
        item.display_status = status
        item.search_text = f"{article.title}\n{version.plain_text}"
        item.deleted_at = None
    return item


async def save_local_article(
    session: AsyncSession, *, owner_id: str, article_id: str
) -> tuple[Article, LibraryItem]:
    article = await owned_article(
        session, owner_id=owner_id, article_id=article_id, for_update=True
    )
    version = await current_article_version(session, article=article)
    article.status = "local_draft"
    item = await upsert_article_library_item(
        session, article=article, version=version, status="local_draft"
    )
    await enqueue_preference_summary(
        session, owner_id=owner_id, task_id=article.source_task_id, reason="save_local"
    )
    create_job(
        session,
        owner_id=owner_id,
        job_type="article_indexing",
        resource_type="article",
        resource_id=article.id,
        queue="embedding",
        stage="queued",
        frozen_payload={"article_id": article.id, "version_id": version.id},
    )
    emit_outbox(
        session,
        event_type="article.index.requested",
        aggregate_type="article",
        aggregate_id=article.id,
        payload={"article_id": article.id, "version_id": version.id},
    )
    await session.flush()
    return article, item


async def soft_delete_article(session: AsyncSession, *, owner_id: str, article_id: str) -> Article:
    """Soft-delete an article and detach tasks that must remain usable."""

    article = await owned_article(
        session,
        owner_id=owner_id,
        article_id=article_id,
        for_update=True,
    )
    deleted_at = utcnow()
    article.deleted_at = deleted_at
    await session.execute(
        update(LibraryItem)
        .where(
            LibraryItem.owner_id == owner_id,
            LibraryItem.item_type == "article",
            LibraryItem.source_id == article.id,
        )
        .values(deleted_at=deleted_at)
    )
    await session.execute(
        update(Task)
        .where(Task.owner_id == owner_id, Task.current_article_id == article.id)
        .values(current_article_id=None)
    )
    return article
