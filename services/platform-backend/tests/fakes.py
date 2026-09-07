from __future__ import annotations

import hashlib
import io
import posixpath
import secrets
import zipfile
from pathlib import Path
from typing import Any
from xml.etree import ElementTree

from app.providers import (
    CompletedUploadPart,
    DocumentProcessingResult,
    DocumentSectionResult,
    InvalidMultipartUpload,
    ModelResult,
    ProviderUnavailable,
    UploadDescriptor,
    WebReferenceContent,
)


class UnavailableModelProvider:
    async def generate(
        self, *, purpose: str, prompt: str, context: dict[str, Any]
    ) -> ModelResult:
        raise ProviderUnavailable("The test did not install a model response")


class AllowAllContentSafetyProvider:
    async def check_text(self, text: str) -> tuple[bool, str | None]:
        return True, None


class StaticWebReferenceProvider:
    async def fetch(self, url: str) -> WebReferenceContent:
        return WebReferenceContent(
            requested_url=url,
            final_url=url,
            title="测试网页参考资料",
            text=f"这是从 {url} 读取的测试网页正文。",
            content_type="text/html",
        )


class InMemoryStorageProvider:
    def __init__(self, *, persistence_dir: Path | None = None) -> None:
        self._persistence_dir = persistence_dir
        self._uploads: dict[str, dict[str, Any]] = {}
        self._direct_objects: dict[str, bytes] = {}
        self._object_tokens: dict[str, str] = {}
        self._request_tokens: dict[str, str] = {}

    async def read_bytes(self, *, object_key: str, max_bytes: int) -> bytes:
        content = self.object_bytes(object_key)
        if content is None:
            raise ProviderUnavailable("Original file is no longer available")
        if len(content) > max_bytes:
            raise ProviderUnavailable("Original file exceeds upload limit")
        return content

    async def put_bytes(
        self, *, object_key: str, content: bytes, mime_type: str, sha256: str
    ) -> None:
        del mime_type
        if hashlib.sha256(content).hexdigest() != sha256:
            raise ProviderUnavailable("Object content hash does not match metadata")
        self._direct_objects[object_key] = bytes(content)
        self._persist(object_key, content)

    def _persist(self, object_key: str, content: bytes) -> None:
        if self._persistence_dir is None:
            return
        self._persistence_dir.mkdir(parents=True, exist_ok=True)
        target = self._persistence_dir / hashlib.sha256(object_key.encode()).hexdigest()
        temporary = target.with_suffix(f".{secrets.token_hex(8)}.tmp")
        temporary.write_bytes(content)
        temporary.replace(target)

    async def create_multipart_upload(
        self,
        *,
        object_key: str,
        part_count: int,
        mime_type: str,
        sha256: str,
        request_token: str,
    ) -> UploadDescriptor:
        token = self._request_tokens.get(request_token)
        if token:
            upload = self._uploads[token]
            if (
                upload["object_key"] != object_key
                or upload["part_count"] != part_count
                or upload["mime_type"] != mime_type
                or upload["sha256"] != sha256
            ):
                raise InvalidMultipartUpload("request token was reused for a different upload")
            return self._descriptor(token, part_count)
        token = secrets.token_urlsafe(48)
        self._uploads[token] = {
            "object_key": object_key,
            "part_count": part_count,
            "mime_type": mime_type,
            "sha256": sha256,
            "parts": {},
            "etags": {},
            "completed": False,
        }
        self._object_tokens[object_key] = token
        self._request_tokens[request_token] = token
        return self._descriptor(token, part_count)

    @staticmethod
    def _descriptor(token: str, part_count: int) -> UploadDescriptor:
        return UploadDescriptor(
            provider_upload_id=f"test:{token}",
            part_urls=[f"/test/uploads/{token}/parts/{part}" for part in range(1, part_count + 1)],
        )

    async def complete_multipart_upload(
        self,
        *,
        provider_upload_id: str,
        object_key: str,
        parts: list[CompletedUploadPart],
    ) -> None:
        if not provider_upload_id.startswith("test:"):
            raise InvalidMultipartUpload("test upload identifier is invalid")
        token = provider_upload_id.removeprefix("test:")
        upload = self._uploads.get(token)
        if not upload or upload["object_key"] != object_key:
            raise InvalidMultipartUpload("multipart upload does not exist")
        expected = list(range(1, int(upload["part_count"]) + 1))
        if [part.part_number for part in parts] != expected:
            raise InvalidMultipartUpload("multipart upload is incomplete")
        etags = upload["etags"]
        if any(etags.get(part.part_number) != part.etag for part in parts):
            raise InvalidMultipartUpload("multipart ETag does not match the uploaded part")
        upload["completed"] = True
        content = self.object_bytes(object_key)
        if content is not None:
            self._persist(object_key, content)

    async def verify_object(self, *, object_key: str, size_bytes: int, sha256: str) -> bool:
        content = self.object_bytes(object_key)
        return bool(
            content is not None
            and len(content) == size_bytes
            and hashlib.sha256(content).hexdigest() == sha256
        )

    async def delete_object(self, *, object_key: str) -> None:
        if self._persistence_dir is not None:
            (self._persistence_dir / hashlib.sha256(object_key.encode()).hexdigest()).unlink(
                missing_ok=True
            )
        self._direct_objects.pop(object_key, None)
        token = self._object_tokens.pop(object_key, None)
        if token:
            self._uploads.pop(token, None)

    def put_part(self, *, token: str, part_number: int, content: bytes) -> str:
        upload = self._uploads[token]
        if upload["completed"]:
            raise ValueError("multipart upload is already completed")
        if part_number < 1 or part_number > int(upload["part_count"]):
            raise ValueError("part number is outside the multipart upload")
        upload["parts"][part_number] = content
        etag = hashlib.sha256(content).hexdigest()
        upload["etags"][part_number] = etag
        return etag

    def object_bytes(self, object_key: str) -> bytes | None:
        if self._persistence_dir is not None:
            path = self._persistence_dir / hashlib.sha256(object_key.encode()).hexdigest()
            if path.is_file():
                return path.read_bytes()
        if object_key in self._direct_objects:
            return self._direct_objects[object_key]
        upload = self._uploads.get(self._object_tokens.get(object_key, ""))
        if not upload or not upload["completed"]:
            return None
        parts = upload["parts"]
        expected = range(1, int(upload["part_count"]) + 1)
        if any(index not in parts for index in expected):
            return None
        return b"".join(parts[index] for index in expected)


class LocalDocumentProcessingProvider:
    def __init__(self, storage: InMemoryStorageProvider | None = None) -> None:
        self._storage = storage

    async def process(
        self,
        *,
        object_key: str,
        filename: str,
        mime_type: str,
        size_bytes: int,
        sha256: str,
    ) -> DocumentProcessingResult:
        del filename, size_bytes, sha256
        content = self._storage.object_bytes(object_key) if self._storage else None
        if content is None:
            raise ProviderUnavailable("Test object does not exist")
        if mime_type in {"text/plain", "text/markdown", "text/csv", "text/html"}:
            extracted = content.decode("utf-8", errors="replace")
            return DocumentProcessingResult(
                extracted_text=extracted,
                parser_version="test-text-v1",
                page_count=1,
                sections=(DocumentSectionResult("page", extracted, page_no=1),),
            )
        if mime_type == "application/vnd.openxmlformats-officedocument.presentationml.presentation":
            return self._process_pptx(content)
        raise ProviderUnavailable("The test processor does not support this media type")

    @staticmethod
    def _process_pptx(content: bytes) -> DocumentProcessingResult:
        drawing_ns = "http://schemas.openxmlformats.org/drawingml/2006/main"
        rels_ns = "http://schemas.openxmlformats.org/package/2006/relationships"
        document_rels_ns = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
        try:
            with zipfile.ZipFile(io.BytesIO(content)) as archive:
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
                        "".join(node.text or "" for node in paragraph.iter(f"{{{drawing_ns}}}t"))
                        for paragraph in root.iter(f"{{{drawing_ns}}}p")
                    ).strip()
                    sections.append(
                        DocumentSectionResult("page", text, f"第 {page_no} 页", page_no=page_no)
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
