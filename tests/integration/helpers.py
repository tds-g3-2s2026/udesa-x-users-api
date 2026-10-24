"""Shared driver for the integration suite.

Lives apart from the test modules so that the auth flow and the password reset
flow drive the app the same way instead of each keeping its own copy.
"""

from urllib.parse import parse_qs, urlsplit

from sqlalchemy import select, text

from users_api.infrastructure.database.models import OutboxModel

REGISTRATION = {
    "email": "Alumno@udesa.edu.ar",
    "handle": "@alumno_01",
    "password": "Contrasena1",
    "terms_accepted": True,
}

NEW_ADMINISTRATOR = {
    "email": "moderadora@udesa.edu.ar",
    "handle": "@moderadora",
    "role": "moderator",
}


class Api:
    """Drives the app and reads back the links and codes from the outbox."""

    def __init__(self, client, app):
        self.client = client
        self.app = app

    async def register(self, **overrides):
        return await self.client.post("/auth/register", json={**REGISTRATION, **overrides})

    async def login(self, identifier=REGISTRATION["email"], password=REGISTRATION["password"]):
        return await self.client.post(
            "/auth/login", json={"identifier": identifier, "password": password}
        )

    async def admin_login(self, email=REGISTRATION["email"], password=REGISTRATION["password"]):
        return await self.client.post(
            "/admin/auth/login", json={"email": email, "password": password}
        )

    async def create_administrator(self, token: str, **overrides):
        return await self.client.post(
            "/admin/users",
            headers={"Authorization": f"Bearer {token}"},
            json={**NEW_ADMINISTRATOR, **overrides},
        )

    async def reset_temporary_password(self, token: str, user_id: str):
        return await self.client.post(
            f"/admin/users/{user_id}/reset-temporary-password",
            headers={"Authorization": f"Bearer {token}"},
        )

    async def list_administrators(self, token: str):
        return await self.client.get("/admin/users", headers={"Authorization": f"Bearer {token}"})

    async def put_under_review(self, user_id: str, internal_token: str | None = None):
        """Call the internal route the way posts-api does, outside `/api`."""
        headers = {} if internal_token is None else {"X-Internal-Token": internal_token}
        # An absolute URL so the client does not add the /api prefix.
        return await self.client.post(
            f"http://test/internal/users/{user_id}/review", headers=headers
        )

    async def get_public_profile(self, user_id: str, internal_token: str | None = None):
        """Read the profile the way posts-api does, outside `/api`."""
        headers = {} if internal_token is None else {"X-Internal-Token": internal_token}
        return await self.client.get(
            f"http://test/internal/users/{user_id}/profile", headers=headers
        )

    async def logout(self, token: str, refresh_token: str | None = None):
        # Without the body at all when there is no refresh token: the route has
        # to accept both shapes.
        body = {} if refresh_token is None else {"json": {"refresh_token": refresh_token}}
        return await self.client.post(
            "/auth/logout", headers={"Authorization": f"Bearer {token}"}, **body
        )

    async def refresh(self, refresh_token: str):
        return await self.client.post("/auth/refresh", json={"refresh_token": refresh_token})

    async def delete_account(self, token: str, current_password: str):
        # httpx's `delete()` takes no body, so the verb goes through `request()`.
        return await self.client.request(
            "DELETE",
            "/me",
            headers={"Authorization": f"Bearer {token}"},
            json={"current_password": current_password},
        )

    async def change_password(
        self,
        token: str,
        current: str,
        new: str,
        confirmation: str | None = None,
    ):
        return await self.client.post(
            "/me/change-password",
            headers={"Authorization": f"Bearer {token}"},
            json={
                "current_password": current,
                "password": new,
                "password_confirmation": new if confirmation is None else confirmation,
            },
        )

    async def outbox_events(self) -> list[dict]:
        """The envelopes waiting in the outbox, oldest first."""
        async with self.app.state.engine.connect() as connection:
            rows = await connection.scalars(
                select(OutboxModel.payload).order_by(OutboxModel.created_at)
            )
            return list(rows)

    async def last_event(self) -> dict:
        events = await self.outbox_events()
        assert events, "no hay ningun evento en el outbox"
        return events[-1]

    async def last_token(self) -> str:
        """The token the last event carries: from the link, or the bare reset code."""
        data = (await self.last_event())["data"]
        if "verification_url" in data:
            return parse_qs(urlsplit(data["verification_url"]).query)["token"][0]
        return data["token"]

    async def last_link(self) -> str:
        """The whole URL the last event carries, not just its token."""
        return (await self.last_event())["data"]["verification_url"]

    async def open_last_link(self):
        """GET the link, the way a browser opens it from the mail."""
        link = urlsplit(await self.last_link())
        # The client's base URL already carries the /api prefix.
        return await self.client.get(f"{link.path.removeprefix('/api')}?{link.query}")

    async def verify_last(self):
        return await self.client.post("/auth/verify", json={"token": await self.last_token()})

    async def register_and_verify(self, **overrides):
        await self.register(**overrides)
        await self.verify_last()

    async def forgot_password(self, identifier=REGISTRATION["email"]):
        return await self.client.post("/auth/forgot-password", json={"identifier": identifier})

    async def reset_password(self, token: str, password: str, confirmation: str | None = None):
        return await self.client.post(
            "/auth/reset-password",
            json={
                "token": token,
                "password": password,
                "password_confirmation": password if confirmation is None else confirmation,
            },
        )

    async def get_profile(self, token: str):
        return await self.client.get("/me", headers={"Authorization": f"Bearer {token}"})

    async def update_profile(self, token: str, **fields):
        return await self.client.patch(
            "/me", headers={"Authorization": f"Bearer {token}"}, json=fields
        )

    async def get_preferences(self, token: str):
        return await self.client.get(
            "/me/preferences", headers={"Authorization": f"Bearer {token}"}
        )

    async def update_preferences(self, token: str, **fields):
        return await self.client.patch(
            "/me/preferences", headers={"Authorization": f"Bearer {token}"}, json=fields
        )


async def set_user_flag(app, column: str, value) -> None:
    async with app.state.engine.begin() as connection:
        await connection.execute(text(f"UPDATE users SET {column} = :value"), {"value": value})
