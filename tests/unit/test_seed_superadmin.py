"""What the seed refuses before it ever opens a connection."""

import pytest

from users_api.config.settings import Settings
from users_api.seed_superadmin import SeedConfigurationError, validate


def build_settings(**overrides) -> Settings:
    defaults = {
        "database_url": "postgresql+asyncpg://unused",
        "redis_url": "redis://unused",
        "superadmin_email": "admin@udesa.edu.ar",
        "superadmin_password": "Admin1234",
    }
    return Settings(**{**defaults, **overrides})


def test_e5_h2_seed_reads_email_handle_and_password_from_the_environment():
    assert validate(build_settings()) == ("admin@udesa.edu.ar", "@superadmin", "Admin1234")


@pytest.mark.parametrize(
    "overrides",
    [
        {"superadmin_email": None},
        {"superadmin_password": None},
        {"superadmin_password": "Corta1"},
        {"superadmin_password": "sinmayuscula1"},
        {"superadmin_password": "SinNumero"},
    ],
)
def test_e5_h2_seed_refuses_a_missing_or_weak_configuration(overrides):
    with pytest.raises(SeedConfigurationError):
        validate(build_settings(**overrides))
