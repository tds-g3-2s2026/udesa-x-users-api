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

    # Five failed attempts lock the account for fifteen minutes.
    login_max_attempts: int = 5
    login_lockout_minutes: int = 15

    # The verification link expires and can be requested again.
    email_verification_hours: int = 24

    # The reset link is short lived: it opens the door to the account, unlike
    # the verification one.
    password_reset_minutes: int = 10

    # Three reset requests per hour for the same identifier. The cap also
    # protects the mail provider, not only the account.
    password_reset_max_requests: int = 3
    password_reset_window_minutes: int = 60

    # Base for the links sent by email.
    public_base_url: str = "http://localhost:8000"

    log_level: str = "INFO"


@lru_cache
def get_settings() -> Settings:
    return Settings()
