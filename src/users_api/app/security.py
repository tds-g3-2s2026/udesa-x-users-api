import hashlib
import logging
import secrets
import uuid
from datetime import UTC, datetime, timedelta

import jwt
from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

logger = logging.getLogger(__name__)

# argon2id with the library defaults, which follow the OWASP recommendation.
_hasher = PasswordHasher()

# A dummy hash to verify against when the user does not exist, so that a missing
# account and a wrong password take the same time. Without this, response timing
# tells an attacker which emails are registered.
_DUMMY_HASH = _hasher.hash("not-a-real-password")

TOKEN_ALGORITHM = "EdDSA"


def hash_password(password: str) -> str:
    return _hasher.hash(password)


def verify_password(password: str, password_hash: str | None) -> bool:
    """Check a password. Passing None still burns the same time on purpose."""
    try:
        _hasher.verify(password_hash or _DUMMY_HASH, password)
    except VerifyMismatchError:
        return False
    except Exception:
        return False
    return password_hash is not None


def hash_token(raw_token: str) -> str:
    """Digest used to store emailed tokens without keeping the token itself."""
    return hashlib.sha256(raw_token.encode()).hexdigest()


def generate_emailed_token() -> str:
    return secrets.token_urlsafe(32)


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
    expires_in_minutes: int,
    now: datetime | None = None,
) -> str:
    """Sign the access token described in ARQUITECTURA.md: sub, role and jti.

    EdDSA and not HS256: posts-api will validate these tokens, and a shared
    secret between services is exactly what the architecture rules out. The jti
    is what allows revoking one token without touching the rest.
    """
    issued_at = now or datetime.now(UTC)
    payload = {
        "sub": str(subject),
        "role": role,
        "jti": str(uuid.uuid4()),
        "iat": issued_at,
        "exp": issued_at + timedelta(minutes=expires_in_minutes),
    }
    return jwt.encode(payload, signing_key, algorithm=TOKEN_ALGORITHM)


def decode_access_token(public_key, token: str) -> dict:
    return jwt.decode(token, public_key, algorithms=[TOKEN_ALGORITHM])
