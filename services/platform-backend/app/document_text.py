"""Bounded document text extraction subprocess. No network or file execution."""

from __future__ import annotations

import io
import json
import sys
import zipfile


def extract() -> dict:
    if sys.platform == "linux":
        import resource

        resource.setrlimit(resource.RLIMIT_AS, (256 * 1024 * 1024, 256 * 1024 * 1024))
        resource.setrlimit(resource.RLIMIT_CPU, (45, 45))
    content = sys.stdin.buffer.read(100 * 1024 * 1024 + 1)
    if len(content) > 100 * 1024 * 1024:
        return {"error_code": "DOCUMENT_PARSE_LIMIT", "message": "文件过大，请拆分后重试。"}
    if sys.argv[1] == "pptx":
        from app.local_document_processing import LocalDocumentProcessingProvider

        result = LocalDocumentProcessingProvider._process_pptx(content)
        if len(result.sections) > 500 or len(result.extracted_text) > 1_000_000:
            return {
                "error_code": "DOCUMENT_PARSE_LIMIT",
                "message": "PPTX 内容过多，请拆分后重试。",
            }
        return {"pages": [section.text for section in result.sections]}
    if sys.argv[1] == "docx":
        from docx import Document
        from docx.text.paragraph import Paragraph

        from app.local_document_processing import LocalDocumentProcessingProvider

        with zipfile.ZipFile(io.BytesIO(content)) as archive:
            LocalDocumentProcessingProvider._validate_archive(archive)
        document = Document(io.BytesIO(content))
        blocks = []
        size = 0
        for block in document.iter_inner_content():
            text = (
                block.text
                if isinstance(block, Paragraph)
                else "\n".join("\t".join(cell.text for cell in row.cells) for row in block.rows)
            )
            size += len(text)
            if size > 1_000_000:
                return {
                    "error_code": "DOCUMENT_PARSE_LIMIT",
                    "message": "文档文字量过大，请拆分后重试。",
                }
            blocks.append(text)
        text = "\n\n".join(blocks).strip()
        if not text:
            return {"error_code": "DOCUMENT_TEXT_EMPTY", "message": "Word 文档中没有可提取的文字。"}
        return {"pages": [text]}
    from pypdf import PdfReader

    reader = PdfReader(io.BytesIO(content))
    if reader.is_encrypted and not reader.decrypt(""):
        return {"error_code": "DOCUMENT_ENCRYPTED", "message": "PDF 已加密，请解密后重新上传。"}
    if len(reader.pages) > 500:
        return {"error_code": "DOCUMENT_PARSE_LIMIT", "message": "PDF 超过 500 页，请拆分后重试。"}
    pages: list[str] = []
    text_length = 0
    for page in reader.pages:
        text = (page.extract_text() or "").strip()
        text_length += len(text)
        if text_length > 1_000_000:
            return {
                "error_code": "DOCUMENT_PARSE_LIMIT",
                "message": "PDF 文字量过大，请拆分后重试。",
            }
        pages.append(text)
    if not any(pages):
        return {
            "error_code": "DOCUMENT_OCR_REQUIRED",
            "message": "PDF 没有可提取的文字，可能是扫描件；请先进行 OCR 或上传文字版。",
        }
    return {"pages": pages}


if __name__ == "__main__":
    try:
        output = extract()
    except MemoryError:
        output = {
            "error_code": "DOCUMENT_PARSE_LIMIT",
            "message": "文档解析内存不足，请拆分后重试。",
        }
    except Exception:
        output = {
            "error_code": "DOCUMENT_PARSE_FAILED",
            "message": "文件损坏或无法解析，请重新导出后上传。",
        }
    sys.stdout.buffer.write(json.dumps(output, ensure_ascii=False).encode("utf-8"))
