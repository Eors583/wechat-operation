"""Learn from attributable user feedback, never from generated or reference prose."""

from __future__ import annotations

import json
import re
from decimal import Decimal
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domains.dialogue_flow import style_action
from app.models import AuditLog, Message, Task, User, UserPreference, utcnow

RULES = {
    "tone": (r"严肃.{0,3}专业|专业.{0,3}严肃", "文章采用严肃、专业的表达风格"),
    "direct_opening": (
        r"开头.{0,12}(?:不要铺垫|别铺垫|直接|开门见山)",
        "文章开头直接进入主题，不要长篇铺垫",
    ),
    "direct_title": (r"标题.{0,12}(?:直接|明确|不要悬念)", "标题偏好直接给出判断，避免夸张悬念"),
    "concise_expression": (r"(?:表达|语言|行文).{0,8}(?:简洁|精简|简短|直接)", "表达偏好简洁直接"),
    "concrete_examples": (
        r"(?:多用|增加|补充).{0,8}(?:案例|例子)|(?:案例|例子).{0,8}(?:多一些|具体)",
        "正文偏好多用具体案例",
    ),
    "avoid_jargon": (
        r"(?:不要|避免|少用).{0,8}(?:术语|黑话|套话)",
        "避免使用复杂术语、行业黑话和套话",
    ),
}
TYPES = set(RULES) | {"tone", "article_length", "structure", "audience", "formatting"}
LONG_TERM = re.compile(r"以后|今后|后续都|一直|默认|每次|我(?:一直)?(?:喜欢|偏好|习惯)")
LOCAL = re.compile(r"这篇|本篇|这次|本次|仅此|只在|暂时|今天")
UNSAFE = re.compile(
    r"不要记|别记|不记录|忘掉|撤销|忽略.{0,8}(?:规则|指令)|系统提示|API.?Key|密码|密钥", re.I
)
MEMORY_INSTRUCTIONS = (
    '返回 JSON 对象 {"summary":"任务事实、未完成事项和文章状态摘要"}。'
    "不要提取或保存用户偏好。"
)


def is_preference_only(text: str) -> bool:
    """Future defaults are not permission to modify the current article."""
    if style_action(text):
        return False
    clauses = re.split(r"[，,。；;！!\n]|同时|然后|并且|(?=并(?:帮我|写|生成|修改))", text.strip())
    preference = False
    action = False
    for clause in clauses:
        if not clause.strip():
            continue
        future = bool(LONG_TERM.search(clause))
        recording = bool(
            re.search(
                r"(?:记录|记住|保存|记下|设为).{0,12}(?:偏好|习惯|风格)|只.{0,4}(?:记录|记住)",
                clause,
            )
        )
        if recording or (
            future
            and re.search(r"文章|写作|风格|语气|开头|标题|语言|表达|案例|术语|正文|排版", clause)
        ):
            preference = True
        current = bool(re.search(r"现在|立即|这篇|本篇|当前|本次|这次", clause))
        if (future or recording) and not current:
            continue
        clause = re.sub(
            r"(?:不要|别|不用|无需|不必|先不|暂不).{0,4}(?:生成|写|修改|改写|重写|创作)(?:文章|正文)?",
            "",
            clause,
        )
        if re.search(
            r"(?:写|生成|创作|改写|重写|修改|润色|扩写|缩写|调整|优化|应用|改成|改为|也按|也用)",
            clause,
        ):
            action = True
    return preference and not action


def feedback_sentences(text: str) -> list[str]:
    if len(text) > 4000 or UNSAFE.search(text):
        return []
    # Conservative exclusion: pasted/quoted examples are not statements of personal preference.
    text = re.sub(r"```[\s\S]*?```|“[^”]*”|\"[^\"]*\"|‘[^’]*’", "", text)
    return [
        part.strip()
        for part in re.split(r"[。！？!?\n；;]", text)
        if part.strip()
        and not part.lstrip().startswith(">")
        and not re.search(r"https?://|原文|示例|引用|例如|假设|如果|是否|他说|她说|作者说", part)
    ]


def extract_feedback(text: str, proposed: object = None) -> list[dict[str, str]]:
    sentences = feedback_sentences(text)
    found: dict[str, dict[str, str]] = {}
    for sentence in sentences:
        if LOCAL.search(sentence):
            continue
        for kind, (pattern, value) in RULES.items():
            if re.search(
                r"(?:不要|不喜欢|避免|别)(?:太|过于)?(?:直接|简洁|精简|增加|补充|多用|严肃|专业)",
                sentence,
            ):
                continue
            if re.search(pattern, sentence):
                found[kind] = {"type": kind, "value": value, "evidence": sentence}
    if isinstance(proposed, list):
        for item in proposed[:5]:
            if not isinstance(item, dict):
                continue
            proposed_kind = item.get("type")
            proposed_value = item.get("value")
            evidence = item.get("evidence")
            if (
                not isinstance(proposed_kind, str)
                or not isinstance(proposed_value, str)
                or not isinstance(evidence, str)
            ):
                continue
            kind, value = proposed_kind, proposed_value
            if (
                kind not in TYPES
                or not 4 <= len(value) <= 200
                or UNSAFE.search(value)
                or evidence not in sentences
                or LOCAL.search(evidence)
            ):
                continue
            found.setdefault(kind, {"type": kind, "value": value, "evidence": evidence})
    return list(found.values())


def parse_memory(text: str) -> tuple[str, object]:
    try:
        raw = text.strip()
        if raw.startswith("```"):
            raw = re.sub(r"^```(?:json)?\s*|\s*```$", "", raw)
        payload = json.loads(raw)
    except (ValueError, TypeError):
        return text[:4000], []
    if not isinstance(payload, dict) or not isinstance(payload.get("summary"), str):
        return text[:4000], []
    return payload["summary"][:4000], payload.get("preferences", [])


async def learn_preferences(
    session: AsyncSession,
    *,
    owner_id: str,
    message_id: str,
    proposed: Any = None,
) -> list[str]:
    row = (
        await session.execute(
            select(Message, Task)
            .join(Task, Task.id == Message.task_id)
            .where(
                Message.id == message_id,
                Message.role == "user",
                Task.owner_id == owner_id,
                Task.deleted_at.is_(None),
            )
        )
    ).first()
    if not row:
        return []
    message, task = row
    if not task.use_preferences:
        return []
    candidates = extract_feedback(message.plain_text, proposed)
    if not candidates:
        return []
    # Serialize this owner's learning; retries share the same message/evidence audit record.
    await session.scalar(select(User).where(User.id == owner_id).with_for_update())
    changed = []
    for candidate in candidates:
        kind, value, evidence = (candidate[k] for k in ("type", "value", "evidence"))
        scope = "project" if task.project_id else "personal"
        preferences = list(
            (
                await session.scalars(
                    select(UserPreference)
                    .where(
                        UserPreference.user_id == owner_id,
                        UserPreference.scope == scope,
                        UserPreference.project_id == task.project_id,
                        UserPreference.preference_type == kind,
                    )
                    .with_for_update()
                )
            ).all()
        )
        existing = next((p for p in preferences if p.value == value), None)
        # Revocation is authoritative, even if the same request is replayed later.
        if existing and existing.status == "revoked":
            continue
        explicit = bool(LONG_TERM.search(evidence))
        if not existing:
            existing = UserPreference(
                user_id=owner_id,
                project_id=task.project_id,
                preference_type=kind,
                value=value,
                scope=scope,
                confidence=Decimal("0.55"),
                source_type="dialogue_feedback",
                source_id=message.id,
                status="candidate",
            )
            session.add(existing)
            await session.flush()
        logs = list(
            (
                await session.scalars(
                    select(AuditLog).where(
                        AuditLog.actor_id == owner_id,
                        AuditLog.action == "preference.feedback",
                        AuditLog.target_id == existing.id,
                    )
                )
            ).all()
        )
        if any(log.details.get("message_id") == message.id for log in logs):
            continue
        tasks = {log.details.get("task_id") for log in logs} | {task.id}
        # Two independent tasks, not two retries or repeated requests in the same article.
        confirmed = explicit or len(tasks) >= 2
        conflicts = [p for p in preferences if p.id != existing.id and p.status == "confirmed"]
        if confirmed and (explicit or not conflicts):
            existing.status = "confirmed"
            existing.confidence = Decimal("0.90") if explicit else Decimal("0.80")
            if explicit:
                for old in conflicts:
                    old.status = "revoked"
                    old.revoked_at = utcnow()
        existing.source_id = message.id
        session.add(
            AuditLog(
                actor_type="user",
                actor_id=owner_id,
                action="preference.feedback",
                target_type="user_preference",
                target_id=existing.id,
                details={"message_id": message.id, "task_id": task.id, "status": existing.status},
            )
        )
        changed.append(existing.id)
        await session.flush()
    return changed
