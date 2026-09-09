"""seed official WeChat operation skills

Revision ID: b6c8e91a24f3
Revises: 7f7b7d0c41a2
Create Date: 2026-09-08
"""

import hashlib
import json
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "b6c8e91a24f3"
down_revision: str | None = "7f7b7d0c41a2"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_SKILLS = (
    {
        "id": "b6c8e91a-24f3-4100-9000-000000000001",
        "version_id": "b6c8e91a-24f3-4100-a000-000000000001",
        "code": "viral-article-rewrite",
        "name": "爆款文章改写",
        "description": "保留原文事实与核心观点，重构为表达原创、节奏鲜明的公众号成稿。",
        "category": "内容创作",
        "sort_order": 10,
        "scenario": "已有文章、采访稿或参考资料，需要改写成新的公众号文章。",
        "examples": (
            "把这篇文章改写成面向职场人的公众号文章\n\n"
            "保留核心事实，换一个更有吸引力的叙事角度"
        ),
        "instructions": (
            "基于用户提供的原文或已提取资料完成公众号文章改写。先识别可验证事实、核心观点、"
            "目标读者和用户明确要求，再重新组织标题、开头、章节推进和结尾。保留事实边界与"
            "专有名词，不虚构数据、案例、出处或引语；资料不足时使用审慎表述。避免逐句同义替换，"
            "不得复制原文独特句式或大段表达。除非用户只要求局部修改，否则交付包含标题、完整正文"
            "和结尾的可发布成稿，不输出分析过程、改写说明或完成提示。"
        ),
    },
    {
        "id": "b6c8e91a-24f3-4100-9000-000000000002",
        "version_id": "b6c8e91a-24f3-4100-a000-000000000002",
        "code": "wechat-title-optimizer",
        "name": "公众号标题优化",
        "description": "根据正文卖点生成清晰、有点击动力且不过度夸张的标题方案。",
        "category": "标题运营",
        "sort_order": 20,
        "scenario": "文章已经有主题或正文，需要生成、筛选或优化公众号标题。",
        "examples": "根据这篇正文给我 10 个标题\n\n把这个标题改得更有点击动力，但不要标题党",
        "instructions": (
            "根据用户主题和正文中的真实信息生成公众号标题。默认提供 10 个差异明显的候选，覆盖"
            "利益点、问题切入、反差、数字信息和观点表达等角度，并推荐 3 个最合适的标题，分别说明"
            "适用读者和亮点。标题应具体、自然、便于移动端阅读，不捏造数字、身份、结论或紧迫性，"
            "不使用与正文不符的夸张承诺、恐吓表达和低俗噱头。用户指定数量或风格时优先遵从。"
        ),
    },
    {
        "id": "b6c8e91a-24f3-4100-9000-000000000003",
        "version_id": "b6c8e91a-24f3-4100-a000-000000000003",
        "code": "article-structure-editor",
        "name": "文章结构优化",
        "description": "梳理文章逻辑、章节层级与段落衔接，解决松散、重复和重点不清。",
        "category": "编辑优化",
        "sort_order": 30,
        "scenario": "已有草稿内容基本完整，但结构松散、重复或阅读节奏不顺。",
        "examples": "帮我优化这篇文章的结构和段落顺序\n\n正文不要大改，只调整逻辑和小标题",
        "instructions": (
            "编辑用户提供的完整草稿，识别中心论点、读者问题和各段功能，调整章节顺序、小标题、"
            "段落拆分与过渡，使开头提出明确阅读价值，中段逐层推进，结尾完成观点收束。删除重复"
            "信息和无效铺垫，但不得改变事实含义、补造材料或扩大结论。用户要求直接修改时输出优化后"
            "的完整文章；用户只要求建议时，先列出关键结构问题，再给出可执行的新结构。"
        ),
    },
    {
        "id": "b6c8e91a-24f3-4100-9000-000000000004",
        "version_id": "b6c8e91a-24f3-4100-a000-000000000004",
        "code": "brand-tone-polish",
        "name": "公众号口吻润色",
        "description": "在不改变事实的前提下，统一语气、增强可读性并减少机械表达。",
        "category": "编辑优化",
        "sort_order": 40,
        "scenario": "草稿事实和结构已经确定，需要调整语气、措辞和品牌表达。",
        "examples": "把这篇文章润色得更自然、更像真人写的\n\n调整成专业但不生硬的品牌口吻",
        "instructions": (
            "按照用户指定的品牌口吻润色现有文章；未指定时采用专业、自然、克制、易读的公众号"
            "表达。保持原有事实、数据、观点和章节意图，不擅自新增案例、引语或结论。减少模板化"
            "套话、空泛形容、连续短句和机械排比，改善句式变化、段落节奏与上下文衔接。保留用户"
            "明确要求的专业术语，必要时补充简短解释。默认输出润色后的完整正文，不附加修改说明。"
        ),
    },
    {
        "id": "b6c8e91a-24f3-4100-9000-000000000005",
        "version_id": "b6c8e91a-24f3-4100-a000-000000000005",
        "code": "long-article-compressor",
        "name": "长文精简",
        "description": "压缩冗余内容，保留关键事实、论证链条和对读者最有价值的信息。",
        "category": "编辑优化",
        "sort_order": 50,
        "scenario": "文章篇幅过长，需要按目标字数精简，同时避免遗漏重要信息。",
        "examples": "把这篇文章压缩到 1500 字左右\n\n删掉重复和空话，核心数据都要保留",
        "instructions": (
            "按照用户指定字数或压缩比例精简文章；未指定时压缩到原文约六成。优先删除重复观点、"
            "冗长背景、空泛修饰、无推进作用的例子和可合并段落，保留核心事实、关键数据、必要限定"
            "条件、因果关系和结论依据。不得为了缩短而改变原意、删除风险提示或制造更强结论。输出"
            "结构完整、衔接自然的精简稿；如果目标字数不足以保留必要信息，应明确指出冲突。"
        ),
    },
    {
        "id": "b6c8e91a-24f3-4100-9000-000000000006",
        "version_id": "b6c8e91a-24f3-4100-a000-000000000006",
        "code": "prepublish-content-review",
        "name": "发布前内容审校",
        "description": "检查事实边界、前后矛盾、错别字、敏感表达和标题正文一致性。",
        "category": "内容审校",
        "sort_order": 60,
        "scenario": "文章准备发布，需要进行最后一轮内容质量与风险检查。",
        "examples": "检查这篇文章能不能直接发布\n\n帮我找出错别字、事实风险和标题正文不一致",
        "instructions": (
            "对待发布文章进行审校，依次检查标题与正文一致性、事实和数据是否有来源支撑、时间与"
            "人物关系、前后矛盾、逻辑跳跃、错别字和标点、可能误导的绝对化表达、隐私和敏感信息。"
            "无法验证的内容必须标记为待核实，不得自行补造来源。按严重、建议、可选三级列出问题，"
            "给出原句定位、风险原因和最小修改建议。除非用户明确要求直接修改，否则只输出审校报告，"
            "不重写整篇文章，也不执行发布。"
        ),
    },
)


def upgrade() -> None:
    skills = sa.table(
        "skills",
        sa.column("id", sa.String),
        sa.column("scope", sa.String),
        sa.column("owner_id", sa.String),
        sa.column("code", sa.String),
        sa.column("name", sa.String),
        sa.column("description", sa.Text),
        sa.column("category", sa.String),
        sa.column("status", sa.String),
        sa.column("sort_order", sa.Integer),
        sa.column("current_version_no", sa.Integer),
    )
    versions = sa.table(
        "skill_versions",
        sa.column("id", sa.String),
        sa.column("skill_id", sa.String),
        sa.column("version_no", sa.Integer),
        sa.column("instructions", sa.Text),
        sa.column("input_schema", sa.JSON),
        sa.column("output_schema", sa.JSON),
        sa.column("tool_policy", sa.JSON),
        sa.column("status", sa.String),
        sa.column("checksum", sa.String),
    )
    op.bulk_insert(
        skills,
        [
            {
                "id": item["id"],
                "scope": "official",
                "owner_id": None,
                "code": item["code"],
                "name": item["name"],
                "description": item["description"],
                "category": item["category"],
                "status": "published",
                "sort_order": item["sort_order"],
                "current_version_no": 1,
            }
            for item in _SKILLS
        ],
    )
    version_rows = []
    for item in _SKILLS:
        payload = {
            "instructions": item["instructions"],
            "input_schema": {
                "scenario": item["scenario"],
                "exampleArticle": item["examples"],
            },
            "output_schema": {},
            "tool_policy": {},
        }
        version_rows.append(
            {
                "id": item["version_id"],
                "skill_id": item["id"],
                "version_no": 1,
                **payload,
                "status": "published",
                "checksum": hashlib.sha256(
                    json.dumps(payload, sort_keys=True, ensure_ascii=False).encode()
                ).hexdigest(),
            }
        )
    op.bulk_insert(versions, version_rows)


def downgrade() -> None:
    connection = op.get_bind()
    version_ids = [item["version_id"] for item in _SKILLS]
    skill_ids = [item["id"] for item in _SKILLS]
    connection.execute(
        sa.text("DELETE FROM skill_versions WHERE id IN :ids").bindparams(
            sa.bindparam("ids", expanding=True)
        ),
        {"ids": version_ids},
    )
    connection.execute(
        sa.text("DELETE FROM skills WHERE id IN :ids").bindparams(
            sa.bindparam("ids", expanding=True)
        ),
        {"ids": skill_ids},
    )
