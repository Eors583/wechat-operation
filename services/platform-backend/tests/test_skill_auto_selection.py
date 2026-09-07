from __future__ import annotations

import pytest
from httpx import AsyncClient

from app.domains.ai import _skill_match_score
from app.models import Skill, SkillVersion
from scripts.seed_official_article_skills import OFFICIAL_ARTICLE_SKILLS, version_payload

from .conftest import bearer, register_and_login


@pytest.mark.parametrize(
    ("message", "expected_code"),
    [
        ("根据这个PPT帮我写一篇公众号文章", "source_to_article"),
        ("写一篇关于战略执行底层逻辑的深度文章", "deep_opinion_article"),
        ("参考这篇文章的风格，根据新资料仿写一篇", "reference_style_rewrite"),
        ("帮我拆解并复盘这个企业管理案例", "case_study_article"),
        ("根据最近的行业新闻写一篇热点评论", "hot_topic_commentary"),
        ("写一篇从零开始的操作指南和避坑清单", "practical_guide_article"),
    ],
)
def test_bundled_article_skill_scenarios_rank_the_expected_skill(
    message: str, expected_code: str
) -> None:
    ranked: list[tuple[int, str]] = []
    for definition in OFFICIAL_ARTICLE_SKILLS:
        skill = Skill(
            scope="official",
            code=definition["code"],
            name=definition["name"],
            description=definition["description"],
            category=definition["category"],
        )
        version = SkillVersion(
            skill_id="test",
            version_no=1,
            checksum="test",
            status="published",
            **version_payload(definition),
        )
        ranked.append((_skill_match_score(message, skill, version), skill.code))

    assert max(ranked)[1] == expected_code


async def test_enabled_matching_skill_is_selected_and_version_is_frozen(
    client: AsyncClient,
) -> None:
    login = await register_and_login(client, "auto-skill@example.com")
    headers = bearer(login["access_token"])
    skill = await client.post(
        "/api/v1/skills",
        headers=headers,
        json={
            "name": "科技产品评测",
            "scenario": "科技产品评测",
            "instructions": "从真实使用场景、优点和局限三个方面进行评测。",
        },
    )
    assert skill.status_code == 201, skill.text
    skill_id = skill.json()["skill"]["id"]
    version_id = skill.json()["version"]["id"]

    created = await client.post(
        "/api/v1/tasks",
        headers={**headers, "Idempotency-Key": "auto-skill-task"},
        json={
            "first_message": {
                "text": "请写一篇科技产品评测，主题是折叠屏手机",
                "content": {},
                "client_message_id": "auto-skill-message",
            }
        },
    )
    assert created.status_code == 202, created.text
    assert created.json()["task"]["current_skill_id"] == skill_id
    run = await client.get(f"/api/v1/ai-runs/{created.json()['ai_run']['id']}", headers=headers)
    assert run.json()["skill_version_id"] == version_id
    assert run.json()["context_snapshot"]["skill_selection"] == "automatic"


async def test_disabled_skill_is_not_selected_automatically(client: AsyncClient) -> None:
    login = await register_and_login(client, "disabled-auto-skill@example.com")
    headers = bearer(login["access_token"])
    skill = await client.post(
        "/api/v1/skills",
        headers=headers,
        json={
            "name": "餐厅探店",
            "scenario": "餐厅探店",
            "instructions": "描述环境、菜品和服务。",
        },
    )
    skill_id = skill.json()["skill"]["id"]
    disabled = await client.patch(
        f"/api/v1/skills/{skill_id}/setting",
        headers=headers,
        json={"enabled": False},
    )
    assert disabled.status_code == 200

    created = await client.post(
        "/api/v1/tasks",
        headers={**headers, "Idempotency-Key": "disabled-auto-skill-task"},
        json={
            "first_message": {
                "text": "请写一篇餐厅探店文章",
                "content": {},
                "client_message_id": "disabled-auto-skill-message",
            }
        },
    )
    assert created.status_code == 202, created.text
    assert created.json()["task"]["current_skill_id"] is None
    assert created.json()["ai_run"]["skill_version_id"] is None
