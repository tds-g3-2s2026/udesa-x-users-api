import asyncio
import hashlib
import logging
import secrets
import uuid
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from functools import lru_cache

import jwt
from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

logger = logging.getLogger(__name__)

_hasher = PasswordHasher(memory_cost=19 * 1024, time_cost=2, parallelism=1)
_DUMMY_PASSWORD = "not-a-real-password"
_DUMMY_HASH = _hasher.hash(_DUMMY_PASSWORD)
_LEGACY_DUMMY_HASH = PasswordHasher(memory_cost=64 * 1024, time_cost=3, parallelism=4).hash(
    _DUMMY_PASSWORD
)
_running_argon2: set[asyncio.Task[object]] = set()

TOKEN_ALGORITHM = "EdDSA"


@lru_cache(maxsize=1)
def _argon2_slot(_loop: asyncio.AbstractEventLoop) -> asyncio.Semaphore:
    return asyncio.Semaphore(1)


async def _run_argon2[T](operation: Callable[[], T]) -> T:
    slot = _argon2_slot(asyncio.get_running_loop())
    await slot.acquire()
    work = asyncio.create_task(asyncio.to_thread(operation))
    _running_argon2.add(work)

    # Argon2 keeps using the slot until the thread finishes, even if the request is cancelled.
    def release_slot(finished: asyncio.Task[T]) -> None:
        slot.release()
        _running_argon2.discard(finished)
        if not finished.cancelled():
            finished.exception()

    work.add_done_callback(release_slot)
    return await asyncio.shield(work)


async def hash_password(password: str) -> str:
    return await _run_argon2(lambda: _hasher.hash(password))


def password_needs_rehash(password_hash: str) -> bool:
    return _hasher.check_needs_rehash(password_hash)


def _password_matches(password: str, password_hash: str) -> bool:
    try:
        return _hasher.verify(password_hash, password)
    except VerifyMismatchError:
        return False


async def verify_password(password: str, password_hash: str | None) -> bool:
    """Check a password. Passing None still burns the same time on purpose."""
    candidate = password_hash or _DUMMY_HASH
    try:
        matches = await _run_argon2(lambda: _password_matches(password, candidate))
    except Exception:
        return False
    return matches and bool(password_hash)


def _login_password_matches(password: str, password_hash: str | None) -> bool:
    candidate = password_hash or _DUMMY_HASH
    try:
        matches = _password_matches(password, candidate)
    except (InvalidHashError, VerificationError):
        candidate = _DUMMY_HASH
        _password_matches(password, candidate)
        matches = False
    if matches and password_hash:
        return True

    # Failed logins spend time on both profiles while either can be stored.
    dummy = _DUMMY_HASH if password_needs_rehash(candidate) else _LEGACY_DUMMY_HASH
    _password_matches(password, dummy)
    return False


async def verify_login_password(password: str, password_hash: str | None) -> bool:
    try:
        return await _run_argon2(lambda: _login_password_matches(password, password_hash))
    except Exception:
        return False


def hash_token(raw_token: str) -> str:
    """Digest used to store emailed and refresh tokens without keeping the token itself."""
    return hashlib.sha256(raw_token.encode()).hexdigest()


def generate_emailed_token() -> str:
    return secrets.token_urlsafe(32)


def generate_refresh_token() -> str:
    """256 random bits, long enough that the digest alone is a safe way to look it up."""
    return secrets.token_urlsafe(32)


def generate_temporary_password() -> str:
    """The password an administrator hands out, meant to be replaced at once.

    Nobody has to remember it or type it twice, so it is random and long
    instead of memorable. It is hashed like any other before being stored.
    """
    return secrets.token_urlsafe(12)


def load_signing_key(pem: str | None) -> Ed25519PrivateKey:
    """Load the Ed25519 key, or mint an ephemeral one for local development.

    An ephemeral key means tokens stop being valid after a restart. That is fine
    locally and unacceptable in production, hence the warning.
    """
    if pem:
        key = serialization.load_pem_private_key(pem.encode(), password=None)
        if not isinstance(key, Ed25519PrivateKey):
            raise ValueError("JWT_PRIVATE_KEY must be an Ed25519 key in PEM format")
        return key

    logger.warning(
        "JWT_PRIVATE_KEY is not set: generating an ephemeral key. Tokens will not "
        "survive a restart. Set the key through SOPS outside development."
    )
    return Ed25519PrivateKey.generate()


def issue_access_token(
    signing_key: Ed25519PrivateKey,
    *,
    subject: uuid.UUID,
    role: str,
    handle: str,
    profile_visibility: str,
    expires_in_minutes: int,
    issuer: str,
    now: datetime | None = None,
) -> str:
    """Sign the access token described in ARQUITECTURA.md: sub, role and jti.

    EdDSA and not HS256: posts-api will validate these tokens, and a shared
    secret between services is exactly what the architecture rules out. The jti
    is what allows revoking one token without touching the rest.

    The handle travels along so the other services can name an account without
    asking this one. It is safe to copy because a handle is fixed at
    registration and the profile endpoint refuses to change it, so what the
    token carries cannot go stale.

    profile_visibility travels too, unlike the handle it can change at any
    time, so a service reading it only ever sees the value as of this
    account's last login — stale until the access token is 15 minutes old at
    most, until there is an event to carry the change sooner.
    """
    issued_at = now or datetime.now(UTC)
    payload = {
        "iss": issuer,
        "sub": str(subject),
        "role": role,
        "handle": handle,
        "profile_visibility": profile_visibility,
        "jti": str(uuid.uuid4()),
        "iat": issued_at,
        "exp": issued_at + timedelta(minutes=expires_in_minutes),
    }
    return jwt.encode(payload, signing_key, algorithm=TOKEN_ALGORITHM)


def decode_access_token(public_key, token: str, *, issuer: str) -> dict:
    return jwt.decode(
        token,
        public_key,
        algorithms=[TOKEN_ALGORITHM],
        issuer=issuer,
        options={"require": ["iss"]},
    )
