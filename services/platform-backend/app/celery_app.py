from __future__ import annotations

import logging

from celery import Celery

from app.config import Settings

settings = Settings.from_env()

# httpx includes full query strings in INFO messages. Presigned upload URLs carry
# temporary credentials, so provider adapters emit their own redacted diagnostics.
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("httpcore").setLevel(logging.WARNING)

celery = Celery(
    "wechat_ai_platform",
    broker=settings.celery_broker_url,
    backend=settings.celery_result_backend,
    include=["app.worker_tasks"],
)
celery.conf.update(
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],
    timezone="UTC",
    enable_utc=True,
    task_acks_late=True,
    task_reject_on_worker_lost=True,
    task_publish_retry=True,
    broker_connection_retry_on_startup=True,
    task_default_queue="ai",
    task_default_queue_type="quorum",
    broker_transport_options={"confirm_publish": True},
    task_routes={
        "app.worker_tasks.process_ai_run_task": {"queue": "ai"},
        "app.worker_tasks.process_ai_run_memory_task": {"queue": "ai"},
        "app.worker_tasks.process_article_revision_task": {"queue": "ai"},
        "app.worker_tasks.process_document_task": {"queue": "files"},
        "app.worker_tasks.process_document_index_task": {"queue": "embedding"},
        "app.worker_tasks.process_layout_extraction_task": {"queue": "files"},
        "app.worker_tasks.process_article_index_task": {"queue": "embedding"},
        "app.worker_tasks.process_external_knowledge_sync_task": {"queue": "sync"},
        "app.worker_tasks.enqueue_due_external_knowledge_syncs_task": {"queue": "maintenance"},
        "app.worker_tasks.process_wechat_operation_task": {"queue": "wechat"},
        "app.worker_tasks.reconcile_wechat_operation_task": {"queue": "wechat"},
        "app.worker_tasks.relay_outbox_task": {"queue": "maintenance"},
        "app.worker_tasks.purge_due_accounts_task": {"queue": "maintenance"},
    },
    beat_schedule={
        "relay-transactional-outbox": {
            "task": "app.worker_tasks.relay_outbox_task",
            "schedule": 2.0,
        },
        "purge-due-accounts": {
            "task": "app.worker_tasks.purge_due_accounts_task",
            "schedule": 3600.0,
        },
        "enqueue-due-external-knowledge-syncs": {
            "task": "app.worker_tasks.enqueue_due_external_knowledge_syncs_task",
            "schedule": 300.0,
        },
    },
)
