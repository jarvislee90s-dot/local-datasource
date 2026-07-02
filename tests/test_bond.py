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


@pytest.mark.skipif(os.environ.get("SKIP_INTEGRATION"), reason="integration")
def test_query_bond_issue_info_exact_match():
    """回归 case:2180495.IB 只应返回 1 条「21徐州新盛03」,排除子串误命中的 112180495。"""
    with tempfile.NamedTemporaryFile(suffix=".csv", delete=False) as f:
        path = f.name
    try:
        file_path, summary = query_bond(kind="issue_info", bond_code="2180495.IB", file_path=path)
        assert os.path.exists(file_path)
        import pandas as pd
        df = pd.read_csv(file_path)
        assert len(df) == 1, f"expected exactly 1 row, got {len(df)}:\n{df}"
        assert "徐州新盛03" in str(df.iloc[0].values) or "2180495" in str(df.iloc[0].values)
    finally:
        os.unlink(path)


def test_query_bond_issue_info_requires_bond_code():
    from local_datasource.providers import bond
    with pytest.raises(ValueError, match="issue_info requires bond_code"):
        bond.query_bond(kind="issue_info", file_path="/tmp/x.csv")


@pytest.mark.skipif(os.environ.get("SKIP_INTEGRATION"), reason="integration")
def test_query_bond_credit_daily():
    with tempfile.NamedTemporaryFile(suffix=".csv", delete=False) as f:
        path = f.name
    try:
        file_path, summary = query_bond(
            kind="credit_daily", symbol="sh019547",
            start_date="2025-01-01", end_date="2025-06-30", file_path=path)
        assert os.path.exists(file_path)
        assert "Rows:" in summary
    finally:
        os.unlink(path)
