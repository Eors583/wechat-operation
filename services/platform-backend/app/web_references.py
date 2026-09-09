from __future__ import annotations

import asyncio
import ipaddress
import re
import socket
from collections.abc import Awaitable, Callable
from html import unescape
from html.parser import HTMLParser
from urllib.parse import urljoin, urlparse

import httpx

from app.providers import ProviderUnavailable, WebReferenceContent
from app.wechat_public_layout import WeChatArticleApiConfig

MAX_RESPONSE_BYTES = 2 * 1024 * 1024
MAX_EXTRACTED_CHARACTERS = 300_000
MAX_REDIRECTS = 3

HostResolver = Callable[[str], Awaitable[list[str]]]


def extract_message_links(text: str) -> list[str]:
    """Recognize pasted/Markdown HTTP links without swallowing adjacent Chinese requests."""
    links: list[str] = []
    for match in re.finditer(r"https?://[^\s<>\"`，。！？；、（）【】“”‘’]+", text):
        value = unescape(match.group())
        # WeChat article URLs use ASCII paths/queries; users often append “帮我改写” directly.
        if value.startswith("https://mp.weixin.qq.com/"):
            value = re.split(r"[\u3400-\u9fff]", value, maxsplit=1)[0]
        value = value.rstrip(".,;!'")
        for opening, closing in (("(", ")"), ("[", "]"), ("{", "}")):
            while value.endswith(closing) and value.count(closing) > value.count(opening):
                value = value[:-1]
        if value not in links:
            links.append(value)
    return links


class _PageTextExtractor(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.fragments: list[str] = []
        self.title_fragments: list[str] = []
        self.article_fragments: list[str] = []
        self.main_fragments: list[str] = []
        self._article_depth = 0
        self._main_depth = 0
        self._ignored_depth = 0
        self._in_title = False

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        del attrs
        if tag in {"script", "style", "noscript", "svg", "nav", "aside", "footer", "form"}:
            self._ignored_depth += 1
        if tag == "article":
            self._article_depth += 1
        if tag == "main":
            self._main_depth += 1
        if tag == "title":
            self._in_title = True

    def handle_endtag(self, tag: str) -> None:
        if (
            tag in {"script", "style", "noscript", "svg", "nav", "aside", "footer", "form"}
            and self._ignored_depth
        ):
            self._ignored_depth -= 1
        if tag == "article":
            self._article_depth = max(0, self._article_depth - 1)
        if tag == "main":
            self._main_depth = max(0, self._main_depth - 1)
        if tag == "title":
            self._in_title = False

    def handle_data(self, data: str) -> None:
        if self._ignored_depth:
            return
        value = " ".join(data.split())
        if not value:
            return
        if self._in_title:
            self.title_fragments.append(value)
        self.fragments.append(value)
        if self._article_depth:
            self.article_fragments.append(value)
        if self._main_depth:
            self.main_fragments.append(value)


async def _resolve_public_addresses(hostname: str) -> list[str]:
    def resolve() -> list[str]:
        return list(
            {
                str(item[4][0])
                for item in socket.getaddrinfo(hostname, None, type=socket.SOCK_STREAM)
            }
        )

    return await asyncio.to_thread(resolve)


def _is_public_address(value: str) -> bool:
    address = ipaddress.ip_address(value)
    return not (
        address.is_private
        or address.is_loopback
        or address.is_link_local
        or address.is_multicast
        or address.is_reserved
        or address.is_unspecified
    )


class SafeHttpWebReferenceProvider:
    """Bounded, read-only webpage fetcher with SSRF and redirect protection."""

    def __init__(
        self,
        *,
        timeout_seconds: float = 12.0,
        transport: httpx.AsyncBaseTransport | None = None,
        resolver: HostResolver | None = None,
        article_apis: list[WeChatArticleApiConfig] | None = None,
    ) -> None:
        self._timeout = timeout_seconds
        self._transport = transport
        self._resolver = resolver or _resolve_public_addresses
        self._article_apis = article_apis
        self._semaphore = asyncio.Semaphore(8)

    async def _validate_url(self, url: str) -> None:
        parsed = urlparse(url)
        if (
            parsed.scheme not in {"http", "https"}
            or not parsed.hostname
            or parsed.username
            or parsed.password
        ):
            raise ProviderUnavailable("Web reference URL is invalid")
        if parsed.port not in {None, 80, 443}:
            raise ProviderUnavailable("Web reference URL uses a disallowed port")
        try:
            addresses = await self._resolver(parsed.hostname)
        except OSError as exc:
            raise ProviderUnavailable("Web reference hostname could not be resolved") from exc
        if not addresses or any(not _is_public_address(value) for value in addresses):
            raise ProviderUnavailable("Web reference hostname is not public")

    async def fetch(self, url: str) -> WebReferenceContent:
        async with self._semaphore:
            parsed = urlparse(url)
            if parsed.scheme == "https" and parsed.hostname == "mp.weixin.qq.com":
                await self._validate_url(url)
                from app.wechat_public_layout import WeChatPublicLayoutExtractionProvider

                return await WeChatPublicLayoutExtractionProvider(
                    timeout_seconds=self._timeout,
                    transport=self._transport,
                    article_apis=self._article_apis,
                ).fetch_reference(source_url=url)
            return await self._fetch(url)

    async def _fetch(self, url: str) -> WebReferenceContent:
        requested_url = url
        current_url = url
        async with httpx.AsyncClient(
            timeout=self._timeout,
            transport=self._transport,
            follow_redirects=False,
            headers={"User-Agent": "WechatAIOperationsBot/1.0", "Accept": "text/html,text/plain"},
        ) as client:
            for redirect_no in range(MAX_REDIRECTS + 1):
                await self._validate_url(current_url)
                try:
                    async with client.stream("GET", current_url) as response:
                        if response.is_redirect:
                            location = response.headers.get("location")
                            if not location or redirect_no == MAX_REDIRECTS:
                                raise ProviderUnavailable("Web reference redirect is invalid")
                            current_url = urljoin(current_url, location)
                            continue
                        response.raise_for_status()
                        content_type = response.headers.get("content-type", "").split(";", 1)[0]
                        if content_type not in {"text/html", "text/plain"}:
                            raise ProviderUnavailable("Web reference content type is unsupported")
                        declared_size = response.headers.get("content-length")
                        if declared_size:
                            try:
                                oversized = int(declared_size) > MAX_RESPONSE_BYTES
                            except ValueError as exc:
                                raise ProviderUnavailable(
                                    "Web reference content length is invalid"
                                ) from exc
                            if oversized:
                                raise ProviderUnavailable("Web reference is too large")
                        chunks: list[bytes] = []
                        size = 0
                        async for chunk in response.aiter_bytes():
                            size += len(chunk)
                            if size > MAX_RESPONSE_BYTES:
                                raise ProviderUnavailable("Web reference is too large")
                            chunks.append(chunk)
                        response_bytes = b"".join(chunks)
                        encoding = response.encoding or "utf-8"
                        body = response_bytes.decode(encoding, errors="replace")
                except httpx.HTTPError as exc:
                    raise ProviderUnavailable("Web reference could not be fetched") from exc
                if content_type == "text/html":
                    parser = _PageTextExtractor()
                    parser.feed(body)
                    text = "\n".join(
                        parser.article_fragments or parser.main_fragments or parser.fragments
                    )
                    title = " ".join(parser.title_fragments).strip()
                else:
                    text = body
                    title = ""
                text = text.strip()[:MAX_EXTRACTED_CHARACTERS]
                if not text:
                    raise ProviderUnavailable("Web reference did not contain readable text")
                return WebReferenceContent(
                    requested_url=requested_url,
                    final_url=current_url,
                    title=title or urlparse(current_url).hostname or "网页参考资料",
                    text=text,
                    content_type=content_type,
                )
        raise ProviderUnavailable("Web reference redirect limit exceeded")
