from __future__ import annotations

from collections.abc import Iterator


def iter_text_chunks(
    text: str, *, target_characters: int, overlap_characters: int
) -> Iterator[str]:
    """Yield bounded overlapping chunks while preserving caller-defined structural boundaries."""
    normalized = text.strip()
    if not normalized:
        return
    if target_characters <= 0 or overlap_characters < 0 or overlap_characters >= target_characters:
        raise ValueError("Invalid text chunking configuration")
    step = target_characters - overlap_characters
    for offset in range(0, len(normalized), step):
        chunk = normalized[offset : offset + target_characters]
        if not chunk:
            return
        yield chunk
        if offset + target_characters >= len(normalized):
            return
