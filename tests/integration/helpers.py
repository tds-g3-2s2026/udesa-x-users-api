"""Shared driver for the integration suite.

Lives apart from the test modules so that the auth flow and the password reset
flow drive the app the same way instead of each keeping its own copy.
"""

import re

from sqlalchemy import text

REGISTRATION = {
    "email": "Alumno@udesa.edu.ar",
    "handle": "@alumno_01",
    "password": "Contrasena1",
    "terms_accepted": True,
}


class Api:
    """Drives the app and reads back the emailed links from the log."""

    def __init__(self, client, app, caplog):
        self.client = client
        self.app = app
        self.caplog = caplog

    async def register(self, **overrides):
        return await self.client.post("/auth/register", json={**REGISTRATION, **overrides})

    async def login(self, identifier=REGISTRATION["email"], password=REGISTRATION["password"]):
        return await self.client.post(
            "/auth/login", json={"identifier": identifier, "password": password}
        )

    async def logout(self, token: str):
        return await self.client.post("/auth/logout", headers={"Authorization": f"Bearer {token}"})

    def last_emailed_token(self) -> str:
        # The console adapter writes the link; this is what the mail would
        # carry. Verification and reset links are logged the same way, so this
        # reads whichever went out last.
        links = re.findall(r"token=([\w\-]+)", self.caplog.text)
        assert links, "no se encontro ningun link en el log"
        return links[-1]

    async def verify_last(self):
        return await self.client.post("/auth/verify", json={"token": self.last_emailed_token()})

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


async def set_user_flag(app, column: str, value) -> None:
    async with app.state.engine.begin() as connection:
        await connection.execute(text(f"UPDATE users SET {column} = :value"), {"value": value})
