from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Service configuration, read from the environment."""

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # No defaults on purpose: a missing URL stops the service from starting,
    # instead of failing on the first request.
    database_url: str
    redis_url: str

    # Ed25519 private key in PEM format. When absent, the service generates an
    # ephemeral pair at startup so development needs no setup. Tokens then stop
    # being valid across restarts, which is fine locally and unacceptable in
    # production, where the key arrives through SOPS.
    jwt_private_key: str | None = None
    access_token_minutes: int = 15

    # E1-H2 CA.2: five failed attempts lock the account for fifteen minutes.
    login_max_attempts: int = 5
    login_lockout_minutes: int = 15

    # E1-H1 CA.6: the verification token expires and can be requested again.
    email_verification_hours: int = 24

    # Base for the verification link sent by email.
    public_base_url: str = "http://localhost:8000"

    log_level: str = "INFO"


@lru_cache
def get_settings() -> Settings:
    return Settings()
