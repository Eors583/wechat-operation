from __future__ import annotations

from app.providers import ModelProvider, ProviderUnavailable


class ModelContentSafetyProvider:
    def __init__(self, model: ModelProvider) -> None:
        self._model = model

    async def check_text(self, text: str) -> tuple[bool, str | None]:
        result = await self._model.generate(
            purpose="content_check",
            prompt=(
                "判断以下文本是否包含违法、暴力伤害、仇恨、色情、诈骗或明显危险内容。"
                "只输出 SAFE，或输出 UNSAFE:后接简短原因。\n\n待检查文本：\n"
                + text
            ),
            context={},
        )
        verdict = result.text.strip()
        if verdict == "SAFE":
            return True, None
        if verdict.startswith("UNSAFE:"):
            return False, verdict.partition(":")[2].strip() or "unsafe"
        raise ProviderUnavailable("内容安全模型返回了无法识别的结果。")
