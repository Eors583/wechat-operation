"""Restore the verified original table into a NEW version; default is read-only."""

import argparse
import asyncio
import copy
import json

from sqlalchemy import select

from app.config import Settings
from app.database import Database
from app.domains.article import canonical_article_content, extract_plain_text, save_article_version
from app.models import Article, ArticleVersion, Message
from scripts.repair_serialized_article_v4 import ARTICLE_ID


async def main(apply: bool):
    db = Database(Settings.from_env())
    try:
        async with db.session_maker() as session:
            article = await session.get(Article, ARTICLE_ID)
            assert article is not None
            versions = (
                await session.scalars(
                    select(ArticleVersion).where(ArticleVersion.article_id == ARTICLE_ID)
                )
            ).all()
            original = next(v for v in versions if v.version_no == 4)
            current = next(v for v in versions if v.version_no == article.current_version_no)
            # The intact first root includes the complete table, before the JSON error.
            first, _ = json.JSONDecoder().raw_decode(extract_plain_text(original.content_json))
            tables = [n for n in first["content"] if n["type"] == "table"]
            assert len(tables) == 1
            table = canonical_article_content({"type": "doc", "content": tables})["content"][0]
            content = copy.deepcopy(current.content_json)
            if table in content["content"]:
                print("Original table already restored; no write.")
                return
            matches = [
                i
                for i, node in enumerate(content["content"])
                if node["type"] == "bulletList"
                and extract_plain_text(node) == extract_plain_text(table)
            ]
            assert len(matches) == 1, "Current content changed; refuse to overwrite user edits."
            content["content"][matches[0]] = table
            assert extract_plain_text(content) == extract_plain_text(current.content_json)
            print(
                {
                    "apply": apply,
                    "base_version": article.current_version_no,
                    "rows": len(table["content"]),
                    "columns": len(table["content"][0]["content"]),
                }
            )
            if apply:
                _, saved = await save_article_version(
                    session,
                    owner_id=article.owner_id,
                    article_id=article.id,
                    base_version_no=article.current_version_no,
                    title=article.title,
                    summary=article.summary,
                    content=content,
                    source="restore",
                    created_by_type="user",
                    created_by_id=article.owner_id,
                )
                if article.source_task_id:
                    session.add(
                        Message(
                            task_id=article.source_task_id,
                            role="assistant",
                            plain_text="表格已恢复为原来的三列结构，正文未改写，旧版本保留。",
                            content_json={"article_id": article.id, "version_no": saved.version_no},
                        )
                    )
                await session.commit()
                print("Restored table as version", saved.version_no)
    finally:
        await db.dispose()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true")
    asyncio.run(main(parser.parse_args().apply))
