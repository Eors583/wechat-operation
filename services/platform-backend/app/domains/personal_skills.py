"""Shared personal-skill creation for settings and explicit conversation actions."""

import hashlib
import json

from sqlalchemy.ext.asyncio import AsyncSession

from app.errors import ApiError
from app.models import AuditLog, Skill, SkillVersion, UserSkillSetting, new_uuid
from app.system_settings import published_setting_section


async def create_personal_skill(
    session: AsyncSession,
    *,
    owner_id: str,
    name: str,
    instructions: str,
    scenario: str,
    description: str = "",
    category: str = "content",
    example_article: str | None = None,
    code: str | None = None,
) -> tuple[Skill, SkillVersion]:
    settings = await published_setting_section(session, "features")
    flags = settings.get("feature_flags", {})
    if isinstance(flags, dict) and flags.get("personal_skills") is False:
        raise ApiError(403, "PERSONAL_SKILLS_DISABLED", "个人技能功能当前已停用。")
    if not (
        1 <= len(name.strip()) <= 120
        and 1 <= len(instructions.strip()) <= 20_000
        and 1 <= len(scenario.strip()) <= 2000
        and len(description) <= 1000
        and len(category) <= 80
        and (example_article is None or len(example_article) <= 50_000)
    ):
        raise ApiError(422, "SKILL_CONTENT_INVALID", "技能名称或内容不完整或过长，未保存。")
    skill = Skill(
        scope="personal",
        owner_id=owner_id,
        code=code or f"user-{owner_id[:8]}-{new_uuid()[:8]}",
        name=name.strip(),
        description=description,
        category=category,
        status="published",
        current_version_no=1,
    )
    session.add(skill)
    await session.flush()
    payload = {
        "instructions": instructions,
        "input_schema": {"scenario": scenario, "example_article": example_article},
        "output_schema": {"type": "article"},
        "tool_policy": {"wechat_publish": False},
    }
    version = SkillVersion(
        skill_id=skill.id,
        version_no=1,
        status="published",
        checksum=hashlib.sha256(
            json.dumps(payload, sort_keys=True, ensure_ascii=False).encode()
        ).hexdigest(),
        **payload,
    )
    session.add(version)
    session.add(UserSkillSetting(user_id=owner_id, skill_id=skill.id, enabled=True))
    session.add(
        AuditLog(
            actor_type="user",
            actor_id=owner_id,
            action="skill.create",
            target_type="skill",
            target_id=skill.id,
        )
    )
    return skill, version
