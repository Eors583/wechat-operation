"""Explicit, version-checked repair using the normal AI pipeline; preserves old versions."""

import asyncio
import copy
import sys

from sqlalchemy import select

from app.config import Settings
from app.database import Database
from app.domains.ai import process_ai_run, validate_article_completeness
from app.models import AIRun, Article, ArticleVersion
from app.provider_factory import build_providers
from app.providers import EnvironmentSecretProvider


async def main() -> None:
    settings = Settings.from_env()
    db = Database(settings)
    try:
        async with db.session_maker() as session:
            article = await session.get(Article, sys.argv[1])
            assert article is not None
            key = f"repair-incomplete:{article.id}:{sys.argv[2]}"
            prior = await session.scalar(
                select(AIRun).where(
                    AIRun.owner_id == article.owner_id,
                    AIRun.idempotency_key == key,
                )
            )
            if prior:
                print("ALREADY_RECORDED", prior.id, prior.status)
                return
            base = int(sys.argv[2])
            assert article.current_version_no == base, "Article changed; refusing overwrite"
            version = await session.scalar(
                select(ArticleVersion).where(
                    ArticleVersion.article_id == article.id,
                    ArticleVersion.version_no == base,
                )
            )
            assert version is not None and version.source == "ai"
            assert len(version.plain_text) < 500, "Not the incomplete version"
            source = await session.get(AIRun, version.created_by_id)
            assert source is not None and source.owner_id == article.owner_id
            assert source.task_id == article.source_task_id
            context = copy.deepcopy(source.context_snapshot)
            context["untrusted_user_input"] = (
                "根据已经上传的麦肯锡十项永恒战略测试 PDF，生成完整公众号文章，"
                "正文2000到3500字，完整展开十项测试及实践建议，包含结尾。不能只给导语或提纲。"
            )
            context["current_article"] = {"article_id": article.id, "version_no": base}
            run = AIRun(
                owner_id=article.owner_id,
                task_id=source.task_id,
                run_type="article_generation",
                idempotency_key=key,
                model_route_snapshot=copy.deepcopy(source.model_route_snapshot),
                context_snapshot=context,
                prompt_version_id=source.prompt_version_id,
                skill_version_id=source.skill_version_id,
                quota_reserved=0,
            )
            session.add(run)
            await session.flush()
            secrets = EnvironmentSecretProvider()
            providers = build_providers(settings, secrets)

            async def event(kind: str, payload: dict) -> None:
                if kind == "stage.changed":
                    print("STAGE", payload.get("stage"), flush=True)

            await process_ai_run(
                session,
                run_id=run.id,
                model=providers.model,
                safety=providers.content_safety,
                secrets=secrets,
                model_timeout_seconds=settings.model_timeout_seconds,
                live_event_sink=event,
            )
            latest = await session.scalar(
                select(ArticleVersion).where(
                    ArticleVersion.article_id == article.id,
                    ArticleVersion.version_no == base + 1,
                )
            )
            assert latest is not None
            length = validate_article_completeness(latest.content_json, context)
            await session.commit()
            print("REPAIRED", article.id, latest.version_no, length, flush=True)
    except Exception as exc:
        print("REPAIR_FAILED", type(exc).__name__, flush=True)
        raise SystemExit(1) from None
    finally:
        await db.dispose()


if __name__ == "__main__":
    asyncio.run(main())
