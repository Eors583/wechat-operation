"""Targeted v4 recovery; dry-run by default. Never rewrites existing versions."""

import argparse
import asyncio
import json
import re

from sqlalchemy import select

from app.config import Settings
from app.database import Database
from app.domains.article import canonical_article_content, extract_plain_text, save_article_version
from app.models import Article, ArticleVersion

ARTICLE_ID = "01a06a13-df3a-7d1b-bdda-c9fb643a64c5"


async def main(apply: bool) -> None:
    db = Database(Settings.from_env())
    try:
        async with db.session_maker() as session:
            article = await session.get(Article, ARTICLE_ID)
            assert article is not None and article.current_version_no == 4
            version = await session.scalar(
                select(ArticleVersion).where(
                    ArticleVersion.article_id == ARTICLE_ID, ArticleVersion.version_no == 4
                )
            )
            assert version is not None
            raw = extract_plain_text(version.content_json)
            # One verified missing object opener in this exact v4 payload.
            for label in ("第一，", "第二，", "第三，"):
                broken = '{"type":"text","text":"' + label + '"},"type":"text"'
                assert raw.count(broken) == 1
                raw = raw.replace(broken, broken.replace('},"type"', '},{"type"'))
            decoder = json.JSONDecoder()
            document, position = decoder.raw_decode(raw)
            assert document["type"] == "doc"
            # The broken response prematurely closed its root multiple times.
            # Decode every remaining node, accepting only closing/separator tokens
            # between nodes. No regex rewrite of prose, no model, no truncation.
            while position < len(raw):
                if raw[position] in " \n\r\t,]}":
                    position += 1
                    continue
                node, position = decoder.raw_decode(raw, position)
                assert isinstance(node, dict) and node.get("type") != "doc"
                document["content"].append(node)
            # Preserve row/cell grouping with supported list paragraphs, including
            # every original text node. This editor does not support table nodes.
            for index, node in enumerate(document["content"]):
                if node.get("type") == "table":
                    items = []
                    for row in node["content"]:
                        assert row["type"] == "tableRow"
                        paragraphs = []
                        for cell in row["content"]:
                            assert cell["type"] in {"tableCell", "tableHeader"}
                            assert all(p["type"] == "paragraph" for p in cell["content"])
                            paragraphs.extend(cell["content"])
                        items.append({"type": "listItem", "content": paragraphs})
                    document["content"][index] = {"type": "bulletList", "content": items}
            document = canonical_article_content(document)
            original_texts = [
                json.loads(value) for value in re.findall(r'"text"\s*:\s*("(?:[^"\\]|\\.)*")', raw)
            ]

            def texts(node):
                if node.get("type") == "text":
                    yield node["text"]
                for child in node.get("content", []):
                    yield from texts(child)

            assert list(texts(document)) == original_texts
            title = extract_plain_text(document["content"][0]).strip()
            assert document["content"][0]["type"] == "heading" and 0 < len(title) <= 120
            print(
                json.dumps(
                    {
                        "apply": apply,
                        "nodes": len(document["content"]),
                        "text_nodes_preserved": len(original_texts),
                    },
                    ensure_ascii=False,
                )
            )
            if apply:
                _, saved = await save_article_version(
                    session,
                    owner_id=article.owner_id,
                    article_id=ARTICLE_ID,
                    base_version_no=4,
                    title=title,
                    summary=article.summary,
                    content=document,
                    source="restore",
                    created_by_type="user",
                    created_by_id=article.owner_id,
                )
                await session.commit()
                print("Recovered as version", saved.version_no)
    finally:
        await db.dispose()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true")
    asyncio.run(main(parser.parse_args().apply))
