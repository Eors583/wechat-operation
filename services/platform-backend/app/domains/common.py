from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.errors import ApiError
from app.models import (
    AuditLog,
    IdempotencyRecord,
    InboxMessage,
    JobRecord,
    OutboxEvent,
    utcnow,
)
from app.security import request_hash


@dataclass(slots=True)
class IdempotencyAttempt:
    record: IdempotencyRecord
    cached_body: dict[str, Any] | None = None
    cached_status: int | None = None


async def begin_idempotency(
    session: AsyncSession,
    *,
    actor_type: str,
    actor_id: str,
    scope: str,
    key: str | None,
    payload: Any,
) -> IdempotencyAttempt:
    if not key or len(key) > 120:
        raise ApiError(
            400,
            "IDEMPOTENCY_KEY_REQUIRED",
            "该操作需要有效的 Idempotency-Key 请求头。",
        )
    digest = request_hash(payload)

    def replay(existing: IdempotencyRecord) -> IdempotencyAttempt:
        if existing.request_hash != digest:
            raise ApiError(
                409,
                "IDEMPOTENCY_KEY_CONFLICT",
                "该幂等键已用于不同请求。",
            )
        if existing.status == "completed" and existing.response_body is not None:
            return IdempotencyAttempt(existing, existing.response_body, existing.response_status)
        raise ApiError(
            409,
            "IDEMPOTENCY_IN_PROGRESS",
            "相同操作仍在处理中，请稍后查询结果。",
            retryable=True,
        )

    existing = await session.scalar(
        select(IdempotencyRecord).where(
            IdempotencyRecord.actor_type == actor_type,
            IdempotencyRecord.actor_id == actor_id,
            IdempotencyRecord.scope == scope,
            IdempotencyRecord.key == key,
        )
    )
    if existing:
        return replay(existing)
    record = IdempotencyRecord(
        actor_type=actor_type,
        actor_id=actor_id,
        scope=scope,
        key=key,
        request_hash=digest,
    )
    try:
        async with session.begin_nested():
            session.add(record)
            await session.flush()
    except IntegrityError:
        winner = await session.scalar(
            select(IdempotencyRecord).where(
                IdempotencyRecord.actor_type == actor_type,
                IdempotencyRecord.actor_id == actor_id,
                IdempotencyRecord.scope == scope,
                IdempotencyRecord.key == key,
            )
        )
        if not winner:
            raise
        return replay(winner)
    return IdempotencyAttempt(record)


def complete_idempotency(
    attempt: IdempotencyAttempt, body: dict[str, Any], status_code: int = 200
) -> None:
    attempt.record.status = "completed"
    attempt.record.response_status = status_code
    attempt.record.response_body = body
    attempt.record.completed_at = utcnow()


def emit_outbox(
    session: AsyncSession,
    *,
    event_type: str,
    aggregate_type: str,
    aggregate_id: str,
    payload: dict[str, Any],
) -> OutboxEvent:
    event = OutboxEvent(
        event_type=event_type,
        aggregate_type=aggregate_type,
        aggregate_id=aggregate_id,
        payload=payload,
    )
    session.add(event)
    return event


def create_job(
    session: AsyncSession,
    *,
    owner_id: str | None,
    job_type: str,
    resource_type: str,
    resource_id: str,
    queue: str,
    stage: str,
    frozen_payload: dict[str, Any],
) -> JobRecord:
    job = JobRecord(
        owner_id=owner_id,
        job_type=job_type,
        resource_type=resource_type,
        resource_id=resource_id,
        queue=queue,
        stage=stage,
        frozen_payload=frozen_payload,
    )
    session.add(job)
    return job


def audit(
    session: AsyncSession,
    *,
    actor_type: str,
    actor_id: str,
    action: str,
    target_type: str,
    target_id: str | None,
    request_id: str | None,
    reason: str | None = None,
    details: dict[str, Any] | None = None,
) -> AuditLog:
    log = AuditLog(
        actor_type=actor_type,
        actor_id=actor_id,
        action=action,
        target_type=target_type,
        target_id=target_id,
        request_id=request_id,
        reason=reason,
        details=details or {},
    )
    session.add(log)
    return log


async def processed_inbox_message(
    session: AsyncSession, *, consumer: str, message_id: str | None
) -> InboxMessage | None:
    if not message_id:
        return None
    return await session.scalar(
        select(InboxMessage).where(
            InboxMessage.consumer == consumer,
            InboxMessage.message_id == message_id,
        )
    )


def remember_inbox_message(
    session: AsyncSession,
    *,
    consumer: str,
    message_id: str | None,
    result: dict[str, Any],
) -> None:
    if message_id:
        session.add(InboxMessage(consumer=consumer, message_id=message_id, result=result))
