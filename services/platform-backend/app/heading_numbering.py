"""Keep section numbering in the layout, not in semantic heading text."""

import re
from copy import deepcopy
from typing import Any

HEADING_NUMBERING_INSTRUCTION = (
    "排版已启用自动标题序号。强制要求：文章中的标题、分论点标题只能输出语义文字，"
    "不得带一、二、（一）、1.、01等章节编号，也不得另建只有序号的标题或段落。"
    "论点标题必须使用heading节点，编号完全交给排版；保留正文列表序号、年份、数量和数据。"
)
_PREFIX = re.compile(
    r"^\s*(?:[一二三四五六七八九十百]{1,4}[、．.]|"
    r"[（(](?:[一二三四五六七八九十百]{1,4}|\d{1,3})[）)]|"
    r"\d{1,3}[、．.)](?!\d))\s*"
)


def without_heading_numbers(value: Any) -> Any:
    result = deepcopy(value)

    def visit(node: Any) -> None:
        if isinstance(node, list):
            for child in node:
                visit(child)
            node[:] = [
                child
                for child in node
                if not (
                    isinstance(child, dict)
                    and child.get("type") == "text"
                    and child.get("text") == ""
                )
            ]
        elif isinstance(node, dict):
            if node.get("type") == "heading":
                leaves: list[dict[str, Any]] = []

                def collect(item: dict[str, Any]) -> None:
                    if isinstance(item.get("text"), str):
                        leaves.append(item)
                    for child in item.get("content", []):
                        if isinstance(child, dict):
                            collect(child)

                collect(node)
                text = "".join(leaf["text"] for leaf in leaves)
                match = _PREFIX.match(text)
                if match and text[match.end() :].strip():
                    remaining = match.end()
                    for leaf in leaves:
                        cut = min(remaining, len(leaf["text"]))
                        leaf["text"] = leaf["text"][cut:]
                        remaining -= cut
            visit(node.get("content", []))

    visit(result)
    return result
