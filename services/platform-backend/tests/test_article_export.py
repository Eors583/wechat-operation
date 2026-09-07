import io
import zipfile

import pytest
from fastapi import FastAPI
from httpx import AsyncClient
from reportlab.pdfbase import pdfmetrics

from app import article_export
from app.article_export import export_article
from app.errors import ApiError
from app.models import Article, ArticleRender, ArticleVersion
from tests.conftest import bearer, register_and_login

HTML = """<h1 style="font-size:24px;color:#123456">下载排版测试</h1>
<p style="font-size:16px;color:#123456;line-height:1.8">中文正文，<strong>重要结论</strong>。</p>
<table><tr><th>项目</th><th>结果</th></tr><tr><td>测试一</td><td>完整保留</td></tr></table>"""


def test_real_formats_keep_content_and_word_styles() -> None:
    markdown = export_article(HTML, "title", "md").decode()
    assert "# 下载排版测试" in markdown and "**重要结论**" in markdown
    assert "完整保留" in markdown
    pdf = export_article(HTML, "title", "pdf")
    assert pdf.startswith(b"%PDF-") and len(pdf) > 1000
    word = export_article(HTML, "title", "docx")
    with zipfile.ZipFile(io.BytesIO(word)) as archive:
        xml = archive.read("word/document.xml").decode()
    assert "完整保留" in xml and 'w:val="123456"' in xml and "w:tbl" in xml


def test_converter_never_fetches_untrusted_images() -> None:
    with pytest.raises(ApiError, match="图片"):
        export_article('<p>正文</p><img src="http://127.0.0.1/secret">', "title", "pdf")


def test_pdf_bold_uses_distinct_embedded_font(monkeypatch: pytest.MonkeyPatch) -> None:
    fragments = {}
    original = article_export.Paragraph

    def capture(*args, **kwargs):
        paragraph = original(*args, **kwargs)
        fragments.update((fragment.text, fragment.fontName) for fragment in paragraph.frags)
        return paragraph

    monkeypatch.setattr(article_export, "Paragraph", capture)
    pdf = export_article(
        "<p>普通正文<strong>强调</strong><b>加粗</b>"
        '<span style="font-weight: 700">数字字重</span>'
        '<span style="font-weight: bold">文字字重</span></p>',
        "标题",
        "pdf",
    )
    assert fragments["普通正文"] == "STSong-Light"
    for text in ("强调", "加粗", "数字字重", "文字字重"):
        assert fragments[text] == "NotoSansSC-Bold"
    regular = pdfmetrics.getFont("STSong-Light")
    bold = pdfmetrics.getFont("NotoSansSC-Bold")
    assert regular is not bold
    assert regular.face.name != bold.face.name
    assert b"NotoSansSC-Regular" in pdf
    assert b"NotoSansSC-Bold" in pdf


async def test_download_requires_owned_render(client: AsyncClient, app: FastAPI) -> None:
    response = await client.get("/api/v1/article-renders/missing/download?format=pdf")
    assert response.status_code == 401
    login = await register_and_login(client, "export-owner@example.com")
    response = await client.get(
        "/api/v1/article-renders/missing/download?format=pdf", headers=bearer(login["access_token"])
    )
    assert response.status_code == 404
    owner = login["registered_user"]["id"]
    async with app.state.database.session_maker() as session:
        article = Article(owner_id=owner, title="最新版标题", current_version_no=2)
        session.add(article)
        await session.flush()
        version = ArticleVersion(
            article_id=article.id,
            version_no=1,
            plain_text="旧文章",
            content_hash="old",
            source="manual",
            created_by_type="user",
            created_by_id=owner,
        )
        session.add(version)
        await session.flush()
        render = ArticleRender(
            owner_id=owner,
            article_id=article.id,
            article_version_id=version.id,
            html=HTML,
            checksum="old-render",
            compatibility_status="passed",
        )
        session.add(render)
        await session.commit()
    stranger = await register_and_login(client, "export-stranger@example.com")
    url = f"/api/v1/article-renders/{render.id}/download"
    hidden = await client.get(url + "?format=pdf", headers=bearer(stranger["access_token"]))
    assert hidden.status_code == 404
    for format, signature in [("md", b"# "), ("pdf", b"%PDF-"), ("docx", b"PK")]:
        result = await client.get(url + "?format=" + format, headers=bearer(login["access_token"]))
        assert result.status_code == 200, result.text[:200]
        assert result.content.startswith(signature)
        assert "attachment" in result.headers["content-disposition"]
        assert result.headers["cache-control"] == "private, no-store"
        if format == "md":
            assert "最新版标题" not in result.text
