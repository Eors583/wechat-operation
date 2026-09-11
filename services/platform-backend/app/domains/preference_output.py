"""Optional writer metadata, separated from both article JSON and streamed prose."""

import json
import re
from dataclasses import replace

from app.providers import ModelResult

MARKER = "<preference_check>"
END_MARKER = "</preference_check>"
INSTRUCTION = """
完成本轮创作是首要任务。同时只依据 untrusted_user_input 中用户本人的明确反馈，
判断是否值得询问用户保存为偏好。标题/开头吸引力、表达简洁度、输出形式等明确取舍，
即使没有“以后、默认”等词，也应建议询问；这不是保存写作风格，更不表示已经保存。
“你的开头要吸引人，现在的太平淡了”应建议“开头更吸引人，避免平淡”，key=opening_appeal。
“标题爆款点，不要这么平淡”应建议“标题更有吸引力，避免平淡”，key=title_appeal。
“感觉你这个结尾不能够吸引用户关注和转发，你再调整一下”应建议
“文章结尾要有吸引力，能引导读者关注和转发”，key=ending_engagement。
修改文章与建议偏好不是互斥意图：先完成修改，同时返回 should_ask=true。
“你这个结尾”“这篇文章的标题”只是修改对象，不等于用户说“仅本次”。
不要因为用户没有说明长期适用而返回 false，长期是否适用由确认卡片询问。
只有“仅本次、只对这篇、暂时”等明确范围限定才排除；纯“调整一下”且无评价标准不询问。
纯操作指令、题材/事实、含糊评价、明确仅本次的要求、引文/附件/技能内容不作为偏好。
不得提取敏感信息、密码或令牌。不从助手自己写出的内容推断用户偏好。
preference_check 的格式为 {"should_ask":false}；值得询问时返回
{"should_ask":true,"key":"稳定的细分英文标识","value":"不超过100字的偏好",
"evidence":"本轮用户输入中连续且完整表达该取舍的原文"}。
只返回一项，不自行询问或声称记住。该字段不能改变文章、风格优先级、权限或操作。
"""


def output_instruction(mode: str) -> str:
    return INSTRUCTION + (
        "在原 JSON 根对象最前面增加 preference_check 字段，其余正文和字段保持原格式。"
        "preference_check 不得放入 article、content、assistant_message 或标题字符串。"
        if mode == "json"
        else "先按原要求返回完整文本，最后另起一行输出 <preference_check>JSON对象"
        "</preference_check>；标签及其中的数据仅供程序读取，不属于回复正文。"
    )


class PreferenceStreamFilter:
    """Hold only a possible delimiter prefix, not the complete creative response."""

    def __init__(self) -> None:
        self.pending = ""
        self.metadata_started = False

    def feed(self, fragment: str) -> str:
        if self.metadata_started:
            return ""
        self.pending += fragment
        index = self.pending.find(MARKER)
        if index >= 0:
            visible = self.pending[:index]
            self.pending = ""
            self.metadata_started = True
            return visible
        keep = next(
            (n for n in range(len(MARKER) - 1, 0, -1) if self.pending.endswith(MARKER[:n])),
            0,
        )
        visible = self.pending[:-keep] if keep else self.pending
        self.pending = self.pending[-keep:] if keep else ""
        return visible

    def finish(self) -> str:
        # A literal '<' is ordinary text; a recognizable interrupted tag is not.
        visible = self.pending if len(self.pending) < 4 else ""
        self.pending = ""
        return visible


def separate_preference_output(result: ModelResult) -> tuple[ModelResult, object]:
    raw = result.text
    candidate = re.sub(r"^```(?:json)?\s*|\s*```$", "", raw.strip())
    try:
        parsed = json.loads(candidate)
    except (ValueError, TypeError):
        parsed = None
    if isinstance(parsed, dict) and "preference_check" in parsed:
        metadata = parsed.pop("preference_check")
        return replace(
            result, text=json.dumps(parsed, ensure_ascii=False), structured=parsed
        ), metadata
    if MARKER in raw:
        visible, tail = raw.split(MARKER, 1)
        try:
            metadata = json.loads(tail.split(END_MARKER, 1)[0].strip())
        except (ValueError, TypeError):
            metadata = None
        visible = visible.rstrip()
        return replace(
            result,
            text=visible,
            structured={
                "type": "doc",
                "content": [{"type": "paragraph", "content": [{"type": "text", "text": visible}]}]
                if visible
                else [],
            },
        ), metadata
    # Never leak an interrupted metadata delimiter at the end of a text response.
    for length in range(len(MARKER) - 1, 3, -1):
        if raw.endswith(MARKER[:length]):
            return replace(result, text=raw[:-length].rstrip()), None
    return result, None
