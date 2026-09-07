from __future__ import annotations

import asyncio
import hashlib
import json
from textwrap import dedent
from typing import Any

from sqlalchemy import select

from app.config import Settings
from app.database import Database
from app.domains.common import audit
from app.models import Skill, SkillVersion


def _instructions(value: str) -> str:
    return dedent(value).strip()


OFFICIAL_ARTICLE_SKILLS: tuple[dict[str, Any], ...] = (
    {
        "code": "source_to_article",
        "name": "资料转公众号文章",
        "description": "将PPT、PDF、Word、会议纪要和调研资料整理为完整公众号文章。",
        "category": "文章创作",
        "sort_order": 1,
        "scenario": (
            "根据PPT写文章、根据PDF写文章、根据Word写文章、资料整理成文章、"
            "会议纪要转文章、调研报告改写、文档提炼成公众号文章"
        ),
        "instructions": _instructions(
            """
            你负责把用户提供的PPT、PDF、Word、会议纪要、访谈或调研资料改写成完整的
            微信公众号文章。先识别主题、目标读者、关键结论和事实材料，再重组为标题、导语、
            主体章节和结尾；不得机械照搬文件目录或逐页复述。资料没有提供的数字、人物、日期、
            引语和因果关系不得补写成事实。不写“根据这份PPT”“本资料主要介绍”“以下是整理结果”
            等过程说明。文件名、页码、页眉页脚、制作人、作者、来源、机构署名和版权信息都是
            元数据，不得进入新文章正文。除非用户本轮明确要求，正文不得出现“作者｜”“撰文：”
            “来源｜”等署名段落。最终返回一篇可独立阅读、内容完整、可直接预览的文章。
            """
        ),
    },
    {
        "code": "deep_opinion_article",
        "name": "深度观点文章",
        "description": "围绕商业、管理、科技和职场议题生成判断清晰、论证充分的深度文章。",
        "category": "文章创作",
        "sort_order": 2,
        "scenario": (
            "深度文章、观点文章、行业分析、商业洞察、管理思考、趋势分析、如何看待、为什么、底层逻辑"
        ),
        "instructions": _instructions(
            """
            你负责围绕用户主题创作深度观点文章。先形成一个明确且可论证的核心判断；导语提出
            真实矛盾或问题，主体依次解释现象、原因、作用机制、影响和行动启示，每一节都必须
            推进论证。适当说明反例、限制或不同立场，区分资料事实、合理推断和作者观点。不要用
            大量口号、连续小标题或项目符号制造虚假的深度感；没有资料支持时不得虚构企业内部
            决策、人物讲话、经营数字或引用。结尾回到读者现实并形成有价值的判断。除非用户本轮
            明确要求，正文不得包含作者、来源、公众号或机构署名。
            """
        ),
    },
    {
        "code": "reference_style_rewrite",
        "name": "参考风格改写",
        "description": "参考示例文章的结构、语气和节奏，基于新主题与新资料创作原创文章。",
        "category": "文章创作",
        "sort_order": 3,
        "scenario": (
            "参考文章风格、模仿风格、仿写、按照这篇文章写、学习行文方式、"
            "参考结构、保持这种语气、公众号链接改写"
        ),
        "instructions": _instructions(
            """
            你负责参考示例文章的宏观写法创作新文章。只学习标题方式、开篇节奏、段落长度、
            论证结构、语言密度和情绪强度；新文章的事实与观点必须来自用户的新主题、新资料和
            明确要求。不得复制参考文章的标题、标志性句子、连续句式、人物、公司、数字、案例、
            广告或推广信息。参考文章中的作者、编辑、来源、公众号名称、机构和版权说明只是来源
            元数据，绝不能进入新文章正文，也不能冒充原作者。用户未明确要求引用内容时，参考
            文章只提供风格，不提供事实。最终文章必须脱离参考文章仍可独立成立。
            """
        ),
    },
    {
        "code": "case_study_article",
        "name": "案例拆解复盘",
        "description": "把企业、品牌、产品、营销或管理案例写成有机制分析的复盘文章。",
        "category": "文章创作",
        "sort_order": 4,
        "scenario": (
            "案例拆解、企业案例、品牌案例、营销案例、项目复盘、失败复盘、"
            "成功经验、商业案例、管理案例"
        ),
        "instructions": _instructions(
            """
            你负责把企业经营、产品、品牌、营销或管理案例写成完整的案例拆解文章。按案例背景、
            关键矛盾、采取行动、作用机制、可确认结果、边界条件和读者启示组织内容。不能因为
            最终成功就把所有历史决策解释为正确，也不能把时间先后直接写成因果关系。资料没有
            结果数据时，不得虚构营收、增长率、市场份额或内部讲话；事实不足的判断应使用准确的
            限定表达。对失败案例不做人身或道德攻击，对成功企业不写成宣传稿。资料署名、页眉页脚
            和来源信息不得进入正文，除非用户本轮明确要求引用。
            """
        ),
    },
    {
        "code": "hot_topic_commentary",
        "name": "热点事件评论",
        "description": "根据新闻、链接或用户资料生成事实清楚、立场明确的热点解读文章。",
        "category": "文章创作",
        "sort_order": 5,
        "scenario": (
            "热点评论、新闻评论、事件解读、时事分析、最近发生、最新消息、"
            "舆情文章、热点文章、行业新闻"
        ),
        "instructions": _instructions(
            """
            你负责根据本轮提供或已提取的新闻材料创作热点评论文章。先说明事件中最值得关注的
            变化，再交代已确认事实，分析背后的行业、商业或社会逻辑，说明对相关群体的影响，
            最后给出有依据的判断和后续观察点。只有本轮资料、已提取网页正文或系统确认的信息
            才能作为新闻事实；不得把传闻写成事实，不得杜撰“网友表示”“业内人士认为”等引用，
            也不得把旧材料描述成最新消息。来源冲突时如实说明。来源媒体、原公众号作者、编辑、
            广告和推广信息不得进入新文章正文，除非用户明确要求标注出处。
            """
        ),
    },
    {
        "code": "practical_guide_article",
        "name": "干货教程文章",
        "description": "生成步骤清楚、能够执行的教程、方法、指南和问题解决型文章。",
        "category": "文章创作",
        "sort_order": 6,
        "scenario": (
            "教程文章、操作指南、方法步骤、实用干货、从零开始、怎么做、避坑指南、检查清单、工作流程"
        ),
        "instructions": _instructions(
            """
            你负责创作可以实际执行的教程、方法和操作指南。先说明要解决的问题、适用对象、
            预期结果和必要前提，再按真实执行顺序展开步骤；每个关键步骤说明做什么、为什么、
            如何判断完成以及常见错误。教程允许使用必要的编号列表和检查清单，但不能只写
            “加强重视”“做好规划”等空泛要求。不得声称未经验证的方法已经验证有效；涉及平台
            界面、政策或软件版本时，只使用用户资料或已确认信息，不虚构工具、按钮、结果或
            成功率。正文不得包含作者、来源、技能说明或生成过程。
            """
        ),
    },
)

OUTPUT_SCHEMA = {
    "type": "object",
    "required": ["assistant_message", "article"],
    "properties": {
        "assistant_message": {"type": "string"},
        "article": {"type": "object"},
    },
    "additionalProperties": False,
}
TOOL_POLICY = {"wechat_publish": False}


def version_payload(definition: dict[str, Any]) -> dict[str, Any]:
    return {
        "instructions": definition["instructions"],
        "input_schema": {"type": "object", "scenario": definition["scenario"]},
        "output_schema": OUTPUT_SCHEMA,
        "tool_policy": TOOL_POLICY,
    }


async def seed_official_article_skills(database: Database) -> list[str]:
    created: list[str] = []
    async with database.session_maker() as session:
        for definition in OFFICIAL_ARTICLE_SKILLS:
            existing = await session.scalar(
                select(Skill).where(
                    Skill.scope == "official",
                    Skill.code == definition["code"],
                    Skill.deleted_at.is_(None),
                )
            )
            if existing:
                continue
            skill = Skill(
                scope="official",
                owner_id=None,
                code=definition["code"],
                name=definition["name"],
                description=definition["description"],
                category=definition["category"],
                status="published",
                sort_order=definition["sort_order"],
                current_version_no=1,
            )
            session.add(skill)
            await session.flush()
            payload = version_payload(definition)
            checksum = hashlib.sha256(
                json.dumps(payload, sort_keys=True, ensure_ascii=False).encode()
            ).hexdigest()
            version = SkillVersion(
                skill_id=skill.id,
                version_no=1,
                status="published",
                checksum=checksum,
                **payload,
            )
            session.add(version)
            await session.flush()
            audit(
                session,
                actor_type="system",
                actor_id="official-article-skills",
                action="official_skill.bootstrap",
                target_type="skill_version",
                target_id=version.id,
                request_id="seed-official-article-skills",
                reason="Install the bundled official article-creation skills.",
                details={"skill_id": skill.id, "code": skill.code, "version_no": 1},
            )
            created.append(skill.code)
        await session.commit()
    return created


async def run() -> None:
    database = Database(Settings.from_env())
    try:
        created = await seed_official_article_skills(database)
        print("Created: " + (", ".join(created) if created else "none; already installed"))
    finally:
        await database.dispose()


if __name__ == "__main__":
    asyncio.run(run())
