"""Shared output limits and tokenizer-independent input estimates."""


def estimate_tokens(text: str) -> int:
    """Approximate mixed Chinese/Latin text; callers must reserve a safety margin."""
    chinese = sum(1 for character in text if "\u2e80" <= character <= "\u9fff")
    other = max(0, len(text) - chinese)
    return chinese + (other + 3) // 4


def output_token_limit(
    purpose: str, configured: int = 0, *, private_user_preferences: bool = False
) -> int | None:
    default = {
        "intent_detection": 128,
        "article_planning": 3072,
        "article_generation": 16384,
        "article_revision": 16384,
        "fast_task": 4096,
        "content_check": 256,
        "memory_summary": 4096 if private_user_preferences else 512,
        "vision": 2048,
        "layout_extraction": 4096,
    }.get(purpose)
    if configured > 0:
        return min(configured, default) if default is not None else configured
    return default
