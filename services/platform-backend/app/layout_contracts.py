from __future__ import annotations

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field

ContentBlockId = Annotated[str, Field(pattern=r"^content-[1-9][0-9]{0,5}$")]


class LayoutContentBlock(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: ContentBlockId
    html: str = Field(max_length=5_000_000)
    text: str = Field(max_length=5_000_000)
    module: Literal[
        "title", "lead", "heading_marker", "heading1", "heading2", "body", "highlight",
        "quote", "list", "caption", "divider", "table_header", "table_cell",
    ] = "body"


class LayoutLockedBlock(BaseModel):
    model_config = ConfigDict(extra="forbid")

    block_ids: list[ContentBlockId] = Field(min_length=1, max_length=10_000)
    position: Literal["before_body", "after_body", "after_paragraph"] = "before_body"
    paragraph_index: int = Field(default=1, ge=1, le=10_000, strict=True)


class LayoutSourceSnapshot(BaseModel):
    # Keep existing extraction observations and provider metadata across template versions.
    model_config = ConfigDict(extra="allow")

    content_blocks: list[LayoutContentBlock] = Field(default_factory=list, max_length=10_000)
    locked_blocks: list[LayoutLockedBlock] = Field(default_factory=list, max_length=100)
