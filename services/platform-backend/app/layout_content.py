"""Safe, selectable article fragments shared by template import and rendering."""

from __future__ import annotations

import ipaddress
import re
from collections.abc import Iterator
from html import escape
from urllib.parse import unquote, urlparse, urlunparse

from bs4 import BeautifulSoup, Comment, NavigableString, Tag

_TAGS = {
    "a", "abbr", "article", "b", "blockquote", "br", "caption", "code", "col",
    "colgroup", "dd", "del", "div", "dl", "dt", "em", "figcaption", "figure",
    "footer", "h1", "h2", "h3", "h4", "h5", "h6", "header", "hr", "i", "img",
    "li", "main", "mark", "ol", "p", "pre", "q", "s", "section", "small", "span",
    "strong", "sub", "sup", "table", "tbody", "td", "th", "thead", "tfoot", "tr",
    "u", "ul", "wbr",
}
_DROP_TAGS = {"script", "style", "noscript", "template", "head", "form", "input", "button"}
_MEDIA_TAGS = {"iframe", "video", "audio", "embed", "object", "svg", "canvas", "mpvoice", "mpvideo"}
_CONTAINERS = {"article", "main", "header", "footer", "div", "section", "blockquote", "span"}
_BLOCK_TAGS = {
    "article", "blockquote", "div", "dl", "figure", "footer", "h1", "h2", "h3",
    "h4", "h5", "h6", "header", "hr", "main", "ol", "p", "pre", "section", "table", "ul",
}
_CSS_PROPERTIES = {
    "background", "background-color", "background-image", "background-size",
    "background-position", "background-repeat", "border", "border-top", "border-right",
    "border-bottom", "border-left", "border-color", "border-style", "border-width",
    "border-top-width", "border-right-width", "border-bottom-width", "border-left-width",
    "border-radius", "border-collapse", "border-spacing", "box-sizing", "color", "display",
    "font-family", "font-size", "font-style", "font-weight", "letter-spacing", "line-height",
    "list-style-type", "list-style-position", "margin", "margin-top", "margin-right",
    "margin-bottom", "margin-left", "padding", "padding-top", "padding-right", "padding-bottom",
    "padding-left", "text-align", "text-decoration", "text-indent", "vertical-align", "width",
    "max-width", "min-width", "overflow-wrap", "word-break", "white-space", "table-layout",
}
_CSS_VALUE = re.compile(r"^[\w\s#.,%()'\"/+-]+$", re.UNICODE)
_CSS_UNSAFE = re.compile(r"(?:url|expression|var|attr|image-set)\s*\(|!|@|\\\\|[\x00-\x1f]", re.I)
_IMAGE_HOSTS = {"qpic.cn", "qlogo.cn"}
_BOUNDS = "max-width:100%;min-width:0;box-sizing:border-box;overflow-wrap:anywhere"


def _safe_url(value: str, *, image: bool = False) -> str:
    value = value.strip()
    if value.startswith("//"):
        value = "https:" + value
    try:
        parsed = urlparse(value)
        host = (parsed.hostname or "").lower().rstrip(".")
        if (
            parsed.scheme not in {"https", "http"}
            or not host
            or parsed.username
            or parsed.password
            or parsed.port not in {None, 80, 443}
            or re.search(r"[\s\\\x00-\x1f]", value)
        ):
            return ""
        if image:
            trusted_cdn = any(
                host == suffix or host.endswith("." + suffix) for suffix in _IMAGE_HOSTS
            )
            if parsed.scheme != "https" and not trusted_cdn:
                return ""
        if "." not in host or host.endswith((
            ".local", ".localhost", ".internal", ".test", ".invalid", ".lan", ".home", ".home.arpa",
        )):
            return ""
        try:
            ipaddress.ip_address(host)
        except ValueError:
            labels = host.split(".")
            if any(
                not re.fullmatch(r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?", label)
                for label in labels
            ) or re.fullmatch(r"(?:[0-9]+|0x[0-9a-f]+)", labels[-1]):
                return ""
        else:
            return ""
        return urlunparse(parsed._replace(scheme="https", netloc=host))
    except ValueError:
        return ""


def _safe_style(value: str) -> str:
    declarations: dict[str, str] = {}
    for declaration in value.split(";"):
        name, separator, raw = declaration.partition(":")
        name, raw = name.strip().lower(), raw.strip()
        raw = re.sub(r"\s*!important\s*$", "", raw, flags=re.I)
        if name in {"background", "background-image"} and "url" in raw.lower():
            match = re.fullmatch(r"url\(\s*['\"]?([^'\"()]+?)['\"]?\s*\)", raw, re.I)
            source = _safe_url(match[1], image=True) if match else ""
            if source:
                declarations["background-image"] = f"url('{source}')"
            continue
        if (
            separator
            and name in _CSS_PROPERTIES
            and len(raw) <= 300
            and _CSS_VALUE.fullmatch(raw)
            and not _CSS_UNSAFE.search(raw)
        ):
            declarations[name] = raw
    # Imported content must stay in the article and remain readable at mobile widths.
    if declarations.get("display", "").lower() == "none":
        declarations.pop("display")
    declarations["white-space"] = (
        "pre-wrap" if declarations.get("white-space") in {"pre", "pre-wrap", "break-spaces"}
        else "normal"
    )
    return ";".join(f"{name}:{raw}" for name, raw in declarations.items())



def _profile_card(element: Tag) -> Tag:
    """Render WeChat custom profile attributes as a single static article block."""
    title = escape(str(element.get("data-nickname") or element.get("data-alias") or "公众号"))
    signature = escape(str(element.get("data-signature") or ""))
    avatar = _safe_url(str(element.get("data-headimg") or ""), image=True)
    badge = (
        '<span style="color:#1684fc;font-size:14px" aria-label="已认证"> ✓</span>'
        if str(element.get("data-verify_status")) == "2" else ""
    )
    image = (
        f'<img src="{escape(avatar, quote=True)}" alt="" width="48" '
        'referrerpolicy="no-referrer" style="width:48px;max-width:100%;height:auto;'
        'border-radius:50%"/>' if avatar else ""
    )
    markup = (
        '<figure style="margin:16px 0;padding:16px;background:#f8f8f8;'
        'border-radius:12px;text-align:left;' + _BOUNDS + '">'
        '<table style="width:100%;table-layout:fixed;border-collapse:collapse"><tbody><tr>'
        '<td style="width:56px;vertical-align:top;padding:0 8px 0 0">' + image + '</td>'
        '<td style="vertical-align:top;min-width:0;overflow-wrap:anywhere">'
        '<strong style="font-size:17px;font-weight:400;color:#222">' + title + badge + '</strong>'
        '<p style="margin:4px 0 0;font-size:14px;line-height:1.6;color:#777">'
        + signature + '</p></td></tr></tbody></table>'
        '<figcaption style="margin-top:16px;padding-top:8px;border-top:1px solid #eee;'
        'font-size:13px;color:#aaa">公众号</figcaption></figure>'
    )
    return BeautifulSoup(markup, "html.parser").figure


def sanitize_content_html(value: str) -> str:
    """Allow static article markup only; never fetch any external resource."""
    soup = BeautifulSoup(value, "html.parser")
    for comment in soup.find_all(string=lambda item: isinstance(item, Comment)):
        comment.extract()
    for element in list(soup.find_all(True)):
        if element.parent is None:
            continue
        name = element.name.lower()
        if name == "mp-common-profile":
            element.replace_with(_profile_card(element))
            continue
        if name in _DROP_TAGS:
            element.decompose()
            continue
        if name in _MEDIA_TAGS:
            url = _safe_url(str(element.get("data-src") or element.get("src") or ""))
            replacement = soup.new_tag("a" if url else "span")
            cover = _safe_url(
                unquote(str(element.get("data-cover") or element.get("poster") or "")), image=True,
            )
            if cover:
                image = soup.new_tag("img", src=cover, alt="视频封面")
                image.attrs.update({
                    "referrerpolicy": "no-referrer", "style": _BOUNDS + ";height:auto",
                })
                replacement.append(image)
                caption = soup.new_tag("span")
                caption.string = "▶ 播放视频" if url else "视频"
                caption["style"] = "display:block;text-align:center"
                replacement.append(caption)
            else:
                replacement.string = "此媒体请在原文查看"
            if url:
                replacement.attrs = {"href": url, "target": "_blank", "rel": "noopener noreferrer"}
            element.replace_with(replacement)
            continue
        if name not in _TAGS:
            element.unwrap()
            continue
        original = dict(element.attrs)
        element.attrs = {}
        style = _safe_style(str(original.get("style", "")))
        align = str(original.get("align", ""))
        if align in {"left", "center", "right", "justify"}:
            style += f";text-align:{align}"
        if name in _BLOCK_TAGS | {"img", "td", "th", "li"}:
            style += ";" + _BOUNDS
        if name == "img":
            source = _safe_url(str(original.get("data-src", "")), image=True) or _safe_url(
                str(original.get("src", "")), image=True
            )
            if not source and not any(original.get(key) for key in ("data-src", "src")):
                element.decompose()
                continue
            if not source:
                replacement = soup.new_tag("span")
                replacement.string = "此图片请在原文查看"
                element.replace_with(replacement)
                continue
            element.attrs.update({
                "src": source,
                "alt": str(original.get("alt", ""))[:500],
                "referrerpolicy": "no-referrer",
                "loading": "lazy",
            })
            width = str(original.get("width", ""))
            if re.fullmatch(r"[1-9][0-9]{0,3}", width) and not re.search(r"(?:^|;)width:", style):
                style += f";width:{width}px"
            style += ";height:auto"
        elif name == "a":
            if href := _safe_url(str(original.get("href", ""))):
                element.attrs.update({
                    "href": href, "target": "_blank", "rel": "noopener noreferrer",
                })
        for attribute in {"colspan", "rowspan", "span", "start", "value"}:
            raw = str(original.get(attribute, ""))
            if re.fullmatch(r"[0-9]{1,3}", raw) and int(raw) > 0:
                element[attribute] = raw
        if name == "table":
            style += ";table-layout:fixed;width:100%"
        if name == "pre":
            style += ";white-space:pre-wrap"
        if style:
            element["style"] = style.strip(";")
    return str(soup)


def _module(element: Tag, text: str) -> str:
    if element.name == "h1":
        return "title"
    if element.name == "h2":
        return "heading1"
    if element.name in {"h3", "h4", "h5", "h6"}:
        return "heading2"
    if element.name in {"ul", "ol", "li"}:
        return "list"
    if element.name == "blockquote":
        return "quote"
    if element.name in {"figcaption", "caption"}:
        return "caption"
    if element.name == "hr":
        return "divider"
    if element.name == "table":
        return "table_cell"
    if re.fullmatch(r"(?:\d{1,3}|[一二三四五六七八九十百]{1,4})", text):
        return "heading_marker"
    return "body"


def _selectable_parts(root: Tag, depth: int = 0) -> Iterator[tuple[str, str, str]]:
    children = list(root.children)
    # Keep tables, lists and inline-only groups intact so their structure is valid.
    if depth >= 80 or root.name not in _CONTAINERS or not root.find(_BLOCK_TAGS):
        text = root.get_text(" ", strip=True)
        if (
            text or root.find(["img", "hr", "br"])
            or root.name in _BLOCK_TAGS | {"img", "br"}
        ):
            yield str(root), text, _module(root, text)
        return
    inline: list[str] = []
    parts: list[tuple[str, str, str]] = []

    def flush_inline() -> Iterator[tuple[str, str, str]]:
        if not inline:
            return
        fragment = "".join(inline)
        inline.clear()
        text = BeautifulSoup(fragment, "html.parser").get_text(" ", strip=True)
        if text or "<" in fragment:
            yield fragment, text, "body"

    for child in children:
        if isinstance(child, Tag) and (child.name in _BLOCK_TAGS or child.find(_BLOCK_TAGS)):
            parts.extend(flush_inline())
            for fragment, text, module in _selectable_parts(child, depth + 1):
                parts.append((fragment, text, "quote" if root.name == "blockquote" else module))
        elif isinstance(child, Tag):
            inline.append(str(child))
        elif isinstance(child, NavigableString):
            inline.append(escape(str(child)))
    parts.extend(flush_inline())
    for index, (fragment, text, module) in enumerate(parts):
        attrs = dict(root.attrs)
        style = str(attrs.get("style", ""))
        if index:
            style += ";margin-top:0;padding-top:0;border-top-width:0"
        if index < len(parts) - 1:
            style += ";margin-bottom:0;padding-bottom:0;border-bottom-width:0"
        attrs["style"] = style.strip(";")
        attributes = "".join(
            f' {key}="{escape(str(value), quote=True)}"' for key, value in attrs.items()
        )
        yield f"<{root.name}{attributes}>{fragment}</{root.name}>", text, module


def extract_content_blocks(page: str) -> list[dict[str, str]]:
    """Extract the whole article, splitting nested wrappers into selectable portions."""
    soup = BeautifulSoup(page, "html.parser")
    content = soup.find(id="js_content") or soup.select_one(".rich_media_content")
    if not isinstance(content, Tag):
        return []
    safe = BeautifulSoup(sanitize_content_html(str(content)), "html.parser")
    root = safe.find(True)
    if not isinstance(root, Tag):
        return []
    if (
        not root.get_text(strip=True)
        and not root.find(["img", "hr"])
        and not re.search(r"(?:border|background)[^:]*:", str(root))
    ):
        return []
    return [
        {"id": f"content-{index}", "html": fragment, "text": text, "module": module}
        for index, (fragment, text, module) in enumerate(_selectable_parts(root), start=1)
    ]
