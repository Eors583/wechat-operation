"""Explicit diagnostic replay: read-only DB, one real intent call, no auth headers saved."""

import asyncio
import json
from pathlib import Path

import httpx
from sqlalchemy import select

from app.config import Settings
from app.database import Database
from app.models import AIRun, User
from app.production_providers import OpenAICompatibleModelProvider
from app.providers import EnvironmentSecretProvider


async def main():
    config = Settings.from_env()
    database = Database(config)
    output = Path("/tmp/eros-request-inspection")
    output.mkdir(exist_ok=True)
    async with database.session_maker() as session:
        run = await session.scalar(
            select(AIRun)
            .join(User, User.id == AIRun.owner_id)
            .where(User.display_name == "eros", AIRun.id == "01a06b2e-4382-700e-b425-8f7bd2a5f6fa")
        )
        assert run is not None
        context = run.context_snapshot
        route = run.model_route_snapshot
        route = (route.get("pipeline_routes") or {}).get("intent_detection") or route
        deployment = route["execution_configs"][0]
        assert "chat" in deployment["adapter"]
        prompt = "识别本轮意图并只返回一个简短类别；后端确定性边界拥有最终决定权。"
        frozen_prompt = context.get("pipeline_prompt_versions", {}).get("intent_detection")
        assert not frozen_prompt, "Use exact frozen prompt if configured"
        capture = {}

        class Capture(httpx.AsyncHTTPTransport):
            async def handle_async_request(self, request):
                payload = json.loads(request.content)
                capture.update(url=str(request.url), body=payload)
                # Never capture headers. Fingerprints are internal metadata, redact export only.
                safe = json.dumps(capture, ensure_ascii=False, indent=2)
                for item in context.get("untrusted_model_files", []):
                    fingerprint = item.get("credential_fingerprint")
                    if fingerprint:
                        safe = safe.replace(fingerprint, "[REDACTED_CREDENTIAL_FINGERPRINT]")
                (output / "actual-request.json").write_text(safe, encoding="utf-8")
                return await super().handle_async_request(request)

        secrets = EnvironmentSecretProvider(config.model_secret_master_key or config.token_secret)
        provider = OpenAICompatibleModelProvider(
            api_base=deployment["base_url"],
            api_key=secrets.resolve(deployment["secret_ref"]),
            model=deployment["model_id"],
            api_style="chat_completions",
            timeout_seconds=90,
            transport=Capture(),
        )
        result = await provider.generate(purpose="intent_detection", prompt=prompt, context=context)
        report = dict(
            source_run_id=run.id,
            source_created_at=str(run.created_at),
            mode="real_intent_replay_not_new_article",
            model=deployment["model_id"],
            provider_request_id=result.provider_request_id,
            response=result.text,
            input_tokens=result.input_tokens,
            output_tokens=result.output_tokens,
            context_keys=list(context),
            file_content_characters=[
                len(f.get("content", "")) for f in context.get("untrusted_model_files", [])
            ],
        )
        (output / "result.json").write_text(
            json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        print(json.dumps(report, ensure_ascii=False))
    await database.dispose()


if __name__ == "__main__":
    asyncio.run(main())
