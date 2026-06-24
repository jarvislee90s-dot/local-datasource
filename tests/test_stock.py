# tests/test_stock.py
import os
import tempfile

import pytest

from local_datasource.providers.stock import query_stock


@pytest.mark.skipif(os.environ.get("SKIP_INTEGRATION"), reason="integration")
def test_query_stock_a_share():
    with tempfile.NamedTemporaryFile(suffix=".csv", delete=False) as f:
        path = f.name
    try:
        file_path, preview = query_stock("600519", market="a", start_date="2025-06-01", end_date="2026-06-24", file_path=path)
        assert os.path.exists(file_path)
        assert "Rows:" in preview
    finally:
        os.unlink(path)


def test_query_stock_normalizes_code():
    from local_datasource.providers import stock
    assert stock._normalize_a_code("600519") == "sh600519"
    assert stock._normalize_hk_code("00700") == "00700"
    assert stock._normalize_us_code("AAPL") == "AAPL"
