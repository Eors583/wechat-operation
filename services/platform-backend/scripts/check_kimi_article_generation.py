"""Opt-in paid smoke against an existing run's file context; never saves an article."""

import asyncio
import sys
from time import perf_counter

from app.config import Settings
from app.database import Database
from app.domains.ai import article_output_contract, generated_article_content
from app.domains.article import extract_plain_text
from app.models import AIRun
from app.production_providers import OpenAICompatibleModelProvider
from app.providers import EnvironmentSecretProvider


async def main() -> None:
    db = Database(Settings.from_env())
    phase = "configuration"
    try:
        async with db.session_maker() as session:
            run = await session.get(AIRun, sys.argv[1])
            assert run is not None
            config = run.model_route_snapshot["execution_configs"][0]
            assert config["model_id"] == "kimi-k2.6"
            model = OpenAICompatibleModelProvider(
                api_base=config["base_url"],
                api_key=EnvironmentSecretProvider().resolve(config["secret_ref"]),
                model=config["model_id"],
                api_style="chat_completions",
                timeout_seconds=240,
            )
            context = {
                "untrusted_user_input": "根据附件写一篇1200到1800字的完整文章，"
                "包含标题、正文和一个三列表格。直接完成，不再追问。",
                "untrusted_model_files": run.context_snapshot["untrusted_model_files"],
            }
            phase = "article_planning"
            started = perf_counter()
            plan = await model.generate(
                purpose=phase,
                prompt="简要规划文章结构和引用，不超过500字。",
                context=context,
            )
            print("PLANNING_OK", round(perf_counter() - started, 1), flush=True)
            context["article_plan"] = plan.text
            phase = "article_generation"
            started = perf_counter()
            result = await model.generate(
                purpose=phase, prompt=article_output_contract(), context=context
            )
            phase = "validation"
            document = generated_article_content(result.structured)
            length = len(extract_plain_text(document))
            assert length >= 800
            assert any(n["type"] == "table" for n in document["content"])
            print(
                "ARTICLE_VALID_WITH_TABLE", length, round(perf_counter() - started, 1), flush=True
            )
    except Exception as exc:
        print("SMOKE_FAILED", phase, type(exc).__name__, flush=True)
        raise SystemExit(1) from None
    finally:
        await db.dispose()


if __name__ == "__main__":
    asyncio.run(main())
