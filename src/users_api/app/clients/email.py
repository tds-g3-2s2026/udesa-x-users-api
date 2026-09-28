"""Outgoing mail, without naming a provider.

This is a client and not a repository because it does not store anything: it
hands something to a third party and forgets about it.
"""

from abc import ABC, abstractmethod


class EmailSender(ABC):
    """Sending never raises: a mail that fails is logged and dropped.

    Services send after their own writes and before the request's transaction
    commits, so an exception here would roll back an operation that did
    happen. Sending is synchronous until notifications-api takes it over.
    """

    @abstractmethod
    async def send_verification(self, *, to: str, verification_url: str) -> None: ...

    @abstractmethod
    async def send_password_reset(self, *, to: str, token: str) -> None:
        """Carry the token itself, for the user to paste in the app.

        Choosing the new password happens in the app, and a mail link can only
        open a browser.
        """

    @abstractmethod
    async def send_password_changed(self, *, to: str) -> None:
        """Warn that the password of this account just changed.

        Carries no link on purpose: it is a notice, not an action. If it was not
        the owner who changed it, what they need is the recovery flow, and a
        link in this mail would be one more thing for an attacker to imitate.
        """
