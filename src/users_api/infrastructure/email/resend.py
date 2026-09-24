"""Mail delivered through Resend.

The sender's domain has to be verified in Resend: without it the provider only
delivers to the address that owns the account.
"""

import logging

import resend
from resend.exceptions import ResendError
from resend.http_client_httpx import HTTPXClient

from users_api.app.clients.email import EmailSender

logger = logging.getLogger(__name__)

# The mail goes out inside the request, so a slow provider holds the response.
# The SDK default is thirty seconds.
TIMEOUT_SECONDS = 5


class ResendEmailSender(EmailSender):
    def __init__(self, *, api_key: str, sender: str) -> None:
        # The SDK keeps its configuration at module level, not per client.
        resend.api_key = api_key
        resend.default_async_http_client = HTTPXClient(timeout=TIMEOUT_SECONDS)
        self.sender = sender

    async def send_verification(self, *, to: str, verification_url: str) -> None:
        await self.send(
            to=to,
            subject="Validá tu cuenta de UdeSA-X",
            text=(
                "Hola,\n\n"
                "Para terminar de crear tu cuenta de UdeSA-X, abrí este link:\n\n"
                f"{verification_url}\n\n"
                "El link vence. Si ya no funciona, pedí uno nuevo desde la app.\n\n"
                "Si no creaste una cuenta, ignorá este correo."
            ),
        )

    async def send_password_reset(self, *, to: str, token: str) -> None:
        await self.send(
            to=to,
            subject="Recuperá tu contraseña de UdeSA-X",
            text=(
                "Hola,\n\n"
                "Pediste cambiar la contraseña de tu cuenta de UdeSA-X. Pegá este código "
                "en la app, en la pantalla de nueva contraseña:\n\n"
                f"{token}\n\n"
                "El código vence en pocos minutos y sirve una sola vez.\n\n"
                "Si no lo pediste, ignorá este correo: tu contraseña sigue igual."
            ),
        )

    async def send_password_changed(self, *, to: str) -> None:
        await self.send(
            to=to,
            subject="La contraseña de tu cuenta de UdeSA-X cambió",
            text=(
                "Hola,\n\n"
                "La contraseña de tu cuenta de UdeSA-X acaba de cambiar y se cerraron "
                "todas las sesiones abiertas.\n\n"
                "Si no fuiste vos, recuperá el acceso desde Olvidé mi contraseña en la app."
            ),
        )

    async def send(self, *, to: str, subject: str, text: str) -> None:
        try:
            await resend.Emails.send_async(
                {"from": self.sender, "to": [to], "subject": subject, "text": text}
            )
        except ResendError as error:
            # The message is left out of the log: it carries a single use token.
            logger.error(
                "Resend did not accept the mail '%s' for %s: %s %s",
                subject,
                to,
                error.error_type,
                error.message,
            )
