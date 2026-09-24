"""ResendEmailSender against a fake HTTP client, so no mail leaves the machine.

The SDK looks its HTTP client up at module level on every call, which is what
lets a test swap it after the adapter is built.
"""

import json
from unittest.mock import Mock

import pytest
import resend
from pydantic import ValidationError
from resend.http_client_async import AsyncHTTPClient

from users_api.config.settings import Settings
from users_api.infrastructure.email import resend as resend_adapter
from users_api.infrastructure.email.resend import ResendEmailSender

SENDER = "UdeSA-X <no-reply@udesax.app>"
LINK = "https://udesax.app/api/auth/verify?token=secret-token"


class FakeResend(AsyncHTTPClient):
    def __init__(self, *, status: int = 200, fail: bool = False) -> None:
        self.status = status
        self.fail = fail
        self.sent: list[dict] = []

    async def request(self, method, url, headers, json=None, files=None, data=None):
        if self.fail:
            raise ConnectionError("provider unreachable")
        self.sent.append(json)
        body = b'{"id": "email-id"}' if self.status == 200 else b'{"name": "internal_server_error"}'
        return body, self.status, {"content-type": "application/json"}


@pytest.fixture
def build_sender(monkeypatch):
    # Recorded first so the module level configuration the adapter writes is
    # restored after each test.
    monkeypatch.setattr(resend, "api_key", None)
    monkeypatch.setattr(resend, "default_async_http_client", None)

    def build(fake: FakeResend) -> ResendEmailSender:
        sender = ResendEmailSender(api_key="re_test", sender=SENDER)
        resend.default_async_http_client = fake
        return sender

    return build


async def test_verification_mail_carries_the_link_from_the_verified_sender(build_sender):
    fake = FakeResend()

    await build_sender(fake).send_verification(to="alumno@udesa.edu.ar", verification_url=LINK)

    [mail] = fake.sent
    assert mail["from"] == SENDER
    assert mail["to"] == ["alumno@udesa.edu.ar"]
    assert LINK in mail["text"]


async def test_reset_mail_carries_the_link(build_sender):
    fake = FakeResend()

    await build_sender(fake).send_password_reset(to="alumno@udesa.edu.ar", reset_url=LINK)

    [mail] = fake.sent
    assert LINK in mail["text"]


async def test_password_changed_mail_carries_no_link(build_sender):
    fake = FakeResend()

    await build_sender(fake).send_password_changed(to="alumno@udesa.edu.ar")

    [mail] = fake.sent
    assert "http" not in json.dumps(mail)


@pytest.mark.parametrize("fake", [FakeResend(status=500), FakeResend(fail=True)])
async def test_provider_failure_is_logged_without_raising_or_leaking_the_link(
    build_sender, fake, monkeypatch
):
    # A mock and not caplog: the in-process Alembic run of the integration
    # suite disables every logger that exists before it, this one included.
    logger = Mock()
    monkeypatch.setattr(resend_adapter, "logger", logger)

    await build_sender(fake).send_verification(to="alumno@udesa.edu.ar", verification_url=LINK)

    logged = str(logger.error.call_args)
    assert "alumno@udesa.edu.ar" in logged
    assert "secret-token" not in logged


def test_resend_provider_refuses_to_start_without_its_key():
    with pytest.raises(ValidationError, match="RESEND_API_KEY"):
        Settings(
            database_url="postgresql+asyncpg://unused",
            redis_url="redis://unused",
            email_provider="resend",
            # Explicit, so a key in a local .env cannot make the test pass.
            resend_api_key=None,
        )
