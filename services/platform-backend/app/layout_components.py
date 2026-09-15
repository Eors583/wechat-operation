"""Conservative structural candidates; recognition never opts source content into reuse."""

from __future__ import annotations

import re
from collections import Counter
from typing import Any
from urllib.parse import urlsplit

from bs4 import BeautifulSoup, Tag

from app.layout_contracts import LayoutComponentGroup
from app.style_token_contracts import StyleProperties


def layout_image_inputs(blocks: list[dict[str, str]]) -> list[dict[str, str]]:
    """Pass real CDN images, with stable source IDs, to the configured visual model."""
    images = []
    for block in blocks:
        soup = BeautifulSoup(block["html"], "html.parser")
        if soup.find("figure", attrs={"data-profile-card": "true"}):
            continue
        for image in soup.find_all("img"):
            source = str(image.get("src", ""))
            parsed = urlsplit(source)
            if (
                parsed.scheme in {"http", "https"}
                and (parsed.hostname == "qpic.cn" or (parsed.hostname or "").endswith(".qpic.cn"))
                and not parsed.username
                and not parsed.password
                and parsed.port in {None, 80, 443}
            ):
                images.append(
                    {"image_id": f"image-{len(images) + 1}", "block_id": block["id"], "url": source}
                )
    return images


_CREDIT = re.compile(
    r"^(文|作者|记者|编辑|见习编辑|责任编辑|责编|审核|头图来源|图片来源|来源|图|排版)"
    r"\s*[丨|｜:：]\s*(.{1,120})$"
)


def image_family_evidence(blocks: list[dict[str, str]]) -> dict[str, dict[str, Any]]:
    evidence: dict[str, dict[str, Any]] = {}
    for index, block in enumerate(blocks):
        soup = BeautifulSoup(block["html"], "html.parser")
        images = soup.find_all("img")
        if len(images) != 1 or soup.find("figure", attrs={"data-profile-card": "true"}):
            continue
        image = images[0]
        width, ratio = str(image.get("data-w", "")), str(image.get("data-ratio", ""))
        if not re.fullmatch(r"[1-9]\d{0,4}", width) or not re.fullmatch(r"\d+(?:\.\d+)?", ratio):
            continue
        if not 0 < float(ratio) < 10:
            continue
        following = next(
            (item for item in blocks[index + 1 : index + 4] if item["text"].strip()), None
        )
        evidence[block["id"]] = {
            "source_width": int(width),
            "ratio": round(float(ratio), 6),
            "alt": str(image.get("alt", ""))[:100],
            "heading_block_id": following["id"]
            if following and 0 < len(following["text"]) < 30
            else None,
        }
    counts = Counter((item["source_width"], item["ratio"]) for item in evidence.values())
    for item in evidence.values():
        item["family_size"] = counts[item["source_width"], item["ratio"]]
    return evidence


def _padding_sides(style: dict[str, str]) -> list[float] | None:
    pieces = style.get("padding", "").split()
    if not 1 <= len(pieces) <= 4 or any(
        not re.fullmatch(r"\d+(?:\.\d+)?(?:px)?", value) for value in pieces
    ):
        return None
    values = [float(value.removesuffix("px")) for value in pieces]
    values = (
        values * 4
        if len(values) == 1
        else values * 2
        if len(values) == 2
        else [values[0], values[1], values[2], values[1]]
        if len(values) == 3
        else values
    )
    return values if all(value <= 72 for value in values) else None


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
        "margin-top": "margin_top",
    }.items():
        value = style.get(css, "")
        if re.fullmatch(r"\d+(?:\.\d+)?px", value) and float(value[:-2]) <= 72:
            result[key] = float(value[:-2])
    if style.get("text-align") in {"left", "center", "right", "justify"}:
        result["align"] = style["text-align"]
    line_height = style.get("line-height", "").removesuffix("em")
    if re.fullmatch(r"\d+(?:\.\d+)?", line_height) and 1 <= float(line_height) <= 3:
        result["line_height"] = float(line_height)
    if style.get("font-weight") in {"400", "500", "600", "700"}:
        result["font_weight"] = int(style["font-weight"])
    elif style.get("font-weight") == "bold":
        result["font_weight"] = 700
    return StyleProperties.model_validate(result)


def recognize_component_groups(blocks: list[dict[str, str]]) -> list[dict[str, Any]]:
    groups: list[LayoutComponentGroup] = []
    families = image_family_evidence(blocks)
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
            start = index
            total_length = 0
            while index < len(blocks) and len(fields) < 12:
                current = blocks[index]
                match = _CREDIT.match(current["text"].strip())
                if (
                    not match
                    or len(current["text"]) > 160
                    or _styles(current["html"]).get("text-align") != "right"
                    or (len(match[2]) > 20 and re.search(r"[。？，,?!！]", match[2]))
                    or total_length + len(current["text"]) >= 200
                ):
                    break
                ids.append(current["id"])
                total_length += len(current["text"])
                labels = re.findall(
                    r"(?:^|\s)(文|作者|记者|见习编辑|责任编辑|责编|编辑|审核|头图来源|图片来源|来源|图|排版)"
                    r"\s*[丨|｜:：]",
                    current["text"].strip(),
                )
                fields.extend({"label": label, "value": ""} for label in labels or [match[1]])
                if len(fields) > 12:
                    fields = []
                    index += 1
                    break
                index += 1
            if len(fields) < 2:
                index = max(index, start + 1)
                continue
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
            20 <= len(text) <= 300
            and background
            and background.lower() != "#ffffff"
            and not soup.find("img")
            and ("inline-block" == style.get("display") or _padding_sides(style) is not None)
        ):
            group = LayoutComponentGroup(
                id=f"group-{len(groups) + 1}",
                kind="lead_card" if index < 12 else "quote_card",
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
                padding_sides=_padding_sides(style),
            )
        if (
            not text
            and soup.find("img")
            and not soup.find("figure", attrs={"data-profile-card": "true"})
            and index + 1 < len(blocks)
        ):
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
            family = families.get(block["id"], {})
            if (
                family.get("family_size", 0) >= 2
                and not family.get("alt")
                and family.get("heading_block_id")
            ):
                group = LayoutComponentGroup(
                    id=f"group-{len(groups) + 1}",
                    kind="decorated_heading",
                    block_ids=[block["id"], family["heading_block_id"]],
                    confidence=0.75,
                    image_width=max(24, min(680, round(image_width or 150))),
                    container_style=StyleProperties(align="left", margin_bottom=8),
                )
        if group:
            groups.append(group)
        index += 1
    return [group.model_dump(exclude_none=True) for group in groups]
