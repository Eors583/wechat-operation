from __future__ import annotations

from copy import deepcopy
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import SystemSetting

AI_RUN_CREDIT_COST_DEFAULT = 1
AI_RUN_CREDIT_COST_MAX = 10_000


def ai_run_credit_cost(values: dict[str, Any]) -> int:
    value = values.get("ai_run_credit_cost", AI_RUN_CREDIT_COST_DEFAULT)
    if type(value) is not int or not 0 <= value <= AI_RUN_CREDIT_COST_MAX:
        raise ValueError("单次 AI 运行积分必须是 0—10000 之间的整数。")
    return value


DEFAULT_SYSTEM_SETTINGS: dict[str, dict[str, Any]] = {
    "home": {
        "welcome_message": "今天想创作什么？",
        "example_prompts": [
            "根据这份资料写一篇公众号文章",
            "把这篇旧文章重新改写",
            "围绕这个主题先给我几个选题",
        ],
    },
    "files": {
        "allowed_extensions": [
            "pdf",
            "docx",
            "pptx",
            "xlsx",
            "csv",
            "txt",
            "md",
            "html",
            "png",
            "jpg",
            "jpeg",
            "mp3",
            "m4a",
            "mp4",
        ],
        "max_file_mb": 200,
        "link_fetch_enabled": True,
    },
    "ai": {
        "ai_run_credit_cost": AI_RUN_CREDIT_COST_DEFAULT,
        "max_clarification_rounds": 2,
        "min_article_length": 300,
        "max_article_length": 12_000,
        "preference_enabled_by_default": True,
    },
    "articles": {"autosave_seconds": 20, "history_versions": 50},
    "wechat": {
        "wechat_draft_enabled": True,
        "wechat_publish_enabled": True,
        "max_article_images": 30,
    },
    "features": {
        "feature_flags": {
            "personal_skills": True,
            "template_extraction": True,
            "external_knowledge": False,
            "visual_understanding": True,
        }
    },
}


async def published_system_settings(session: AsyncSession) -> dict[str, dict[str, Any]]:
    merged = deepcopy(DEFAULT_SYSTEM_SETTINGS)
    rows = list(
        (
            await session.scalars(
                select(SystemSetting)
                .where(SystemSetting.status == "published")
                .order_by(SystemSetting.section, SystemSetting.version_no.desc())
            )
        ).all()
    )
    seen: set[str] = set()
    for row in rows:
        if row.section in seen or row.section not in merged:
            continue
        seen.add(row.section)
        merged[row.section].update(row.values)
    return merged


async def published_setting_section(session: AsyncSession, section: str) -> dict[str, Any]:
    return (await published_system_settings(session))[section]
