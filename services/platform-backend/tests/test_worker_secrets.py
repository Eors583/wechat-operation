from app.config import Settings
from app.providers import EnvironmentSecretProvider
from app.worker_tasks import _configured_secrets


def test_worker_uses_the_same_development_encryption_key_as_the_api() -> None:
    settings = Settings(token_secret="development-secret-shared-by-api-and-worker")
    encrypted = EnvironmentSecretProvider(settings.token_secret).protect("model-api-key")

    assert _configured_secrets(settings).resolve(encrypted) == "model-api-key"
