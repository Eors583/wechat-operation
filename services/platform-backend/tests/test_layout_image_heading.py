from unittest.mock import AsyncMock, MagicMock

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings
from app.domains import layout
from app.model_gateway import RoutedModelResult
from app.models import LayoutTemplate, OfficialAccount
from app.providers import LayoutExtractionResult, ModelResult


@pytest.mark.parametrize("source_account", ["其他公众号", ""])
async def test_extracted_heading_images_survive_account_difference(
    monkeypatch: pytest.MonkeyPatch, source_account: str,
) -> None:
    template = LayoutTemplate(
        id="template", owner_id="owner", official_account_id="account",
        source_url="https://mp.weixin.qq.com/s/example", extraction_status="queued",
    )
    session = MagicMock(spec=AsyncSession)
    session.scalar.side_effect = [template, None]
    session.get.return_value = OfficialAccount(name="目标公众号")
    snapshot = {
        "account_name": source_account,
        "content_blocks": [
            {"id": "content-1", "html": '<p><img src="https://mmbiz.qpic.cn/01.png"></p>',
             "text": "", "module": "body"},
            {"id": "content-2", "html": "<h2>原文标题</h2>",
             "text": "原文标题", "module": "heading1"},
        ],
    }
    provider = MagicMock()
    provider.extract = AsyncMock(return_value=LayoutExtractionResult(
        style_tokens={}, source_snapshot=snapshot, extractor_version="test",
    ))
    result = ModelResult(
        text="", input_tokens=1, output_tokens=1, provider_request_id="test",
        structured={
            "style_tokens": {"heading_marker": {"enabled": False}}, "confidence": 0.95,
            "module_evidence": {}, "image_markers": [
                {"image_id": "image-1", "sequence": 1,
                 "heading_block_id": "content-2", "confidence": 0.95},
            ],
        },
    )
    monkeypatch.setattr(layout, "generate_with_frozen_route", AsyncMock(
        return_value=RoutedModelResult(result=result, attempts=()),
    ))
    save = AsyncMock()
    monkeypatch.setattr(layout, "add_template_version", save)
    await layout.process_layout_extraction(
        session, template_id="template", provider=provider, route_snapshot={},
        model=MagicMock(), secrets=MagicMock(), settings=Settings(),
    )
    saved = save.call_args.kwargs
    group = saved["source_snapshot"]["component_groups"][0]
    assert group["enabled"] is True
    assert group["confirmed"] is True
    assert saved["style_tokens"]["heading_marker"]["enabled"] is False
    # Render the same heading across two visual lines with one image and one heading.
    rendered = layout._document_with_locked_content(
        {"type": "doc", "content": [{"type": "heading", "attrs": {"level": 2},
         "content": [{"type": "text", "text": "第一行"}, {"type": "hardBreak"},
                     {"type": "text", "text": "第二行"}]}]},
        saved["style_tokens"], saved["source_snapshot"],
    )
    assert rendered.count("<img ") == 1
    assert rendered.count("<h2 ") == 1
    assert "第一行<br>第二行" in rendered
