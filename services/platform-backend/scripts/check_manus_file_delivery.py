"""Opt-in live smoke: uploads synthetic text and runs one configured Manus task."""

import asyncio
import time
import uuid

import httpx
from sqlalchemy import select

from app.config import Settings
from app.database import Database
from app.model_files import upload_manus_file
from app.models import ModelDeployment, ModelProviderRecord
from app.production_providers import ManusModelProvider
from app.providers import EnvironmentSecretProvider


async def main() -> None:
    db = Database(Settings.from_env())
    phase = "configuration"
    try:
        async with db.session_maker() as session:
            row = (
                await session.execute(
                    select(ModelProviderRecord, ModelDeployment)
                    .join(ModelDeployment, ModelDeployment.provider_id == ModelProviderRecord.id)
                    .where(ModelProviderRecord.adapter == "manus_v2")
                )
            ).first()
            if not row:
                raise RuntimeError("No configured Manus deployment")
            provider, model = row
            key = EnvironmentSecretProvider().resolve(provider.secret_ref)
            nonce = "FILE-PROBE-" + uuid.uuid4().hex[:12]
            phase = "original_upload"
            async with httpx.AsyncClient(timeout=120, follow_redirects=False) as client:
                file_id = await upload_manus_file(
                    client,
                    api_base=provider.base_url,
                    headers={"x-manus-api-key": key},
                    filename="file-delivery-probe.txt",
                    mime_type="text/plain",
                    content=("Verification code: " + nonce).encode(),
                )
            print("ORIGINAL_UPLOAD_CONFIRMED", flush=True)
            phase = "model_read"
            result = await ManusModelProvider(
                api_base=provider.base_url,
                api_key=key,
                agent_profile=model.model_id,
            ).generate(
                purpose="conversation",
                prompt="Read the attached text file. Reply only with its verification code.",
                context={
                    "untrusted_model_files": [
                        {
                            "delivery": "manus_files_api",
                            "base_url": provider.base_url.rstrip("/"),
                            "provider_file_id": file_id,
                            "uploaded_at": time.time(),
                        }
                    ]
                },
            )
            if nonce not in result.text:
                raise RuntimeError("File verification code was not returned")
            print("MODEL_READ_ORIGINAL_CONFIRMED", flush=True)
    except Exception as exc:
        # Do not print exception messages that may contain signed URLs or secrets.
        print("SMOKE_FAILED", phase, type(exc).__name__, flush=True)
        raise SystemExit(1) from None
    finally:
        await db.dispose()


if __name__ == "__main__":
    asyncio.run(main())
