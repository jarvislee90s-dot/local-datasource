# tests/test_worldbank.py
import os
import tempfile

import pytest

from local_datasource.providers.worldbank import query_worldbank


@pytest.mark.skipif(os.environ.get("SKIP_INTEGRATION"), reason="integration")
def test_query_worldbank_gdp():
    with tempfile.NamedTemporaryFile(suffix=".csv", delete=False) as f:
        path = f.name
    try:
        file_path, preview = query_worldbank("NY.GDP.MKTP.CD", country="CHN", start_year=2020, end_year=2023, file_path=path)
        assert os.path.exists(file_path)
        assert "CHN" in preview or "2020" in preview
    finally:
        os.unlink(path)
