from __future__ import annotations

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field


class StyleContractModel(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class StyleProperties(StyleContractModel):
    border_all: str | None = Field(
        default=None,
        pattern=r"^(?:none|(?:[0-9]|1[0-2])px (?:solid|dashed|dotted) #[0-9A-Fa-f]{6})$",
    )
    enabled: bool | None = None
    font_size: float | None = Field(default=None, ge=0, le=72)
    font_weight: Literal[400, 500, 600, 700] | None = None
    color: str | None = Field(
        default=None,
        pattern=r"^#(?:[0-9A-Fa-f]{3}|[0-9A-Fa-f]{4}|[0-9A-Fa-f]{6}|[0-9A-Fa-f]{8})$",
    )
    background: str | None = Field(
        default=None,
        pattern=r"^#(?:[0-9A-Fa-f]{3}|[0-9A-Fa-f]{4}|[0-9A-Fa-f]{6}|[0-9A-Fa-f]{8})$",
    )
    align: Literal["left", "center", "right", "justify"] | None = None
    line_height: float | None = Field(default=None, ge=1, le=3)
    margin_top: float | None = Field(default=None, ge=0, le=72)
    margin_bottom: float | None = Field(default=None, ge=0, le=72)
    padding: float | None = Field(default=None, ge=0, le=72)
    border_left: str | None = Field(
        default=None,
        pattern=(
            r"^(?:[0-9]|1[0-2])px (?:solid|dashed|dotted) "
            r"#(?:[0-9A-Fa-f]{3}|[0-9A-Fa-f]{4}|[0-9A-Fa-f]{6}|[0-9A-Fa-f]{8})$"
        ),
    )
    text_indent: float | None = Field(default=None, ge=0, le=72)


class StyleTokenPayload(StyleContractModel):
    table_header: StyleProperties | None = None
    table_cell: StyleProperties | None = None
    title: StyleProperties | None = None
    lead: StyleProperties | None = None
    heading_marker: StyleProperties | None = None
    heading1: StyleProperties | None = None
    heading2: StyleProperties | None = None
    body: StyleProperties | None = None
    highlight: StyleProperties | None = None
    quote: StyleProperties | None = None
    list: StyleProperties | None = None
    caption: StyleProperties | None = None
    divider: StyleProperties | None = None


EvidenceBlockId = Annotated[str, Field(pattern=r"^block-[1-9][0-9]{0,3}$")]
EvidenceList = list[EvidenceBlockId]


class LayoutModuleEvidence(StyleContractModel):
    table_header: EvidenceList | None = None
    table_cell: EvidenceList | None = None
    title: EvidenceList | None = None
    lead: EvidenceList | None = None
    heading_marker: EvidenceList | None = None
    heading1: EvidenceList | None = None
    heading2: EvidenceList | None = None
    body: EvidenceList | None = None
    highlight: EvidenceList | None = None
    quote: EvidenceList | None = None
    caption: EvidenceList | None = None
    divider: EvidenceList | None = None
    list: EvidenceList | None = None


class LayoutAgentResponse(StyleContractModel):
    style_tokens: StyleTokenPayload
    confidence: float = Field(ge=0, le=1)
    module_evidence: LayoutModuleEvidence
