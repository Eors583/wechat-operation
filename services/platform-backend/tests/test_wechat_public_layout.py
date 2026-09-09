from __future__ import annotations

import httpx
import pytest

from app.providers import ProviderUnavailable
from app.wechat_public_layout import WeChatArticleApiConfig, WeChatPublicLayoutExtractionProvider


@pytest.mark.asyncio
async def test_wechat_public_layout_extracts_inline_article_styles() -> None:
    html = """
    <html>
      <head><meta property="og:title" content="品牌内容策略"></head>
      <body>
        <span id="js_name">蓝雪研究</span>
        <div id="js_content" class="rich_media_content">
          <section style="font-size:28px;font-weight:700;color:#111827;margin-bottom:24px">
            品牌内容策略：从信息堆砌到清晰表达
          </section>
          <p style="font-size:16px;line-height:1.9;color:rgb(31,41,55);
                    margin-bottom:18px;text-indent:32px">
            在信息爆炸的时代，品牌更需要有策略的内容输出。
          </p>
          <blockquote style="font-size:15px;color:#4b5563;background-color:#f3f4f6;
                             border-left:4px solid #059669;padding:12px">
            只有目标清晰，表达才不会散。
          </blockquote>
          <ul><li style="font-size:16px;color:#1f2937">标题先交代价值判断</li></ul>
          <p style="font-size:13px;color:#6b7280;text-align:center">图片说明</p>
          <script>alert(1)</script>
        </div>
      </body>
    </html>
    """

    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text=html)

    provider = WeChatPublicLayoutExtractionProvider(transport=httpx.MockTransport(handler))
    result = await provider.extract(source_url="https://mp.weixin.qq.com/s/demo")

    assert result.extractor_version == "wechat-public-dom-v1"
    assert result.source_snapshot["title"] == "品牌内容策略"
    assert result.source_snapshot["account_name"] == "蓝雪研究"
    assert "品牌内容策略：从信息堆砌到清晰表达" in result.source_snapshot["text_preview"]
    assert result.source_snapshot["text_samples"]
    observation = result.source_snapshot["layout_observation"]
    assert observation["schema_version"] == 1
    assert observation["samples"][0] == {
        "id": "block-1",
        "order": 1,
        "tag_hint": "section",
        "text_excerpt": "品牌内容策略：从信息堆砌到清晰表达",
        "computed_style": {
            "font-size": "28px",
            "font-weight": "700",
            "color": "#111827",
            "margin-bottom": "24px",
        },
    }
    assert result.style_tokens["title"]["font_size"] == 28
    assert result.style_tokens["body"]["line_height"] == 1.9
    assert result.style_tokens["body"]["color"] == "#1f2937"
    assert result.style_tokens["body"]["font_weight"] == 400
    assert result.style_tokens["body"]["align"] == "left"
    assert result.style_tokens["quote"]["background"] == "#f3f4f6"
    assert result.style_tokens["quote"]["border_left"] == "4px solid #059669"
    assert result.style_tokens["caption"]["align"] == "center"


@pytest.mark.asyncio
async def test_wechat_article_api_returns_downloaded_article_html() -> None:
    requests: list[httpx.Request] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(
            200,
            headers={"content-type": "text/html; charset=utf-8"},
            text=(
                '<html><meta property="og:title" content="第三方正文">'
                '<div id="js_content"><p>'
                + "这是通过第三方接口读取的微信公众号正文。" * 8
                + "</p></div></html>"
            ),
        )

    provider = WeChatPublicLayoutExtractionProvider(
        transport=httpx.MockTransport(handler),
        article_apis=[
            WeChatArticleApiConfig(
                name="mptext",
                base_url="https://down.mptext.top/api/public/v1/download",
                api_key="secret-key",
            )
        ],
        direct_fallback=False,
    )
    result = await provider.fetch_reference(source_url="https://mp.weixin.qq.com/s/example")

    assert result.title == "第三方正文"
    assert "第三方接口读取" in result.text
    assert requests[0].url.params["format"] == "html"
    assert requests[0].url.params["url"] == "https://mp.weixin.qq.com/s/example"
    assert requests[0].headers["X-Auth-Key"] == "secret-key"


@pytest.mark.asyncio
async def test_wechat_article_api_falls_back_in_priority_order() -> None:
    hosts: list[str] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        hosts.append(str(request.url.host))
        if request.url.host == "first.example.com":
            return httpx.Response(429, text="rate limited")
        return httpx.Response(
            200,
            headers={"content-type": "text/html"},
            text='<div id="js_content"><p>' + "备用接口正文内容。" * 12 + "</p></div>",
        )

    provider = WeChatPublicLayoutExtractionProvider(
        transport=httpx.MockTransport(handler),
        article_apis=[
            WeChatArticleApiConfig("second", "https://second.example.com/download", 20),
            WeChatArticleApiConfig("first", "https://first.example.com/download", 10),
        ],
        direct_fallback=False,
    )
    result = await provider.fetch_reference(source_url="https://mp.weixin.qq.com/s/example")

    assert "备用接口正文" in result.text
    assert hosts == ["first.example.com", "second.example.com"]


@pytest.mark.asyncio
async def test_wechat_public_layout_keeps_article_specific_styles() -> None:
    first_html = """
    <html><body><div id="js_content" class="rich_media_content">
      <p style="font-size:15px;color:#123456;text-align:left">
        第一篇文章的正文样式明显不同，这里补充足够长的文字用于通过正文有效性校验。
      </p>
    </div></body></html>
    """
    second_html = """
    <html><body><div id="js_content" class="rich_media_content">
      <p style="font-size:19px;color:#654321;text-align:right">
        第二篇文章的正文样式明显不同，这里补充足够长的文字用于通过正文有效性校验。
      </p>
    </div></body></html>
    """

    def handler(request: httpx.Request) -> httpx.Response:
        html = first_html if request.url.path.endswith("/first") else second_html
        return httpx.Response(200, text=html)

    provider = WeChatPublicLayoutExtractionProvider(transport=httpx.MockTransport(handler))

    first = await provider.extract(source_url="https://mp.weixin.qq.com/s/first")
    second = await provider.extract(source_url="https://mp.weixin.qq.com/s/second")

    assert first.source_snapshot["text_preview"] != second.source_snapshot["text_preview"]
    assert first.style_tokens["body"] != second.style_tokens["body"]


@pytest.mark.asyncio
async def test_wechat_public_layout_rejects_invalid_original_article_page() -> None:
    requests: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(str(request.url))
        return httpx.Response(200, text="<html><body>链接无法访问</body></html>")

    provider = WeChatPublicLayoutExtractionProvider(transport=httpx.MockTransport(handler))

    with pytest.raises(ProviderUnavailable, match="已删除、停用或不可公开访问"):
        await provider.extract(source_url="https://mp.weixin.qq.com/s/not-real")

    assert requests == ["https://mp.weixin.qq.com/s/not-real"]


@pytest.mark.asyncio
async def test_wechat_public_layout_uses_heading_text_not_number_marker_style() -> None:
    html = """
    <html><body><div id="js_content" class="rich_media_content">
      <p style="font-size:16px;color:#595959;text-align:center;line-height:35px">
        这是一段足够长的正文，用来识别正文样式。
      </p>
      <p style="font-size:24px;color:#ff4c00;text-align:center;font-weight:bold">06</p>
      <p style="font-size:17px;color:#595959;text-align:center;font-weight:bold">沉默的操盘手</p>
      <p style="font-size:16px;color:#595959;text-align:center;line-height:35px">
        如果只能用一句话概括库克，那便是沉默的操盘手。
      </p>
    </div></body></html>
    """

    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text=html)

    provider = WeChatPublicLayoutExtractionProvider(transport=httpx.MockTransport(handler))
    result = await provider.extract(source_url="https://mp.weixin.qq.com/s/numbered-heading")

    assert result.style_tokens["heading1"]["font_size"] == 17
    assert result.style_tokens["heading1"]["color"] == "#595959"
    assert result.style_tokens["heading1"]["color"] != "#ff4c00"
    assert result.style_tokens["heading_marker"]["enabled"] is True
    assert result.style_tokens["heading_marker"]["font_size"] == 24
    assert result.style_tokens["heading_marker"]["color"] == "#ff4c00"
    assert result.style_tokens["body"]["font_weight"] == 400
