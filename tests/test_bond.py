# tests/test_bond.py
import os
import tempfile

import pytest

from local_datasource.providers.bond import query_bond


def test_normalize_bond_code_strips_ib_suffix():
    from local_datasource.providers import bond
    assert bond._normalize_bond_code("2180495.IB") == "2180495"


def test_normalize_bond_code_strips_exchange_suffix():
    from local_datasource.providers import bond
    assert bond._normalize_bond_code("sh019623") == "sh019623"
    assert bond._normalize_bond_code("019623.SH") == "019623"


def test_normalize_bond_code_plain_digits():
    from local_datasource.providers import bond
    assert bond._normalize_bond_code("2180495") == "2180495"


def test_normalize_bond_code_invalid():
    from local_datasource.providers import bond
    with pytest.raises(ValueError):
        bond._normalize_bond_code("abc!@#")
