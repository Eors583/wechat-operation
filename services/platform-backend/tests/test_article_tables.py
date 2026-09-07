from copy import deepcopy

import pytest

from app.domains.article import canonical_article_content
from app.domains.layout import _node_html
from app.errors import ApiError


def table_document():
    return {
        "type": "doc",
        "content": [
            {
                "type": "table",
                "content": [
                    {
                        "type": "tableRow",
                        "content": [
                            {
                                "type": "tableHeader" if row == 0 else "tableCell",
                                "attrs": {"colspan": 1, "rowspan": 1, "colwidth": None},
                                "content": [
                                    {
                                        "type": "paragraph",
                                        "content": [
                                            {"type": "text", "text": f"行{row}列{col}<script>"}
                                        ],
                                    }
                                ],
                            }
                            for col in range(3)
                        ],
                    }
                    for row in range(3)
                ],
            }
        ],
    }


def test_table_roundtrip_and_publication_html_preserve_cells():
    doc = canonical_article_content(table_document())
    assert canonical_article_content(doc) == doc
    output = _node_html(doc, {}, [0])
    assert output.count("<tr>") == 3
    assert output.count("<th ") == 3
    assert output.count("<td ") == 6
    assert "<script>" not in output
    assert "行2列2&lt;script&gt;" in output


def test_table_template_styles_apply_to_cells_and_inner_text():
    from app.domains.layout import validate_style_tokens

    tokens = validate_style_tokens(
        {
            "table_header": {
                "background": "#123456",
                "color": "#ffffff",
                "font_size": 19,
                "padding": 12,
                "align": "center",
                "border_all": "2px solid #059669",
            },
            "table_cell": {"font_size": 14, "line_height": 2, "border_all": "none"},
        }
    )
    output = _node_html(canonical_article_content(table_document()), tokens, [0])
    assert "background-color:#123456" in output
    assert "font-size:19.0px" in output and "text-align:center" in output
    assert "border:2px solid #059669" in output
    assert "font-size:14.0px" in output and "line-height:2" in output
    with pytest.raises(ApiError):
        validate_style_tokens({"table_cell": {"border_all": "1px solid red;position:fixed"}})


@pytest.mark.parametrize("bad", ["ragged", "empty", "span", "width", "html", "nested"])
def test_invalid_table_is_rejected_not_flattened(bad):
    doc = deepcopy(table_document())
    table = doc["content"][0]
    cell = table["content"][0]["content"][0]
    if bad == "ragged":
        table["content"][1]["content"].pop()
    elif bad == "empty":
        table["content"] = []
    elif bad == "span":
        cell["attrs"]["rowspan"] = 2
    elif bad == "width":
        cell["attrs"]["colwidth"] = ["1;position:fixed"]
    elif bad == "html":
        cell["attrs"]["onclick"] = "evil()"
    elif bad == "nested":
        cell["content"] = table_document()["content"]
    with pytest.raises(ApiError):
        canonical_article_content(doc)


async def test_save_reload_and_history_keep_table(app, client):
    import json

    from app.production_providers import _structured_output
    from app.providers import ModelResult
    from tests.conftest import bearer, register_and_login

    class Model:
        async def generate(self, *, purpose, prompt, context):
            text = json.dumps(table_document()) if purpose == "article_generation" else "PASS"
            return ModelResult(text, _structured_output(text), 1, 1, "table-test")

    app.state.model_provider = Model()
    login = await register_and_login(client, "table@example.com")
    headers = bearer(login["access_token"])
    created = await client.post(
        "/api/v1/tasks",
        headers={**headers, "Idempotency-Key": "table"},
        json={
            "first_message": {
                "text": "生成一篇带表格的完整文章",
                "content": {},
                "client_message_id": "table",
            }
        },
    )
    assert created.status_code == 202, created.text
    task = await client.get("/api/v1/tasks/" + created.json()["task"]["id"], headers=headers)
    article_id = task.json()["current_article_id"]
    assert article_id
    path = "/api/v1/articles/" + article_id
    first = (await client.get(path, headers=headers)).json()
    content = first["version"]["content_json"]
    assert content["content"][0]["type"] == "table"
    content["content"][0]["content"][1]["content"][1]["content"][0]["content"][0]["text"] = (
        "修改后的单元格"
    )
    saved = await client.put(
        path + "/content",
        headers={**headers, "Idempotency-Key": "table-save"},
        json={
            "base_version_no": 1,
            "title": "表格文章",
            "summary": "",
            "content": content,
            "source": "manual",
        },
    )
    assert saved.status_code == 200, saved.text
    current = (await client.get(path, headers=headers)).json()
    assert current["version"]["content_json"] == content
    history = (await client.get(path + "/versions", headers=headers)).json()["items"]
    old = next(v for v in history if v["version_no"] == 1)
    assert "修改后的单元格" not in json.dumps(old["content_json"], ensure_ascii=False)
    assert old["content_json"]["content"][0]["type"] == "table"


async def test_table_template_save_and_reload(client):
    from tests.conftest import bearer, register_and_login

    login = await register_and_login(client, "table-template@example.com")
    headers = bearer(login["access_token"])
    tokens = {
        "table_header": {"background": "#123456", "border_all": "2px solid #059669"},
        "table_cell": {"padding": 12, "font_size": 14},
    }
    response = await client.post(
        "/api/v1/layout-templates",
        headers=headers,
        json={"name": "表格样式", "enabled": True, "style_tokens": tokens},
    )
    assert response.status_code in {200, 201}, response.text
    items = (await client.get("/api/v1/layout-templates", headers=headers)).json()["items"]
    assert "#123456" in str(items) and "2px solid #059669" in str(items)
