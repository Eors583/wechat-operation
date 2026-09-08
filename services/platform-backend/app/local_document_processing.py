from __future__ import annotations

import hashlib
import io
import posixpath
import zipfile
from typing import Protocol
from xml.etree import ElementTree

from app.providers import (
    DocumentProcessingResult,
    DocumentSectionResult,
    ProviderUnavailable,
    StorageProvider,
)

PPTX_MIME = "application/vnd.openxmlformats-officedocument.presentationml.presentation"
TEXT_MIME_TYPES = {"text/plain", "text/markdown", "text/csv", "text/html"}
MAX_DOCUMENT_BYTES = 100 * 1024 * 1024
MAX_ZIP_ENTRIES = 10_000
MAX_ZIP_UNCOMPRESSED_BYTES = 250 * 1024 * 1024
MAX_ZIP_COMPRESSION_RATIO = 200


class DocumentScanner(Protocol):
    async def scan(self, content: bytes) -> None: ...


class BuiltInDocumentScanner:
    async def scan(self, content: bytes) -> None:
        eicar_marker = b"EICAR-STANDARD-ANTIVIRUS-TEST-FILE"
        if eicar_marker in content or content.startswith((b"MZ", b"\x7fELF")):
            raise ProviderUnavailable("文件未通过安全检查。")


class LocalDocumentProcessingProvider:
    def __init__(self, storage: StorageProvider, scanner: DocumentScanner) -> None:
        self._storage = storage
        self._scanner = scanner

    async def process(
        self,
        *,
        object_key: str,
        filename: str,
        mime_type: str,
        size_bytes: int,
        sha256: str,
    ) -> DocumentProcessingResult:
        del filename
        if size_bytes > MAX_DOCUMENT_BYTES:
            raise ProviderUnavailable("文件超过文档处理大小限制。")
        content = await self._storage.read_bytes(
            object_key=object_key, max_bytes=MAX_DOCUMENT_BYTES
        )
        if len(content) != size_bytes or hashlib.sha256(content).hexdigest() != sha256:
            raise ProviderUnavailable("文件内容与上传记录不一致。")
        await self._scanner.scan(content)
        if mime_type in TEXT_MIME_TYPES:
            extracted = content.decode("utf-8", errors="replace").strip()
            if not extracted:
                raise ProviderUnavailable("文件中没有可提取的文字。")
            return DocumentProcessingResult(
                extracted_text=extracted,
                parser_version="local-text-v1",
                page_count=1,
                sections=(DocumentSectionResult("page", extracted, page_no=1),),
            )
        if mime_type == PPTX_MIME:
            return self._process_pptx(content)
        raise ProviderUnavailable("当前文档格式暂不支持解析。")

    @staticmethod
    def _validate_archive(archive: zipfile.ZipFile) -> None:
        entries = archive.infolist()
        if len(entries) > MAX_ZIP_ENTRIES:
            raise ProviderUnavailable("PPTX 文件包含过多条目。")
        total_size = 0
        for entry in entries:
            normalized = posixpath.normpath(entry.filename.replace("\\", "/"))
            if normalized.startswith("/") or normalized == ".." or normalized.startswith("../"):
                raise ProviderUnavailable("PPTX 文件包含不安全的路径。")
            if entry.flag_bits & 0x1:
                raise ProviderUnavailable("不支持加密的 PPTX 文件。")
            total_size += entry.file_size
            if total_size > MAX_ZIP_UNCOMPRESSED_BYTES:
                raise ProviderUnavailable("PPTX 解压后的内容过大。")
            if entry.file_size > 1024 and entry.compress_size == 0:
                raise ProviderUnavailable("PPTX 压缩结构无效。")
            if (
                entry.compress_size > 0
                and entry.file_size / entry.compress_size > MAX_ZIP_COMPRESSION_RATIO
            ):
                raise ProviderUnavailable("PPTX 压缩比例异常。")

    @classmethod
    def _process_pptx(cls, content: bytes) -> DocumentProcessingResult:
        drawing_ns = "http://schemas.openxmlformats.org/drawingml/2006/main"
        rels_ns = "http://schemas.openxmlformats.org/package/2006/relationships"
        document_rels_ns = (
            "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
        )
        try:
            with zipfile.ZipFile(io.BytesIO(content)) as archive:
                cls._validate_archive(archive)
                presentation = ElementTree.fromstring(archive.read("ppt/presentation.xml"))
                relationships = ElementTree.fromstring(
                    archive.read("ppt/_rels/presentation.xml.rels")
                )
                targets = {
                    item.attrib["Id"]: posixpath.normpath(
                        posixpath.join("ppt", item.attrib["Target"])
                    )
                    for item in relationships.iter(f"{{{rels_ns}}}Relationship")
                    if item.attrib.get("Type", "").endswith("/slide")
                }
                paths = [
                    targets[item.attrib[f"{{{document_rels_ns}}}id"]]
                    for item in presentation.iter(
                        "{http://schemas.openxmlformats.org/presentationml/2006/main}sldId"
                    )
                ]
                sections = []
                for page_no, path in enumerate(paths, start=1):
                    root = ElementTree.fromstring(archive.read(path))
                    text = "\n".join(
                        "".join(
                            node.text or ""
                            for node in paragraph.iter(f"{{{drawing_ns}}}t")
                        )
                        for paragraph in root.iter(f"{{{drawing_ns}}}p")
                    ).strip()
                    sections.append(
                        DocumentSectionResult(
                            "page", text, f"第 {page_no} 页", page_no=page_no
                        )
                    )
        except (KeyError, zipfile.BadZipFile, ElementTree.ParseError, OSError) as exc:
            raise ProviderUnavailable("PPTX 文件结构无效或无法读取。") from exc
        extracted = "\n\n".join(
            f"{section.title}\n{section.text}" for section in sections if section.text
        )
        if not extracted:
            raise ProviderUnavailable("PPTX 中没有可提取的文字。")
        return DocumentProcessingResult(
            extracted_text=extracted,
            parser_version="local-pptx-xml-v1",
            page_count=len(sections),
            sections=tuple(sections),
        )
