import os

import pytest
import resend

from users_api.config.settings import get_settings
from users_api.infrastructure.email.resend import ResendEmailSender

pytestmark = pytest.mark.skipif(
    not os.getenv("DATABASE_URL") or not os.getenv("REDIS_URL"),
    reason="requires DATABASE_URL and REDIS_URL pointing at real services",
)


async def test_the_resend_provider_wires_the_resend_sender(monkeypatch):
    from users_api import main

    settings = get_settings().model_copy(
        update={"email_provider": "resend", "resend_api_key": "re_test"}
    )
    monkeypatch.setattr(main, "get_settings", lambda: settings)
    # The sender configures the SDK at module level; restore it for later tests.
    monkeypatch.setattr(resend, "api_key", resend.api_key)
    monkeypatch.setattr(resend, "default_async_http_client", resend.default_async_http_client)

    async with main.app.router.lifespan_context(main.app):
        assert isinstance(main.app.state.email_sender, ResendEmailSender)
