"""Explicit read-only replay of a failed source through the real compression provider."""

import asyncio
import hashlib
import json
from pathlib import Path

from app.config import Settings
from app.database import Database
from app.long_context import context_budget, encoded_size, fit_context, summary_prompt
from app.models import AIRun
from app.production_providers import OpenAICompatibleModelProvider
from app.providers import EnvironmentSecretProvider


async def main():
    settings = Settings.from_env()
    database = Database(settings)
    async with database.session_maker() as session:
        run = await session.get(AIRun, "01a06bb0-532b-7131-bbca-a01be5de4187")
        config = run.model_route_snapshot["execution_configs"][0]
        secrets = EnvironmentSecretProvider(
            settings.model_secret_master_key or settings.token_secret
        )
        provider = OpenAICompatibleModelProvider(
            api_base=config["base_url"],
            api_key=secrets.resolve(config["secret_ref"]),
            model=config["model_id"],
            api_style="chat_completions",
            timeout_seconds=90,
        )
        calls = 0
        cache_dir = Path("/tmp/failed-context-replay-cache")
        cache_dir.mkdir(exist_ok=True)

        async def summarize(part):
            nonlocal calls
            cache_path = (
                cache_dir / hashlib.sha256(json.dumps(part, sort_keys=True).encode()).hexdigest()
            )
            if cache_path.exists():
                cached = cache_path.read_text(encoding="utf-8")
                if len(cached.encode()) <= part["max_summary_bytes"]:
                    return cached
            calls += 1
            result = await provider.generate(
                purpose="memory_summary",
                prompt=summary_prompt(part),
                context=part,
            )
            print(
                "summary bytes=",
                len(result.text.encode()),
                "requested=",
                part["max_summary_bytes"],
                flush=True,
            )
            cache_path.write_text(result.text, encoding="utf-8")
            return result.text

        async def progress(part):
            print(
                "reading",
                part["source"],
                part["part"],
                "/",
                part["total"],
                "retry",
                part.get("compression_retry", 0),
                flush=True,
            )

        budget = context_budget(run.model_route_snapshot, "验证预留" * 300)
        result = await fit_context(
            run.context_snapshot, budget=budget, summarize=summarize, progress=progress, cache={}
        )
        assert encoded_size(result) <= budget
        print(
            "VERIFIED",
            "bytes=",
            encoded_size(result),
            "budget=",
            budget,
            "calls=",
            calls,
            flush=True,
        )
    await database.dispose()


if __name__ == "__main__":
    asyncio.run(main())
