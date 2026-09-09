from __future__ import annotations

import asyncio
import ipaddress
import re
import socket
from collections import Counter
from dataclasses import dataclass
from html.parser import HTMLParser
from typing import Any
from urllib.parse import urljoin, urlparse

import httpx

from app.providers import LayoutExtractionResult, ProviderUnavailable, WebReferenceContent

_WECHAT_HOST = "mp.weixin.qq.com"
_MAX_HTML_CHARS = 5_000_000
_DEFAULT_MPTEXT_URL = "https://down.mptext.top/api/public/v1/download"
_BROWSER_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Linux; Android 12; SM-G9910) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/120.0.0.0 Mobile Safari/537.36 "
        "MicroMessenger/8.0.50 WeChat/arm64 Language/zh_CN"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
    "Referer": "https://mp.weixin.qq.com/",
}
_DECLARATION = re.compile(r"\s*([a-zA-Z-]+)\s*:\s*([^;]+)")
_HEX_COLOR = re.compile(r"^#(?:[0-9a-fA-F]{8}|[0-9a-fA-F]{6}|[0-9a-fA-F]{3})$")
_RGB_COLOR = re.compile(r"rgba?\((\d{1,3})\s*,\s*(\d{1,3})\s*,\s*(\d{1,3})")
_NUMBER = re.compile(r"-?\d+(?:\.\d+)?")
_NUMBERED_HEADING_MARKER = re.compile(r"^(?:\d{1,3}|[一二三四五六七八九十百]{1,4})$")
_BLOCK_TAGS = {"p", "section", "div", "blockquote", "li", "h1", "h2", "h3", "figcaption"}
_TEXT_PROPERTIES = {
    "font-size",
    "font-weight",
    "color",
    "background",
    "background-color",
    "text-align",
    "line-height",
    "margin",
    "margin-top",
    "margin-bottom",
    "padding",
    "padding-left",
    "padding-right",
    "border-left",
    "text-indent",
}
_MAX_LAYOUT_SAMPLES = 120
_MAX_SAMPLE_TEXT_CHARS = 160


@dataclass(frozen=True, slots=True)
class _Sample:
    tag: str
    text: str
    style: dict[str, str]

    @property
    def weight(self) -> int:
        return max(1, min(len(self.text), 200))


@dataclass(frozen=True, slots=True)
class WeChatArticleApiConfig:
    """One normalized HTML download endpoint in the configured fallback chain."""

    name: str
    base_url: str
    priority: int = 100
    api_key: str | None = None
    auth_header: str = "X-Auth-Key"
    auth_prefix: str = ""


DEFAULT_MPTEXT_CONFIG = WeChatArticleApiConfig(
    name="mptext 免费 API",
    base_url=_DEFAULT_MPTEXT_URL,
    priority=10,
)


class WeChatPublicLayoutExtractionProvider:
    """Extract reusable layout tokens from public WeChat article HTML."""

    def __init__(
        self,
        *,
        timeout_seconds: float = 20.0,
        transport: httpx.AsyncBaseTransport | None = None,
        article_apis: list[WeChatArticleApiConfig] | None = None,
        direct_fallback: bool = True,
    ) -> None:
        self._timeout = timeout_seconds
        self._transport = transport
        self._article_apis = sorted(
            article_apis or [],
            key=lambda item: item.priority,
        )
        self._direct_fallback = direct_fallback

    async def extract(self, *, source_url: str) -> LayoutExtractionResult:
        clean_url = _validate_url(source_url)
        parser = await self._load_parser(clean_url)
        samples = parser.samples
        text_samples = [sample.text for sample in samples if sample.text]
        text_preview = "\n".join(text_samples[:20])[:2000]
        return LayoutExtractionResult(
            style_tokens=_style_tokens(samples),
            source_snapshot={
                "source_url": clean_url,
                "title": parser.title,
                "account_name": parser.account_name,
                "text_preview": text_preview,
                "text_samples": text_samples[:20],
                "text_sample_count": len(samples),
                "image_count": parser.image_count,
                "layout_observation": {
                    "schema_version": 1,
                    "sample_count": min(len(samples), _MAX_LAYOUT_SAMPLES),
                    "samples": [
                        {
                            "id": f"block-{index + 1}",
                            "order": index + 1,
                            "tag_hint": sample.tag,
                            "text_excerpt": sample.text[:_MAX_SAMPLE_TEXT_CHARS],
                            "computed_style": sample.style,
                        }
                        for index, sample in enumerate(samples[:_MAX_LAYOUT_SAMPLES])
                    ],
                },
            },
            extractor_version="wechat-public-dom-v1",
        )

    async def fetch_reference(self, *, source_url: str) -> WebReferenceContent:
        """Fetch real WeChat article text with the same guarded browser profile as layout import."""

        clean_url = _validate_url(source_url)
        parser = await self._load_parser(clean_url)
        text = "\n".join(sample.text for sample in parser.samples if sample.text).strip()
        if len(re.sub(r"\s+", "", text)) < 80:
            raise ProviderUnavailable("没有读取到完整微信公众号正文，请稍后重试或直接粘贴原文。")
        return WebReferenceContent(
            requested_url=clean_url,
            final_url=clean_url,
            title=parser.title or "微信公众号文章",
            text=text,
            content_type="text/html",
        )

    async def _load_parser(self, url: str) -> _WeChatContentParser:
        page = await self._fetch_page(url)
        parser = _WeChatContentParser()
        try:
            parser.feed(page[:_MAX_HTML_CHARS])
            parser.close()
        except Exception as exc:
            raise ProviderUnavailable("微信公众号文章 HTML 解析失败") from exc
        samples = parser.samples
        text_samples = [sample.text for sample in samples if sample.text]
        if len("".join(text_samples)) < 20:
            raise ProviderUnavailable("没有读取到微信公众号正文，请确认文章链接仍然有效。")
        return parser

    async def _fetch_page(self, url: str) -> str:
        last_error: ProviderUnavailable | None = None
        for api in self._article_apis:
            try:
                return await self._fetch_page_from_api(url, api)
            except ProviderUnavailable as exc:
                last_error = exc
                continue
        if not self._direct_fallback:
            raise last_error or ProviderUnavailable("没有可用的微信公众号正文 API")
        return await self._fetch_page_direct(url)

    async def _fetch_page_from_api(self, url: str, api: WeChatArticleApiConfig) -> str:
        parsed = urlparse(api.base_url)
        if (
            parsed.scheme != "https"
            or not parsed.hostname
            or parsed.username
            or parsed.password
            or parsed.port not in {None, 443}
        ):
            raise ProviderUnavailable(f"{api.name} 的接口地址不安全")
        if self._transport is None:
            try:
                addresses = await asyncio.to_thread(
                    lambda: {
                        str(item[4][0])
                        for item in socket.getaddrinfo(
                            parsed.hostname, None, type=socket.SOCK_STREAM
                        )
                    }
                )
            except OSError as exc:
                raise ProviderUnavailable(f"{api.name} 的接口域名无法解析") from exc
            if not addresses or any(not _is_public_ip(value) for value in addresses):
                raise ProviderUnavailable(f"{api.name} 的接口地址不是公网地址")
        headers = dict(_BROWSER_HEADERS)
        if api.api_key:
            headers[api.auth_header] = f"{api.auth_prefix}{api.api_key}"
        try:
            async with httpx.AsyncClient(
                headers=headers,
                timeout=self._timeout,
                follow_redirects=False,
                transport=self._transport,
            ) as client:
                async with client.stream(
                    "GET", api.base_url, params={"url": url, "format": "html"}
                ) as response:
                    if response.is_redirect:
                        raise ProviderUnavailable(f"{api.name} 返回了不受信任的跳转")
                    response.raise_for_status()
                    content_type = response.headers.get("content-type", "").casefold()
                    if "html" not in content_type and "text/plain" not in content_type:
                        raise ProviderUnavailable(f"{api.name} 没有返回 HTML")
                    chunks: list[bytes] = []
                    size = 0
                    async for chunk in response.aiter_bytes():
                        size += len(chunk)
                        if size > _MAX_HTML_CHARS:
                            raise ProviderUnavailable(f"{api.name} 返回的文章页面过大")
                        chunks.append(chunk)
                    text = b"".join(chunks).decode(
                        response.encoding or "utf-8", errors="replace"
                    )
        except httpx.HTTPError as exc:
            raise ProviderUnavailable(f"{api.name} 暂时不可用") from exc
        _validate_article_html(text, provider_name=api.name)
        return text

    async def _fetch_page_direct(self, url: str) -> str:
        try:
            async with httpx.AsyncClient(
                headers=_BROWSER_HEADERS,
                timeout=self._timeout,
                follow_redirects=False,
                transport=self._transport,
            ) as client:
                current_url = url
                for redirect_no in range(4):
                    parsed = urlparse(current_url)
                    if (
                        parsed.scheme != "https"
                        or parsed.hostname != _WECHAT_HOST
                        or parsed.username
                        or parsed.password
                        or parsed.port not in {None, 443}
                    ):
                        raise ProviderUnavailable("微信文章链接跳转到了非微信页面，已拒绝提取。")
                    async with client.stream("GET", current_url) as response:
                        if response.is_redirect:
                            location = response.headers.get("location")
                            if not location or redirect_no == 3:
                                raise ProviderUnavailable("微信文章跳转次数过多或地址无效。")
                            current_url = urljoin(current_url, location)
                            continue
                        response.raise_for_status()
                        chunks: list[bytes] = []
                        size = 0
                        async for chunk in response.aiter_bytes():
                            size += len(chunk)
                            if size > _MAX_HTML_CHARS:
                                raise ProviderUnavailable("微信文章页面过大，已停止提取。")
                            chunks.append(chunk)
                        text = b"".join(chunks).decode(
                            response.encoding or "utf-8", errors="replace"
                        )
                        break
        except httpx.HTTPError as exc:
            raise ProviderUnavailable("微信文章网络请求失败，暂时无法提取排版。") from exc
        final_url = str(response.url)
        if urlparse(final_url).hostname != _WECHAT_HOST:
            raise ProviderUnavailable("微信文章链接跳转到了非微信页面，已拒绝提取。")
        _raise_for_wechat_guard_page(text, final_url=final_url)
        _validate_article_html(text, provider_name="微信公众号")
        return text


def _is_public_ip(value: str) -> bool:
    address = ipaddress.ip_address(value)
    return not (
        address.is_private
        or address.is_loopback
        or address.is_link_local
        or address.is_multicast
        or address.is_reserved
        or address.is_unspecified
    )


def _validate_article_html(text: str, *, provider_name: str) -> None:
    folded = text.casefold()
    if 'id="js_content"' not in folded and "rich_media_content" not in folded:
        raise ProviderUnavailable(f"{provider_name} 没有返回可识别的微信公众号正文")


class _WeChatContentParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.samples: list[_Sample] = []
        self.title = ""
        self.account_name = ""
        self.image_count = 0
        self._capturing = False
        self._capture_depth = 0
        self._style_stack: list[dict[str, str]] = [{}]
        self._tag_stack: list[str] = []
        self._title_depth = 0
        self._name_depth = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attributes = {name.lower(): value or "" for name, value in attrs}
        if tag == "meta" and attributes.get("property") == "og:title":
            self.title = attributes.get("content", self.title).strip()
        if tag == "img" and self._capturing:
            self.image_count += 1
        if tag in {
            "area",
            "base",
            "br",
            "col",
            "embed",
            "hr",
            "img",
            "input",
            "link",
            "meta",
            "param",
            "source",
            "track",
            "wbr",
        }:
            return
        if attributes.get("id") == "activity-name":
            self._title_depth = 1
        if attributes.get("id") == "js_name":
            self._name_depth = 1
        if not self._capturing and _is_content_root(attributes):
            self._capturing = True
            self._capture_depth = 1
            self._style_stack = [_parse_style(attributes.get("style", ""))]
            self._tag_stack = [tag]
            return
        if self._capturing:
            self._capture_depth += 1
            merged = dict(self._style_stack[-1])
            merged.update(_parse_style(attributes.get("style", "")))
            if attributes.get("align") in {"left", "center", "right", "justify"}:
                merged["text-align"] = attributes["align"]
            self._style_stack.append(merged)
            self._tag_stack.append(tag)

    def handle_endtag(self, tag: str) -> None:
        if self._title_depth:
            self._title_depth -= 1
        if self._name_depth:
            self._name_depth -= 1
        if not self._capturing:
            return
        self._capture_depth -= 1
        if self._style_stack:
            self._style_stack.pop()
        if self._tag_stack:
            self._tag_stack.pop()
        if self._capture_depth <= 0:
            self._capturing = False
            self._capture_depth = 0
            self._style_stack = [{}]
            self._tag_stack = []

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self.handle_starttag(tag, attrs)
        if self._capturing and self._tag_stack and self._tag_stack[-1] == tag:
            self.handle_endtag(tag)

    def handle_data(self, data: str) -> None:
        text = " ".join(data.split())
        if not text:
            return
        if self._title_depth and not self.title:
            self.title = text
        if self._name_depth and not self.account_name:
            self.account_name = text
        if not self._capturing:
            return
        if any(tag in {"script", "style", "noscript", "svg"} for tag in self._tag_stack):
            return
        tag = next(
            (item for item in reversed(self._tag_stack) if item in _BLOCK_TAGS), self._tag_stack[-1]
        )
        self.samples.append(_Sample(tag=tag, text=text, style=dict(self._style_stack[-1])))


def _validate_url(url: str) -> str:
    value = str(url or "").strip()
    parsed = urlparse(value)
    if parsed.scheme != "https" or parsed.hostname != _WECHAT_HOST:
        raise ProviderUnavailable("请输入 mp.weixin.qq.com 的微信公众号文章链接。")
    if parsed.username or parsed.password or parsed.port not in {None, 443}:
        raise ProviderUnavailable("微信公众号文章链接不安全。")
    if not (parsed.path == "/s" or parsed.path.startswith("/s/")):
        raise ProviderUnavailable("该链接不是微信公众号公开文章地址。")
    return value


def _is_content_root(attributes: dict[str, str]) -> bool:
    classes = set(attributes.get("class", "").split())
    return attributes.get("id") == "js_content" or "rich_media_content" in classes


def _parse_style(value: str) -> dict[str, str]:
    parsed: dict[str, str] = {}
    for name, raw in _DECLARATION.findall(value):
        key = name.lower()
        if key in _TEXT_PROPERTIES:
            parsed[key] = raw.strip()
    return parsed


def _style_tokens(samples: list[_Sample]) -> dict[str, Any]:
    body = [
        sample
        for sample in samples
        if sample.tag in {"p", "div", "section"} and len(sample.text) >= 8
    ]
    numbered_heading_texts = _numbered_heading_text_samples(samples)
    numbered_heading_markers = _numbered_heading_marker_samples(samples)
    headings = numbered_heading_texts + [
        sample
        for sample in samples
        if sample not in numbered_heading_texts
        and not _is_numbered_heading_marker(sample)
        and (sample.tag in {"h1", "h2", "h3"} or _font_size(sample) >= 20)
    ]
    quotes = [sample for sample in samples if sample.tag == "blockquote" or _has_box_style(sample)]
    lists = [sample for sample in samples if sample.tag == "li"]
    captions = [
        sample for sample in samples if sample.tag == "figcaption" or 0 < _font_size(sample) <= 14
    ]
    title = headings[:1]
    heading1 = headings[1:8] or title
    heading2 = [
        sample for sample in headings[1:12] if _font_size(sample) < _font_size(title[0]) - 1
    ] or heading1
    tokens = {
        "body": _token_from_samples(body or samples),
        "title": _token_from_samples(
            title or heading1 or body[:1] or samples[:1], default_weight=700
        ),
        "heading1": _token_from_samples(heading1 or title or body[:1], default_weight=700),
        "heading2": _token_from_samples(
            heading2 or heading1 or title or body[:1], default_weight=600
        ),
        "lead": _token_from_samples(body[:2] or samples[:2]),
        "highlight": _token_from_samples(quotes or headings[1:4] or body[:1], keep_box=True),
        "quote": _token_from_samples(quotes or body[:1], keep_box=True),
        "list": _token_from_samples(lists or body[:1]),
        "caption": _token_from_samples(captions or body[-2:]),
    }
    if numbered_heading_markers:
        tokens["heading_marker"] = {
            **_token_from_samples(numbered_heading_markers, default_weight=700),
            "enabled": True,
        }
    tokens["divider"] = {"color": "#d1d5db", "margin_top": 16, "margin_bottom": 16}
    return {module: properties for module, properties in tokens.items() if properties}


def _numbered_heading_text_samples(samples: list[_Sample]) -> list[_Sample]:
    headings: list[_Sample] = []
    for index, sample in enumerate(samples[:-1]):
        if not _is_numbered_heading_marker(sample):
            continue
        for following in samples[index + 1 : index + 3]:
            if _is_heading_text_after_marker(following):
                headings.append(following)
            else:
                break
    return headings


def _numbered_heading_marker_samples(samples: list[_Sample]) -> list[_Sample]:
    markers: list[_Sample] = []
    for index, sample in enumerate(samples[:-1]):
        if _is_numbered_heading_marker(sample) and any(
            _is_heading_text_after_marker(following) for following in samples[index + 1 : index + 3]
        ):
            markers.append(sample)
    return markers


def _is_numbered_heading_marker(sample: _Sample) -> bool:
    weight = _font_weight(sample)
    return bool(_NUMBERED_HEADING_MARKER.fullmatch(sample.text.strip())) and (
        _font_size(sample) >= 18 or (weight is not None and weight >= 500)
    )


def _is_heading_text_after_marker(sample: _Sample) -> bool:
    weight = _font_weight(sample)
    return (
        2 <= len(sample.text) <= 40
        and weight is not None
        and weight >= 500
        and _align(sample.style.get("text-align", "")) == "center"
        and "。" not in sample.text
        and sample.text.count("，") <= 1
    )


def _token_from_samples(
    samples: list[_Sample],
    *,
    default_weight: int | None = None,
    keep_box: bool = False,
) -> dict[str, Any]:
    if not samples:
        return {}
    token: dict[str, Any] = {}
    if font_size := _weighted(samples, _font_size):
        token["font_size"] = font_size
    weight = _weighted(samples, _font_weight) or default_weight
    if weight:
        token["font_weight"] = weight
    if color := _weighted(samples, lambda item: _color(item.style.get("color", ""))):
        token["color"] = color
    if align := _weighted(samples, lambda item: _align(item.style.get("text-align", ""))):
        token["align"] = align
    if line_height := _weighted(samples, _line_height):
        token["line_height"] = line_height
    if margin_top := _weighted(samples, lambda item: _dimension(item.style.get("margin-top", ""))):
        token["margin_top"] = margin_top
    if margin_bottom := _weighted(samples, _margin_bottom):
        token["margin_bottom"] = margin_bottom
    if text_indent := _weighted(
        samples, lambda item: _dimension(item.style.get("text-indent", ""))
    ):
        token["text_indent"] = text_indent
    if padding := _weighted(samples, _padding):
        token["padding"] = padding
    if keep_box:
        if background := _weighted(samples, _background):
            token["background"] = background
        if border_left := _weighted(
            samples, lambda item: _border_left(item.style.get("border-left", ""))
        ):
            token["border_left"] = border_left
    return token


def _weighted(samples: list[_Sample], getter: Any) -> Any:
    counter: Counter[Any] = Counter()
    for sample in samples:
        value = getter(sample)
        if value not in {None, "", 0}:
            counter[value] += sample.weight
    return counter.most_common(1)[0][0] if counter else None


def _font_size(sample: _Sample) -> int:
    value = _dimension(sample.style.get("font-size", ""))
    return int(value or 0)


def _font_weight(sample: _Sample) -> int | None:
    value = sample.style.get("font-weight", "")
    if not value:
        return 400
    if value in {"bold", "bolder"}:
        return 700
    try:
        number = int(float(value))
    except ValueError:
        return None
    if number >= 650:
        return 700
    if number >= 550:
        return 600
    if number >= 450:
        return 500
    return 400


def _dimension(value: str) -> int | None:
    match = _NUMBER.search(value)
    if not match:
        return None
    number = round(float(match.group()))
    return number if 0 <= number <= 72 else None


def _line_height(sample: _Sample) -> float | None:
    value = sample.style.get("line-height", "")
    match = _NUMBER.search(value)
    if not match:
        return None
    number = float(match.group())
    if value.endswith("px"):
        size = _font_size(sample)
        number = number / size if size else 0
    return round(number, 2) if 1 <= number <= 3 else None


def _margin_bottom(sample: _Sample) -> int | None:
    return _dimension(sample.style.get("margin-bottom", "")) or _box_index(
        sample.style.get("margin", ""), -1
    )


def _padding(sample: _Sample) -> int | None:
    return (
        _dimension(sample.style.get("padding", ""))
        or _dimension(sample.style.get("padding-left", ""))
        or _dimension(sample.style.get("padding-right", ""))
    )


def _box_index(value: str, index: int) -> int | None:
    numbers = [round(float(item)) for item in _NUMBER.findall(value)]
    if not numbers:
        return None
    if len(numbers) == 1:
        return numbers[0]
    if index == -1:
        return numbers[2] if len(numbers) >= 3 else numbers[0]
    return numbers[index] if index < len(numbers) else None


def _color(value: str) -> str | None:
    candidate = value.strip().lower()
    if _HEX_COLOR.fullmatch(candidate):
        if len(candidate) == 4:
            return "#" + "".join(character * 2 for character in candidate[1:])
        return candidate[:7]
    hex_match = re.search(r"#(?:[0-9a-fA-F]{8}|[0-9a-fA-F]{6}|[0-9a-fA-F]{3})", candidate)
    if hex_match:
        return _color(hex_match.group())
    match = _RGB_COLOR.search(candidate)
    if match:
        channels = [min(255, int(channel)) for channel in match.groups()]
        return "#" + "".join(f"{channel:02x}" for channel in channels)
    return None


def _background(sample: _Sample) -> str | None:
    return _color(sample.style.get("background-color", "")) or _color(
        sample.style.get("background", "")
    )


def _border_left(value: str) -> str | None:
    color = _color(value)
    width = _dimension(value)
    if color and width:
        return f"{min(width, 12)}px solid {color}"
    return None


def _align(value: str) -> str | None:
    if not value:
        return "left"
    return value if value in {"left", "center", "right", "justify"} else None


def _has_box_style(sample: _Sample) -> bool:
    return bool(_background(sample) or _border_left(sample.style.get("border-left", "")))


def _raise_for_wechat_guard_page(page: str, *, final_url: str) -> None:
    lowered = page.casefold()
    if 'id="js_content"' in lowered or "rich_media_content" in lowered:
        return
    if any(
        marker in lowered or marker in final_url
        for marker in (
            "appmsgcaptcha",
            "security_check",
            "captcha",
            "环境异常",
            "请在微信客户端打开",
            "访问过于频繁",
            "去验证",
        )
    ):
        raise ProviderUnavailable("微信返回了安全验证页，请稍后重试或换一篇公开文章。")
    if any(
        marker in lowered
        for marker in (
            "已被删除",
            "内容已被发布者删除",
            "已停止访问该网页",
            "链接无法访问",
            "内容不存在",
        )
    ):
        raise ProviderUnavailable("这篇微信文章已删除、停用或不可公开访问，无法提取排版。")
