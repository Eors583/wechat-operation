import hashlib
import uuid

from fastapi import FastAPI
from httpx import AsyncClient
from sqlalchemy import select

from app.models import AuditLog, LibraryItem
from tests.conftest import bearer, register_and_login


async def test_reuploads_reuse_library_not_chat_documents(
    client: AsyncClient, app: FastAPI
) -> None:
    owner = await register_and_login(client, "dedup@example.com")
    stranger = await register_and_login(client, "dedup-other@example.com")

    async def upload(token: str, name: str, content: bytes, project_id: str | None = None) -> dict:
        headers = bearer(token)
        digest = hashlib.sha256(content).hexdigest()
        response = await client.post(
            "/api/v1/uploads",
            headers={**headers, "Idempotency-Key": str(uuid.uuid4())},
            json={
                "filename": name,
                "mime_type": "text/plain",
                "size_bytes": len(content),
                "sha256": digest,
                "project_id": project_id,
            },
        )
        assert response.status_code == 201, response.text
        data = response.json()
        part = await client.put(data["part_urls"][0], content=content)
        assert part.status_code == 204
        completed = await client.post(
            f"/api/v1/uploads/{data['upload']['id']}/complete",
            headers={**headers, "Idempotency-Key": str(uuid.uuid4())},
            json={
                "size_bytes": len(content),
                "sha256": digest,
                "completed_parts": [{"part_number": 1, "etag": part.headers["etag"]}],
                "save_to_library": True,
            },
        )
        assert completed.status_code == 200, completed.text
        return completed.json()

    first = await upload(owner["access_token"], "reference.txt", b"original text")
    # Simulate a historical duplicate without touching its underlying document.
    async with app.state.database.session_maker() as session:
        original = await session.get(LibraryItem, first["library_item"]["id"])
        assert original is not None
        duplicate = LibraryItem(
            owner_id=original.owner_id,
            item_type="document",
            source_id="legacy-placeholder",
            title="legacy",
            display_status="ready",
            search_text="legacy",
        )
        # A second real upload below supplies the historical document to reference.
    repeated = await upload(owner["access_token"], "renamed.txt", b"original text")
    async with app.state.database.session_maker() as session:
        duplicate.source_id = repeated["document"]["id"]
        session.add(duplicate)
        await session.commit()
    await upload(owner["access_token"], "third-name.txt", b"original text")
    async with app.state.database.session_maker() as session:
        archived = await session.get(LibraryItem, duplicate.id)
        assert archived is not None and archived.deleted_at is not None
        assert await session.scalar(select(AuditLog).where(AuditLog.target_id == duplicate.id))
    changed = await upload(owner["access_token"], "reference.txt", b"different text")
    other = await upload(stranger["access_token"], "reference.txt", b"original text")
    assert first["library_item"]["id"] == repeated["library_item"]["id"]
    assert first["document"]["id"] != repeated["document"]["id"]
    assert changed["library_item"]["id"] != first["library_item"]["id"]
    assert other["library_item"]["id"] != first["library_item"]["id"]
    library = await client.get("/api/v1/library-items", headers=bearer(owner["access_token"]))
    assert len(library.json()["items"]) == 2
    project = await client.post(
        "/api/v1/projects", headers=bearer(owner["access_token"]), json={"name": "Separate"}
    )
    assert project.status_code == 201
    separate = await upload(
        owner["access_token"], "reference.txt", b"original text", project.json()["id"]
    )
    assert separate["library_item"]["id"] != first["library_item"]["id"]
    for data in (first, repeated):
        detail = await client.get(
            f"/api/v1/documents/{data['document']['id']}",
            headers=bearer(owner["access_token"]),
        )
        assert detail.status_code == 200
