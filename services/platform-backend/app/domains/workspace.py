from __future__ import annotations

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.errors import ApiError
from app.models import Article, Asset, Document, LibraryItem, Project, Task, utcnow


async def owned_project(session: AsyncSession, *, owner_id: str, project_id: str) -> Project:
    project = await session.scalar(
        select(Project).where(
            Project.id == project_id,
            Project.owner_id == owner_id,
            Project.deleted_at.is_(None),
        )
    )
    if not project:
        raise ApiError(404, "PROJECT_NOT_FOUND", "项目不存在。")
    return project


async def owned_task(session: AsyncSession, *, owner_id: str, task_id: str) -> Task:
    task = await session.scalar(
        select(Task).where(
            Task.id == task_id,
            Task.owner_id == owner_id,
            Task.deleted_at.is_(None),
        )
    )
    if not task:
        raise ApiError(404, "TASK_NOT_FOUND", "任务不存在。")
    return task


async def delete_project_keep_contents(
    session: AsyncSession, *, owner_id: str, project_id: str
) -> None:
    project = await owned_project(session, owner_id=owner_id, project_id=project_id)
    now = utcnow()
    project.deleted_at = now
    await session.execute(
        update(Task)
        .where(Task.owner_id == owner_id, Task.project_id == project_id)
        .values(project_id=None)
    )
    await session.execute(
        update(Article)
        .where(Article.owner_id == owner_id, Article.project_id == project_id)
        .values(project_id=None)
    )
    await session.execute(
        update(Asset)
        .where(Asset.owner_id == owner_id, Asset.project_id == project_id)
        .values(project_id=None)
    )
    await session.execute(
        update(Document)
        .where(Document.owner_id == owner_id, Document.project_id == project_id)
        .values(project_id=None)
    )
    await session.execute(
        update(LibraryItem)
        .where(LibraryItem.owner_id == owner_id, LibraryItem.project_id == project_id)
        .values(project_id=None)
    )
