import logging
from typing import Protocol

logger = logging.getLogger(__name__)


class EmailSender(Protocol):
    """Outgoing email, behind an interface.

    S2 decided to send verification mail synchronously behind an adapter: the
    queue only makes sense once notifications-api exists, in S4. Swapping this
    for a real provider is adding one class, without touching business logic.
    """

    async def send_verification(self, *, to: str, verification_url: str) -> None: ...


class ConsoleEmailSender:
    """Writes the message to the log instead of sending it.

    The email provider is still undecided and the domain was never verified
    (risk R3), so this is what unblocks registration in development.
    """

    async def send_verification(self, *, to: str, verification_url: str) -> None:
        logger.info(
            "Correo de verificación para %s. Link válido por tiempo limitado: %s",
            to,
            verification_url,
        )
