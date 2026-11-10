"""Cells a spreadsheet would run as formulas (E5-H8)."""

import pytest

from users_api.api.accounts_csv import line, neutralized


@pytest.mark.parametrize("value", ["=1+1", "+54911", "-2", "@mariag", "\tx", "\rx"])
def test_a_cell_a_spreadsheet_would_execute_goes_out_escaped(value):
    assert neutralized(value) == f"'{value}"


def test_an_ordinary_cell_goes_out_as_it_is():
    assert neutralized("maria.gomez@udesa.edu.ar") == "maria.gomez@udesa.edu.ar"


def test_a_comma_inside_a_cell_does_not_split_it():
    assert line(["Gómez, María", "x"]) == '"Gómez, María",x\r\n'
