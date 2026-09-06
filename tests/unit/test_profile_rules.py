import pytest
from pydantic import ValidationError

from users_api.api.schemas.profile import (
    BIO_MAX_LENGTH,
    DISPLAY_NAME_MAX_LENGTH,
    UpdateProfileRequest,
)


def field_errors(error: ValidationError) -> list[str]:
    return [str(problem["loc"][0]) for problem in error.errors()]


def test_e1_h6_ca1_rejects_text_over_the_maximum_length():
    with pytest.raises(ValidationError) as error:
        UpdateProfileRequest(bio="a" * (BIO_MAX_LENGTH + 1))
    assert field_errors(error.value) == ["bio"]

    # El limite se mide sobre lo que mando el cliente, antes de sanitizar: si
    # se midiera despues, un texto lleno de tags podria colarse por debajo del
    # limite una vez que las etiquetas se recortan.
    with pytest.raises(ValidationError):
        UpdateProfileRequest(display_name="<b>" + "a" * DISPLAY_NAME_MAX_LENGTH + "</b>")

    # Justo en el limite, sin tags, entra.
    assert UpdateProfileRequest(bio="a" * BIO_MAX_LENGTH).bio == "a" * BIO_MAX_LENGTH


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("<script>alert(1)</script>Hola", "Hola"),
        ("Con <b>negrita</b> y <i>cursiva</i>", "Con negrita y cursiva"),
        ('<a href="javascript:alert(1)">click</a>', "click"),
        ("<img src=x onerror=alert(1)>Pie de foto", "Pie de foto"),
        ("Sin ninguna etiqueta", "Sin ninguna etiqueta"),
    ],
)
def test_e1_h6_ca4_strips_html_and_scripts_from_text_fields(raw, expected):
    assert UpdateProfileRequest(bio=raw).bio == expected
    assert UpdateProfileRequest(display_name=raw).display_name == expected


@pytest.mark.parametrize("blank", [None, "", "   ", "<b></b>"])
def test_e1_h6_ca5_rejects_a_blank_display_name(blank):
    with pytest.raises(ValidationError) as error:
        UpdateProfileRequest(display_name=blank)
    assert field_errors(error.value) == ["display_name"]
    assert "no puede quedar vacío" in error.value.errors()[0]["msg"]


def test_e1_h6_ca5_a_blank_bio_is_allowed():
    # A la biografia no la alcanza la misma regla: se puede vaciar.
    assert UpdateProfileRequest(bio="   ").bio == ""


def test_update_profile_request_rejects_the_email_and_the_handle():
    with pytest.raises(ValidationError) as error:
        UpdateProfileRequest(email="otro@udesa.edu.ar")
    assert field_errors(error.value) == ["email"]

    with pytest.raises(ValidationError) as error:
        UpdateProfileRequest(handle="@otro")
    assert field_errors(error.value) == ["handle"]


def test_update_profile_request_omitting_a_field_leaves_it_unset():
    payload = UpdateProfileRequest(display_name="Juan Perez")
    assert payload.model_dump(exclude_unset=True) == {"display_name": "Juan Perez"}
