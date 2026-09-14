from __future__ import annotations

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field

from app.style_token_contracts import StyleProperties

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


class LayoutCreditField(BaseModel):
    model_config = ConfigDict(extra="forbid")
    label: str = Field(max_length=40)
    value: str = Field(default="", max_length=120)


class LayoutComponentGroup(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str = Field(pattern=r"^group-[1-9][0-9]{0,3}$")
    kind: Literal["lead_card", "credits", "decorated_heading", "body", "fixed"]
    block_ids: list[ContentBlockId] = Field(min_length=1, max_length=100)
    confirmed: bool = False
    enabled: bool = False
    confidence: float = Field(default=0, ge=0, le=1)
    container_style: StyleProperties = Field(default_factory=StyleProperties)
    text_style: StyleProperties = Field(default_factory=StyleProperties)
    label_style: StyleProperties = Field(default_factory=StyleProperties)
    fields: list[LayoutCreditField] = Field(default_factory=list, max_length=12)
    image_width: int = Field(default=120, ge=24, le=680)
    sequence: int | None = Field(default=None, ge=1, le=100)


class LayoutSourceSnapshot(BaseModel):
    # Keep existing extraction observations and provider metadata across template versions.
    model_config = ConfigDict(extra="allow")

    content_blocks: list[LayoutContentBlock] = Field(default_factory=list, max_length=10_000)
    locked_blocks: list[LayoutLockedBlock] = Field(default_factory=list, max_length=100)
    component_groups: list[LayoutComponentGroup] = Field(default_factory=list, max_length=100)
