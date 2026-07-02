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


@pytest.mark.skipif(os.environ.get("SKIP_INTEGRATION"), reason="integration")
def test_query_bond_yield_curve():
    with tempfile.NamedTemporaryFile(suffix=".csv", delete=False) as f:
        path = f.name
    try:
        file_path, summary = query_bond(
            kind="yield_curve", start_date="2025-01-01", end_date="2025-06-30", file_path=path)
        assert os.path.exists(file_path)
        assert "Rows:" in summary
        assert "Columns:" in summary
    finally:
        os.unlink(path)
