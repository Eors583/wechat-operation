"""Explicit conversation actions; inferred style is never saved without a request."""

import re
from typing import Any


def local_revision_requested(text: str) -> bool:
    return bool(
        re.match(
            r"(?:请|帮我)?(?:只|仅)(?:把|修改|调整|润色|改写|精简|优化|替换|改|换)?"
            r"(?:一下)?(?:文章的?)?(标题|开头|首段|第一段|结尾|末段|最后一段)",
            text.strip(),
        )
    )


def local_revision_target(text: str, document: dict[str, Any]) -> int | None:
    """Only a single, explicitly limited top-level block is safe to replace automatically."""
    match = re.fullmatch(
        r"(?:请|帮我)?(?:只|仅)(?:把|修改|调整|润色|改写|精简|优化|替换|改|换)?"
        r"(?:一下)?(?:文章的?)?(标题|开头|首段|第一段|结尾|末段|最后一段)[\s\S]*",
        text.strip(),
    )
    if not match or re.search(r"全文|整篇|同时|以及|并且|然后", text):
        return None
    blocks = document.get("content", [])
    if match[1] == "标题":
        return (
            0
            if blocks
            and blocks[0].get("type") == "heading"
            and blocks[0].get("attrs", {}).get("level") == 1
            else None
        )
    paragraphs = [
        i
        for i, block in enumerate(blocks)
        if block.get("type") == "paragraph" and block.get("content")
    ]
    if not paragraphs:
        return None
    return paragraphs[-1] if match[1] in {"结尾", "末段", "最后一段"} else paragraphs[0]


def style_action(text: str) -> str | None:
    if not re.search(r"写作风格|写作偏好|行文风格", text):
        return None
    if re.search(r"不要保存|不用保存|别保存|不要记录|别记录", text):
        return "describe"
    if re.search(r"保存|记录|记住|设为|形成|以后|今后", text):
        return "save"
    if re.search(r"总结|提炼|分析|归纳", text):
        return "describe"
    return None


def explicit_article_request(text: str) -> bool:
    """A requested article remains the deliverable even when research is also requested."""
    text = re.sub(r"https?://[^\s<>\u3400-\u9fff]+", "", text)
    if re.search(
        r"(?:不要|不用|无需|别|先不).{0,5}(?:写|生成|创作)"
        r"|(?:只|仅|先)(?:要|给我|提供|输出|生成|列|写)?(?:一下)?(?:创作)?"
        r"(?:提纲|大纲|思路|方向|标题|建议)",
        text,
    ):
        return False
    return bool(
        re.search(
            r"(?:写|撰写|创作|生成|完成|产出).{0,60}(?:文章|推文|公众号内容)"
            r"|写成(?:一|1)?篇|整理成文章|生成全文|完整成文"
            r"|(?:写|撰写|创作|生成)(?:一|1)?篇(?:吧|呀|啊|呗|看看)?(?=[，。！？、,!.?\s]|$)"
            r"|(?:文章|推文|原文)[，,：:、\s]*(?:请|麻烦|帮我|给我|为我)*"
            r"(?:重新|再|进行)?(?:创作|撰写|写作|改写|重写)"
            r"|(?:帮我|给我|请)(?:参考.{0,20})?(?:创作|撰写)(?:一下|一篇|成文)",
            text,
        )
    )
