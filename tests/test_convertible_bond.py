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


@pytest.mark.skipif(os.environ.get("SKIP_INTEGRATION"), reason="integration")
def test_query_cb_overview():
    """可转债一览:返回全市场转债,含转股溢价率等字段,行数>0。"""
    with tempfile.NamedTemporaryFile(suffix=".csv", delete=False) as f:
        path = f.name
    try:
        file_path, summary = query_convertible_bond(kind="overview", file_path=path)
        assert os.path.exists(file_path)
        assert "Rows:" in summary
    finally:
        os.unlink(path)
