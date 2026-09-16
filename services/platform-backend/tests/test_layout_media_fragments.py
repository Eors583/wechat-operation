from bs4 import BeautifulSoup

from app.layout_content import (
    extract_content_blocks,
    native_wechat_profile_cards,
    sanitize_content_html,
)


def test_empty_svg_separator_keeps_lines_without_media_placeholder() -> None:
    source = """<section data-tools="xiumi" style="display:flex;align-items:center">
    <section style="height:1px;flex:100 100 0%;align-self:center;background-color:#cd9f5b">
    <svg style="width:0;line-height:0" viewBox="0 0 1 1"></svg></section>
    <span>••••</span>
    <section style="height:1px;flex:100 100 0%;align-self:center;background-color:#cd9f5b">
    <svg style="width:0" viewBox="0 0 1 1"></svg></section></section>"""
    clean = sanitize_content_html(sanitize_content_html(source))
    assert "此媒体请在原文查看" not in clean
    assert "<svg" not in clean
    assert clean.count("height:1px") == 2
    assert clean.count("flex:100 100 0%") == 2
    assert clean.count("align-self:center") == 2
    assert "••••" in clean
    blocks = extract_content_blocks(f'<div id="js_content">{source}</div>')
    assert len(blocks) == 1
    assert "••••" in blocks[0]["html"]


def test_videosnap_cover_and_native_metadata_survive_repeated_sanitization() -> None:
    source = """<mp-common-videosnap data-id="export/video_123" data-nonceid="1234"
    data-username="example@finder" data-width="1920" data-height="1440"
    data-url="https://findermp.video.qq.com/cover.jpg?token=example&amp;picformat=200"
    data-desc="视频介绍" data-nickname="视频号名称" onclick="alert(1)">
    <script>alert(1)</script></mp-common-videosnap>"""
    clean = sanitize_content_html(sanitize_content_html(source))
    soup = BeautifulSoup(clean, "html.parser")
    card = soup.select_one('figure[data-videosnap-card="true"]')
    assert card is not None
    image = card.find("img")
    assert image is not None and "cover.jpg" in image["src"]
    assert not soup.find("script") and "onclick" not in clean
    native = BeautifulSoup(native_wechat_profile_cards(clean), "html.parser")
    video = native.find("mp-common-videosnap")
    assert video is not None
    assert video["data-id"] == "export/video_123"
    assert video["data-nonceid"] == "1234"
    assert video["data-url"].endswith("token=example&picformat=200")
    assert video["data-desc"] == "视频介绍"
    blocks = extract_content_blocks(f'<div id="js_content">{source}</div>')
    assert len(blocks) == 1 and 'data-videosnap-card="true"' in blocks[0]["html"]


def test_videosnap_rejects_active_and_private_cover_urls() -> None:
    for url in ("javascript:alert(1)", "https://127.0.0.1/secret", "data:image/svg+xml,evil"):
        clean = sanitize_content_html(f'<mp-common-videosnap data-url="{url}"/>')
        assert "<img" not in clean
        assert 'data-url=' not in clean
