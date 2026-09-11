"""Parse task summaries and identify attributable feedback without persisting preferences."""

from __future__ import annotations

import json
import re

from app.domains.dialogue_flow import style_action

LONG_TERM = re.compile(r"以后|今后|后续都|一直|默认|每次|我(?:一直)?(?:喜欢|偏好|习惯)")
UNSAFE = re.compile(
    r"不要记|别记|不记录|忘掉|撤销|忽略.{0,8}(?:规则|指令)|系统提示|API.?Key|密码|密钥", re.I
)
MEMORY_INSTRUCTIONS = (
    '返回 JSON 对象 {"summary":"任务事实、未完成事项和文章状态摘要"}。不要提取或保存用户偏好。'
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
