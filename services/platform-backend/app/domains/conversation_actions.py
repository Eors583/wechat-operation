"""Explicit, owner-scoped dialogue operations backed by the preferences API's service."""

import re
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domains.personal_skills import create_personal_skill
from app.errors import ApiError
from app.models import AuditLog, Message, Skill, Task, UserPreference, utcnow


def needs_model(action: dict[str, Any]) -> bool:
    return action["operation"] in {"describe", "update"} or (
        action["operation"] in {"save", "save_skill"} and not action.get("value")
    )


async def create_preference(
    session: AsyncSession, owner_id: str, values: dict[str, Any]
) -> UserPreference:
    row = UserPreference(user_id=owner_id, source_type="explicit", status="confirmed", **values)
    session.add(row)
    await session.flush()
    session.add(
        AuditLog(
            actor_type="user",
            actor_id=owner_id,
            action="preference.create",
            target_type="user_preference",
            target_id=row.id,
            details={"source_message_id": row.source_id},
        )
    )
    return row


async def owned_preference(
    session: AsyncSession, owner_id: str, preference_id: str
) -> UserPreference:
    row = await session.scalar(
        select(UserPreference)
        .where(UserPreference.user_id == owner_id, UserPreference.id == preference_id)
        .with_for_update()
    )
    if row is None:
        raise ApiError(404, "PREFERENCE_NOT_FOUND", "写作偏好不存在。")
    return row


def update_preference(session: AsyncSession, row: UserPreference, changes: dict[str, Any]) -> None:
    for key in ("value", "status"):
        if key in changes:
            value = changes[key]
            if key == "value" and (
                not isinstance(value, str) or not 1 <= len(value.strip()) <= 2000
            ):
                raise ApiError(422, "WRITING_STYLE_INVALID", "写作风格必须为 1—2000 个字符。")
            if key == "status" and value not in {"candidate", "confirmed", "revoked"}:
                raise ApiError(422, "PREFERENCE_STATUS_INVALID", "偏好状态无效。")
            setattr(row, key, value)
    row.revoked_at = utcnow() if row.status == "revoked" else None
    session.add(
        AuditLog(
            actor_type="user",
            actor_id=row.user_id,
            action="preference.update",
            target_type="user_preference",
            target_id=row.id,
            details={"fields": list(changes)},
        )
    )


def title(row: UserPreference) -> str:
    return row.value.splitlines()[0].lstrip("# ").strip()[:80]


async def plan_action(
    session: AsyncSession, task: Task, text: str, recent: list[Message]
) -> dict[str, Any] | None:
    """Only the current user message grants authority; previous metadata resolves references."""
    text = text.strip()
    command = re.sub(r"[《“\"][^》”\"]+[》”\"]", "", text)
    previous = next((m for m in recent if m.role == "assistant"), None)
    prior = previous.content_json.get("conversation_action", {}) if previous else {}
    if not isinstance(prior, dict):
        prior = {}
    style = bool(
        re.search(
            r"写作风格|写作偏好|行文风格|(?:总结|提炼|归纳|保存|查看|修改|删除).*风格", command
        )
    )
    followup = bool(prior) and bool(re.search(r"刚才|上面|这个|这条|它|保存下来|保存吧", text))
    destination = re.search(
        r"(?:保存|另存|存入|存到|添加|新增|转成|做成).{0,12}?(技能|写作风格|写作偏好|行文风格)",
        command,
    )
    explicit_destinations = list(
        re.finditer(
            r"(?:成|为|到|入)(?:我的|个人|自己的|一个|一项|一条|的|新|\s)*"
            r"(技能|写作风格|写作偏好|行文风格|模板|项目要求|草稿箱|文章库)",
            command,
        )
    )
    if explicit_destinations:
        destination = explicit_destinations[-1]
    if destination and destination[1] in {"模板", "项目要求", "草稿箱", "文章库"}:
        return {"operation": "help", "reply": "这个保存目标尚未接入对话，请使用对应页面保存。"}
    explicit_style = destination is not None and destination[1] != "技能"
    skill_target = (
        "技能" in command or (followup and prior.get("operation") == "save_skill")
    ) and not explicit_style
    if (
        not style
        and not followup
        and not skill_target
        and not re.search(r"偏好(?:学习|使用)|使用偏好", text)
    ):
        return None
    # Questions, quotations, negation and multiple commands never authorize a mutation.
    if re.search(
        r"(?:不要|不用|别|先不|暂不).{0,3}(?:保存|记录|记住|删除|移除|修改|更新|启用|应用|确认)",
        command,
    ):
        if re.search(r"保存|记录|记住", text) and re.search(r"总结|分析|提炼|归纳", text):
            return {"operation": "describe"}
        return {"operation": "help", "reply": "本轮没有更改写作风格。"}
    if re.search(r"能否|能不能|可以吗|如何|怎么|为什么|是否|假设|例如|比如|他说|她说", command):
        return {
            "operation": "help",
            "reply": (
                "可以在对话中查看、总结并保存、修改、删除或确认写作风格。"
                "例如：总结并保存我的写作风格；查看我的写作风格；删除写作风格《名称》。"
            ),
        }
    # The requested destination wins over the type of the previous answer.
    if skill_target:
        if not re.search(r"保存|另存|存入|存到|添加|新增|转成|做成", command):
            return {"operation": "help", "reply": "请明确技能操作，例如：把这个保存成我的技能。"}
        value = prior.get("value")
        if not isinstance(value, str) or not value.strip():
            value = (
                previous.plain_text
                if previous and previous.content_json.get("response_kind") != "ai_error"
                else None
            )
        if not value or re.search(r"(?:重新|再).{0,4}(?:总结|提炼|归纳)", command):
            return {
                "operation": "help",
                "reply": "请先给出要保存的技能内容，或先让我总结，再保存成技能。",
            }
        action = {"operation": "save_skill", "value": value}
        if prior.get("operation") == "save_skill" and prior.get("skill_id"):
            action["skill_id"] = prior["skill_id"]
        return action
    if re.search(r"(?:开启|打开|启用|关闭|关掉|停用).*(?:偏好学习|使用偏好|偏好使用)", text):
        return {"operation": "toggle", "enabled": not bool(re.search(r"关闭|关掉|停用", text))}
    candidates = []
    for name, pattern in (
        ("delete", r"删除|移除|撤销"),
        ("update", r"修改|更新|编辑|改为|改成|重命名"),
        ("confirm", r"确认|启用|应用|使用"),
        ("save", r"保存|记录|记住|存入|存到|添加|新增"),
        ("describe", r"总结|提炼|分析|归纳"),
        ("list", r"查看|列出|展示|有哪些|显示|看看"),
    ):
        match = re.search(pattern, command)
        if match:
            candidates.append((match.start(), name))
    operation = min(candidates)[1] if candidates else None
    if operation == "describe" and any(name == "save" for _, name in candidates):
        operation = "save"
    if operation is None:
        return None
    if operation in {"update", "confirm"} and re.search(
        r"(?:修改|改写|重写|润色|生成|写).{0,8}(?:当前文章|这篇文章|正文|推文)|应用.{0,12}文章",
        command,
    ):
        return None  # Article revision continues through its versioned workflow.
    if operation in {"delete", "update", "confirm"} and re.search(
        r"全部|所有|一并|同时|然后|并且|再(?:删除|修改|启用)", command
    ):
        return {
            "operation": "help",
            "reply": "请每次指定一个写作风格及一个操作，例如：删除写作风格《名称》。",
        }
    if operation in {"save", "describe"}:
        action: dict[str, Any] = {"operation": operation}
        if followup and prior.get("operation") in {"describe", "save", "save_skill"}:
            value = prior.get("value")
            if isinstance(value, str):
                action["value"] = value
                if prior.get("operation") == "save" and prior.get("preference_id"):
                    action["preference_id"] = prior["preference_id"]
        return action
    rows = list(
        (
            await session.scalars(
                select(UserPreference)
                .where(
                    UserPreference.user_id == task.owner_id,
                    UserPreference.status != "revoked",
                )
                .order_by(UserPreference.updated_at.desc(), UserPreference.id)
            )
        ).all()
    )
    if operation == "list":
        return {"operation": "list"}
    quoted = re.search(r"[《“\"]([^》”\"]+)[》”\"]", text)
    matches = (
        [row for row in rows if title(row) == quoted[1]]
        if quoted
        else [row for row in rows if len(title(row)) >= 2 and title(row) in text]
    )
    if not matches and followup and prior.get("preference_id"):
        matches = [row for row in rows if row.id == prior["preference_id"]]
    if len(matches) != 1:
        names = "、".join(f"《{title(row)}》" for row in rows[:20])
        return {
            "operation": "help",
            "reply": (
                f"请指定一个准确的写作风格名称。当前有：{names}。"
                if rows
                else "还没有保存写作风格。可以先说：总结并保存我的写作风格。"
            ),
        }
    row = matches[0]
    if operation == "confirm" and row.project_id and row.project_id != task.project_id:
        return {
            "operation": "help",
            "reply": "这个风格属于其他项目，请在对应项目中使用，或另存为个人风格。",
        }
    return {"operation": operation, "preference_id": row.id, "value": row.value}


async def execute_action(
    session: AsyncSession, task: Task, action: dict[str, Any], *, source_id: str, generated: str
) -> tuple[str, dict[str, Any]]:
    operation = action["operation"]
    metadata = {"operation": operation}
    if operation == "save_skill":
        value = str(action.get("value") or generated).strip()
        code = f"dialogue-{source_id}"
        existing = await session.scalar(
            select(Skill).where(
                Skill.owner_id == task.owner_id,
                Skill.scope == "personal",
                Skill.id == action["skill_id"] if action.get("skill_id") else Skill.code == code,
            )
        )
        if existing and existing.deleted_at:
            raise ApiError(409, "SKILL_CHANGED", "这个技能已被删除，请明确要重新创建的内容。")
        if existing is None:
            name = value.splitlines()[0].lstrip("# ").strip() if value else ""
            existing, _ = await create_personal_skill(
                session,
                owner_id=task.owner_id,
                name=name,
                instructions=value,
                scenario="用户明确保存的写作方法，用于后续内容创作。",
                code=code,
            )
        metadata.update({"skill_id": existing.id, "value": value})
        return f"已保存到我的技能：《{existing.name}》。", metadata
    if operation == "help":
        return action["reply"], metadata
    if operation == "list":
        rows = list(
            (
                await session.scalars(
                    select(UserPreference)
                    .where(
                        UserPreference.user_id == task.owner_id,
                        UserPreference.status != "revoked",
                    )
                    .order_by(UserPreference.updated_at.desc(), UserPreference.id)
                )
            ).all()
        )
        if not rows:
            return "还没有保存写作风格。可以说：总结并保存我的写作风格。", metadata
        return "我的写作风格：\n\n" + "\n\n".join(
            f"{row.value}\n\n状态：{'已生效' if row.status == 'confirmed' else '待确认'}；"
            f"范围：{'项目' if row.project_id else '个人'}"
            for row in rows
        ), metadata
    if operation == "toggle":
        task.use_preferences = action["enabled"]
        session.add(
            AuditLog(
                actor_type="user",
                actor_id=task.owner_id,
                action="task.preferences.toggle",
                target_type="task",
                target_id=task.id,
                details={"enabled": action["enabled"]},
            )
        )
        return (
            "已开启" if task.use_preferences else "已关闭"
        ) + "当前任务的偏好使用与学习。", metadata
    if operation in {"describe", "save", "update"}:
        value = (
            action.get("value")
            if operation == "save" and action.get("value")
            else generated.strip()
        )
        if (
            not isinstance(value, str)
            or not re.fullmatch(r"# [^\r\n]{1,80}\r?\n\s*\n[\s\S]+", value)
            or len(value) > 2000
        ):
            raise ApiError(422, "WRITING_STYLE_INVALID", "风格总结格式不完整或过长，未保存。")
        metadata["value"] = value
        if operation == "describe":
            return value + "\n\n尚未保存；可以说“把刚才的保存下来”。", metadata
        if operation == "save":
            if action.get("preference_id"):
                existing = await owned_preference(session, task.owner_id, action["preference_id"])
                if existing.status != "revoked" and existing.value == value:
                    metadata["preference_id"] = existing.id
                    return "这份风格已经保存在设置 → 我的写作风格中，没有重复添加。", metadata
                raise ApiError(409, "PREFERENCE_CHANGED", "刚才的风格已变化，请重新指定保存内容。")
            row = await session.scalar(
                select(UserPreference).where(
                    UserPreference.user_id == task.owner_id,
                    UserPreference.source_id == source_id,
                    UserPreference.preference_type == "writing_style",
                )
            )
            if row is None:
                row = await create_preference(
                    session,
                    task.owner_id,
                    {
                        "project_id": None,
                        "preference_type": "writing_style",
                        "value": value,
                        "scope": "personal",
                        "confidence": 1,
                        "source_id": source_id,
                    },
                )
            metadata["preference_id"] = row.id
            return value + "\n\n已保存到设置 → 我的写作风格。" + (
                "当前任务的偏好使用已关闭，保存不会自动开启它。" if not task.use_preferences else ""
            ), metadata
    row = await owned_preference(session, task.owner_id, action["preference_id"])
    if row.status == "revoked" or row.value != action["value"]:
        raise ApiError(409, "PREFERENCE_CHANGED", "该风格已经变化，请重新指定要操作的风格。")
    if operation == "update":
        update_preference(session, row, {"value": generated.strip()})
        reply = f"已更新写作风格《{title(row)}》，可在设置中查看。\n\n{row.value}"
    elif operation == "delete":
        update_preference(session, row, {"status": "revoked"})
        reply = f"已删除写作风格《{title(row)}》。"
    else:
        update_preference(session, row, {"status": "confirmed"})
        task.use_preferences = True
        reply = (
            f"已确认写作风格《{title(row)}》并开启当前任务的偏好使用，"
            "后续创作会参考它；当前文章未改动。"
        )
    metadata["preference_id"] = row.id
    return reply, metadata
