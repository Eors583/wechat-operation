from __future__ import annotations

import hashlib
import io
import zipfile

import pytest

from app.providers import ProviderUnavailable
from tests.fakes import InMemoryStorageProvider, LocalDocumentProcessingProvider


def _pptx(*slides: str) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        slide_ids = "".join(
            f'<p:sldId id="{255 + page_no}" r:id="rId{page_no}" />'
            for page_no in range(1, len(slides) + 1)
        )
        archive.writestr(
            "ppt/presentation.xml",
            "<p:presentation "
            'xmlns:p="http://schemas.openxmlformats.org/presentationml/2006/main" '
            'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">'
            f"<p:sldIdLst>{slide_ids}</p:sldIdLst></p:presentation>",
        )
        relationships = "".join(
            "<Relationship "
            f'Id="rId{page_no}" '
            'Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/slide" '
            f'Target="slides/slide{len(slides) - page_no + 1}.xml" />'
            for page_no in range(1, len(slides) + 1)
        )
        archive.writestr(
            "ppt/_rels/presentation.xml.rels",
            "<Relationships "
            'xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
            f"{relationships}</Relationships>",
        )
        for page_no, text in enumerate(slides, start=1):
            archive.writestr(
                f"ppt/slides/slide{len(slides) - page_no + 1}.xml",
                '<p:sld xmlns:p="http://schemas.openxmlformats.org/presentationml/2006/main" '
                'xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main">'
                f"<p:cSld><a:p><a:r><a:t>{text}</a:t></a:r></a:p></p:cSld></p:sld>",
            )
    return buffer.getvalue()


async def test_local_document_processor_extracts_pptx_by_slide() -> None:
    content = _pptx("市场洞察", "战略解码")
    storage = InMemoryStorageProvider()
    await storage.put_bytes(
        object_key="owner/reference.pptx",
        content=content,
        mime_type="application/vnd.openxmlformats-officedocument.presentationml.presentation",
        sha256=hashlib.sha256(content).hexdigest(),
    )

    result = await LocalDocumentProcessingProvider(storage).process(
        object_key="owner/reference.pptx",
        filename="战略规划.pptx",
        mime_type="application/vnd.openxmlformats-officedocument.presentationml.presentation",
        size_bytes=len(content),
        sha256=hashlib.sha256(content).hexdigest(),
    )

    assert result.parser_version == "local-pptx-xml-v1"
    assert result.page_count == 2
    assert [(section.page_no, section.text) for section in result.sections] == [
        (1, "市场洞察"),
        (2, "战略解码"),
    ]
    assert "第 1 页\n市场洞察" in result.extracted_text
    assert "第 2 页\n战略解码" in result.extracted_text


async def test_local_document_processor_rejects_pptx_without_text() -> None:
    content = _pptx("")
    storage = InMemoryStorageProvider()
    await storage.put_bytes(
        object_key="owner/empty.pptx",
        content=content,
        mime_type="application/vnd.openxmlformats-officedocument.presentationml.presentation",
        sha256=hashlib.sha256(content).hexdigest(),
    )

    with pytest.raises(ProviderUnavailable, match="没有可提取的文字"):
        await LocalDocumentProcessingProvider(storage).process(
            object_key="owner/empty.pptx",
            filename="empty.pptx",
            mime_type="application/vnd.openxmlformats-officedocument.presentationml.presentation",
            size_bytes=len(content),
            sha256=hashlib.sha256(content).hexdigest(),
        )
