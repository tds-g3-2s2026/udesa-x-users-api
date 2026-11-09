"""The CSV of app accounts the backoffice downloads (E5-H8).

Written row by row as the search hands them over, so the file never sits whole
in memory.
"""

import csv
import io
from collections.abc import AsyncIterable, AsyncIterator, Iterable

from users_api.app.models.user import AccountStatus, User

COLUMNS = ("ID", "Handle", "Email", "Estado", "Fecha de registro")

# The words the panel uses, so the file reads like the screen it came from.
STATUS_LABELS = {
    AccountStatus.ACTIVE: "Activa",
    AccountStatus.SUSPENDED: "Bloqueada",
    AccountStatus.UNDER_REVIEW: "En revisión",
}

# A cell starting with one of these is run as a formula by Excel and others.
# Every handle starts with "@", so every handle goes out escaped.
FORMULA_PREFIXES = ("=", "+", "-", "@", "\t", "\r")


def neutralized(value: str) -> str:
    """The value with a leading apostrophe if a spreadsheet would execute it."""
    return f"'{value}" if value.startswith(FORMULA_PREFIXES) else value


def line(cells: Iterable[str]) -> str:
    buffer = io.StringIO()
    csv.writer(buffer).writerow([neutralized(cell) for cell in cells])
    return buffer.getvalue()


async def csv_lines(accounts: AsyncIterable[User]) -> AsyncIterator[str]:
    # The BOM goes first: without it Excel reads UTF-8 as Latin-1 and breaks
    # every accent.
    yield "﻿" + line(COLUMNS)
    async for user in accounts:
        yield line(
            (
                str(user.id),
                user.handle,
                user.email,
                STATUS_LABELS[user.status],
                user.created_at.isoformat(timespec="seconds"),
            )
        )
