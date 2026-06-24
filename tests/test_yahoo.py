import os
import tempfile

import pytest

from local_datasource.providers.yahoo import query_yfinance


@pytest.mark.skipif(os.environ.get("SKIP_INTEGRATION"), reason="integration")
def test_query_yfinance_default_akshare():
    with tempfile.NamedTemporaryFile(suffix=".csv", delete=False) as f:
        path = f.name
    try:
        file_path, preview = query_yfinance("AAPL", period="1y", file_path=path, use_yfinance=False)
        assert os.path.exists(file_path)
        assert "Rows:" in preview
    finally:
        os.unlink(path)
