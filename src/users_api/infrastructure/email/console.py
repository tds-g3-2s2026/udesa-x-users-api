"""Mail that never leaves the machine.

Writes the message to the log instead of sending it. The provider is still
undecided and the domain was never verified, so this is what unblocks
registration and recovery in development.

Replacing it is writing another class against the same interface and changing
one line in `main.py`. No service is touched.
"""

import logging

from users_api.app.clients.email import EmailSender

logger = logging.getLogger(__name__)


class ConsoleEmailSender(EmailSender):
    async def send_verification(self, *, to: str, verification_url: str) -> None:
        logger.info(
            "Correo de verificación para %s. Link válido por tiempo limitado: %s",
            to,
            verification_url,
        )

    async def send_password_reset(self, *, to: str, reset_url: str) -> None:
        logger.info(
            "Correo de recuperación para %s. Link válido por tiempo limitado: %s",
            to,
            reset_url,
        )
