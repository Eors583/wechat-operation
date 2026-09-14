"""Conservative structural candidates; recognition never opts source content into reuse."""

from __future__ import annotations

import re
from typing import Any

from bs4 import BeautifulSoup, Tag

from app.layout_contracts import LayoutComponentGroup
from app.style_token_contracts import StyleProperties

_CREDIT = re.compile(
    r"^(文(?=\s|[丨|｜:：])|作者|记者|编辑|见习编辑|责任编辑|审核|头图来源|图片来源|来源)\s*[丨|｜:：]?\s*(.*)"
)


def _tag_style(tag: Tag) -> dict[str, str]:
    result: dict[str, str] = {}
    for item in str(tag.get("style", "")).split(";"):
        if ":" in item:
            key, value = item.split(":", 1)
            result[key.strip()] = value.strip().replace("!important", "").strip()
    if tag.name in {"strong", "b"}:
        result.setdefault("font-weight", "700")
    return result


def _styles(fragment: str) -> dict[str, str]:
    soup = BeautifulSoup(fragment, "html.parser")
    result: dict[str, str] = {}
    # Walk the first text branch, not every sibling: later value spans must not
    # overwrite the container alignment or the earlier label's color.
    text = soup.find(string=lambda value: bool(value.strip()))
    path = list(reversed(list(text.parents))) if text else soup.find_all(True, limit=1)
    for tag in path:
        if isinstance(tag, Tag):
            result.update(_tag_style(tag))
    return result


def _credit_styles(
    soup: BeautifulSoup, base: dict[str, str]
) -> tuple[StyleProperties, StyleProperties]:
    styles = []
    for text in soup.find_all(string=lambda value: bool(value.strip().strip("丨|｜:："))):
        style = {key: value for key, value in base.items() if key in {"font-size", "font-weight"}}
        for tag in reversed(list(text.parents)):
            if isinstance(tag, Tag):
                style.update(_tag_style(tag))
        styles.append(
            _properties(
                {
                    key: value
                    for key, value in style.items()
                    if key in {"color", "font-size", "font-weight"}
                }
            )
        )
    label = styles[0] if len(styles) > 1 else StyleProperties(color="#888888")
    value = styles[-1] if styles else StyleProperties(color="#222222")
    return label, value


def _color(value: str) -> str | None:
    if re.fullmatch(r"#[0-9a-fA-F]{6}", value):
        return value
    match = re.fullmatch(r"rgb\(\s*(\d+),\s*(\d+),\s*(\d+)\s*\)", value)
    if match and all(int(v) <= 255 for v in match.groups()):
        return "#" + "".join(f"{int(v):02x}" for v in match.groups())
    return None


def _properties(style: dict[str, str]) -> StyleProperties:
    result: dict[str, Any] = {}
    for css, key in {
        "color": "color",
        "background-color": "background",
        "background": "background",
    }.items():
        if color := _color(style.get(css, "")):
            result[key] = color
    for css, key in {
        "font-size": "font_size",
        "padding": "padding",
        "margin-bottom": "margin_bottom",
    }.items():
        value = style.get(css, "")
        if re.fullmatch(r"\d+(?:\.\d+)?px", value) and float(value[:-2]) <= 72:
            result[key] = float(value[:-2])
    if style.get("text-align") in {"left", "center", "right", "justify"}:
        result["align"] = style["text-align"]
    if style.get("font-weight") in {"400", "500", "600", "700"}:
        result["font_weight"] = int(style["font-weight"])
    elif style.get("font-weight") == "bold":
        result["font_weight"] = 700
    return StyleProperties.model_validate(result)


def recognize_component_groups(blocks: list[dict[str, str]]) -> list[dict[str, Any]]:
    groups: list[LayoutComponentGroup] = []
    index = 0
    while index < len(blocks) and len(groups) < 100:
        block = blocks[index]
        text = block["text"].strip()
        style = _styles(block["html"])
        soup = BeautifulSoup(block["html"], "html.parser")
        group: LayoutComponentGroup | None = None
        if style.get("text-align") == "right" and _CREDIT.match(text) and len(text) <= 160:
            label_style, value_style = _credit_styles(soup, style)
            ids, fields = [], []
            while index < len(blocks) and len(fields) < 12:
                current = blocks[index]
                match = _CREDIT.match(current["text"].strip())
                if (
                    not match
                    or len(current["text"]) > 160
                    or _styles(current["html"]).get("text-align") != "right"
                ):
                    break
                ids.append(current["id"])
                fields.append({"label": match[1], "value": ""})
                index += 1
            group = LayoutComponentGroup(
                id=f"group-{len(groups) + 1}",
                kind="credits",
                block_ids=ids,
                confidence=0.9,
                fields=fields,
                container_style=StyleProperties(align="right", margin_bottom=24),
                text_style=value_style,
                label_style=label_style,
            )
            groups.append(group)
            continue
        background = _color(style.get("background-color", style.get("background", "")))
        if (
            index < 12
            and 8 <= len(text) <= 180
            and background
            and background.lower() != "#ffffff"
            and not soup.find("img")
        ):
            group = LayoutComponentGroup(
                id=f"group-{len(groups) + 1}",
                kind="lead_card",
                block_ids=[block["id"]],
                confidence=0.75,
                container_style=StyleProperties(
                    background=background, padding=12, margin_bottom=24
                ),
                text_style=_properties(
                    {
                        key: value
                        for key, value in style.items()
                        if key in {"color", "font-size", "font-weight", "text-align"}
                    }
                ),
            )
        if (
            not text
            and soup.find("img")
            and not soup.find("figure", attrs={"data-profile-card": "true"})
            and index + 1 < len(blocks)
        ):
            following = blocks[index + 1]
            image = soup.find("img")
            width = str(image.get("width", "")) if image else ""
            width_match = (
                re.search(r"(?:^|;)\s*width:\s*(\d+(?:\.\d+)?)px", str(image.get("style", "")))
                if image
                else None
            )
            image_width = (
                float(width) if width.isdigit() else float(width_match[1]) if width_match else 0
            )
            heading = following["module"] in {"heading1", "heading2"} or (
                2 <= len(following["text"]) <= 60
                and BeautifulSoup(following["html"], "html.parser").find(["strong", "b"])
            )
            if heading and 0 < image_width <= 240:
                group = LayoutComponentGroup(
                    id=f"group-{len(groups) + 1}",
                    kind="decorated_heading",
                    block_ids=[block["id"], following["id"]],
                    confidence=0.55,
                    image_width=max(24, round(image_width)),
                    container_style=StyleProperties(align="left", margin_bottom=8),
                )
        if group:
            groups.append(group)
        index += 1
    return [group.model_dump(exclude_none=True) for group in groups]
