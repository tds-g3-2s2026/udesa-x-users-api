import uuid
from datetime import UTC, datetime, timedelta

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from pydantic import ValidationError

from users_api.api.schemas.auth import LoginRequest, RegisterRequest
from users_api.api.schemas.password_reset import ResetPasswordRequest
from users_api.app.security import (
    TOKEN_ALGORITHM,
    hash_password,
    hash_token,
    issue_access_token,
    load_signing_key,
    verify_password,
)

VALID = {
    "email": "alumno@udesa.edu.ar",
    "handle": "@alumno_01",
    "password": "Contrasena1",
    "terms_accepted": True,
}


def register_payload(**overrides):
    return RegisterRequest(**{**VALID, **overrides})


@pytest.mark.parametrize(
    "handle",
    ["@alumno", "@a_b_c1", "@AlumnoDeUdesa", "@0123"],
)
def test_e1_h1_ca3_accepts_valid_handles(handle):
    assert register_payload(handle=handle).handle == handle.lower()


@pytest.mark.parametrize(
    ("handle", "reason"),
    [
        ("alumno_01", "no empieza con arroba"),
        ("@abc", "menos de cuatro caracteres"),
        ("@" + "a" * 16, "mas de quince caracteres"),
        ("@alumno-01", "guion medio no permitido"),
        ("@alumno 01", "espacio no permitido"),
        ("@alumnó01", "caracter no ascii"),
    ],
)
def test_e1_h1_ca3_rejects_invalid_handles(handle, reason):
    with pytest.raises(ValidationError):
        register_payload(handle=handle)


def test_e1_h1_ca3_handle_is_stored_lowercase():
    assert register_payload(handle="@AlumnoUno").handle == "@alumnouno"


@pytest.mark.parametrize("email", ["sin-arroba", "@udesa.edu.ar", "alumno@", ""])
def test_e1_h1_ca2_rejects_invalid_email_format(email):
    with pytest.raises(ValidationError):
        register_payload(email=email)


@pytest.mark.parametrize(
    ("password", "reason"),
    [
        ("Corta1", "menos de ocho caracteres"),
        ("contrasena1", "sin mayuscula"),
        ("ContrasenaSinNumero", "sin numero"),
    ],
)
def test_e1_h1_ca4_rejects_passwords_outside_policy(password, reason):
    with pytest.raises(ValidationError):
        register_payload(password=password)


def test_e1_h1_ca4_password_is_hashed_and_never_stored_raw():
    digest = hash_password("Contrasena1")
    assert "Contrasena1" not in digest
    assert digest.startswith("$argon2")
    assert verify_password("Contrasena1", digest)
    assert not verify_password("otra", digest)


def test_e1_h1_ca4_verification_against_a_missing_hash_fails_without_raising():
    # Used when the account does not exist, so timing does not reveal it.
    assert not verify_password("Contrasena1", None)


@pytest.mark.parametrize("field", ["email", "handle", "password"])
def test_e1_h1_ca5_rejects_empty_required_fields(field):
    with pytest.raises(ValidationError):
        register_payload(**{field: ""})


def test_e1_h1_ca5_rejects_missing_required_fields():
    with pytest.raises(ValidationError):
        RegisterRequest(email="alumno@udesa.edu.ar")


def test_e1_h1_ca5_login_rejects_empty_identifier_or_password():
    with pytest.raises(ValidationError):
        LoginRequest(identifier="", password="Contrasena1")
    with pytest.raises(ValidationError):
        LoginRequest(identifier="alumno@udesa.edu.ar", password="")


def test_registration_requires_accepting_the_terms():
    with pytest.raises(ValidationError):
        register_payload(terms_accepted=False)


def test_e1_h2_ca1_token_carries_subject_role_jti_and_expiry():
    key = Ed25519PrivateKey.generate()
    subject = uuid.uuid4()
    issued_at = datetime(2026, 8, 30, 12, 0, tzinfo=UTC)

    token = issue_access_token(
        key, subject=subject, role="user", expires_in_minutes=15, now=issued_at
    )
    # Expiry is not verified here: this test is about the claims. That the token
    # expires has its own test below, with a token that really is past its date.
    claims = jwt.decode(
        token,
        key.public_key(),
        algorithms=[TOKEN_ALGORITHM],
        options={"verify_exp": False},
    )

    assert claims["sub"] == str(subject)
    assert claims["role"] == "user"
    assert uuid.UUID(claims["jti"])
    assert claims["exp"] - claims["iat"] == timedelta(minutes=15).total_seconds()


def test_e1_h2_ca1_token_is_signed_with_eddsa_and_not_hs256():
    # ARQUITECTURA.md rules out HS256: posts-api will validate these tokens and a
    # shared secret between services is exactly what must be avoided.
    key = Ed25519PrivateKey.generate()
    token = issue_access_token(key, subject=uuid.uuid4(), role="user", expires_in_minutes=15)
    assert jwt.get_unverified_header(token)["alg"] == "EdDSA"


def test_e1_h2_ca1_expired_token_is_rejected():
    key = Ed25519PrivateKey.generate()
    token = issue_access_token(
        key,
        subject=uuid.uuid4(),
        role="user",
        expires_in_minutes=15,
        now=datetime.now(UTC) - timedelta(hours=1),
    )
    with pytest.raises(jwt.ExpiredSignatureError):
        jwt.decode(token, key.public_key(), algorithms=[TOKEN_ALGORITHM])


def test_signing_key_is_generated_when_none_is_configured():
    # Development convenience: no key means an ephemeral one, so nothing has to
    # be versioned. Production passes the key through SOPS.
    assert isinstance(load_signing_key(None), Ed25519PrivateKey)


def reset_payload(**overrides):
    valid = {"token": "un-token", "password": "Contrasena2", "password_confirmation": "Contrasena2"}
    return ResetPasswordRequest(**{**valid, **overrides})


def test_e1_h5_ca3_reset_requires_matching_confirmation_and_the_password_policy():
    assert reset_payload().password == "Contrasena2"

    # La confirmacion tiene que coincidir.
    with pytest.raises(ValidationError):
        reset_payload(password_confirmation="Contrasena3")

    # Y la contrasena nueva pasa por la misma politica que la del registro,
    # porque las dos clases validan con la misma funcion.
    for invalid in ("Corta1", "contrasena2", "ContrasenaSinNumero"):
        with pytest.raises(ValidationError):
            reset_payload(password=invalid, password_confirmation=invalid)


def test_verification_tokens_are_stored_hashed():
    digest = hash_token("un-token-cualquiera")
    assert digest != "un-token-cualquiera"
    assert len(digest) == 64
    assert hash_token("un-token-cualquiera") == digest
