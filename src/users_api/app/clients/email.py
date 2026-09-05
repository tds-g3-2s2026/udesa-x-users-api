"""Outgoing mail, without naming a provider.

This is a client and not a repository because it does not store anything: it
hands something to a third party and forgets about it.
"""

from abc import ABC, abstractmethod


class EmailSender(ABC):
    """Sending is synchronous for now.

    A queue only pays off once notifications-api exists.
    """

    @abstractmethod
    async def send_verification(self, *, to: str, verification_url: str) -> None: ...

    @abstractmethod
    async def send_password_reset(self, *, to: str, reset_url: str) -> None: ...

    @abstractmethod
    async def send_password_changed(self, *, to: str) -> None:
        """Warn that the password of this account just changed.

        Carries no link on purpose: it is a notice, not an action. If it was not
        the owner who changed it, what they need is the recovery flow, and a
        link in this mail would be one more thing for an attacker to imitate.
        """
