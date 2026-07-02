# tests/test_convertible_bond.py
import os
import tempfile

import pytest

from local_datasource.providers.convertible_bond import query_convertible_bond


def test_normalize_cb_code_native():
    from local_datasource.providers import convertible_bond as cb
    assert cb._normalize_cb_code("sz128039") == "sz128039"


def test_normalize_cb_code_plain_digits_sz():
    from local_datasource.providers import convertible_bond as cb
    assert cb._normalize_cb_code("128039") == "sz128039"


def test_normalize_cb_code_plain_digits_sh():
    from local_datasource.providers import convertible_bond as cb
    assert cb._normalize_cb_code("113682") == "sh113682"


def test_normalize_cb_code_suffix():
    from local_datasource.providers import convertible_bond as cb
    assert cb._normalize_cb_code("113682.SH") == "sh113682"


def test_normalize_cb_code_invalid():
    from local_datasource.providers import convertible_bond as cb
    with pytest.raises(ValueError):
        cb._normalize_cb_code("abc!@#")
