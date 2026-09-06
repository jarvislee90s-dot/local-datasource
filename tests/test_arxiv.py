# tests/test_arxiv.py
import os
import tempfile

import pytest

from local_datasource.providers.arxiv import query_arxiv


@pytest.mark.skipif(os.environ.get("SKIP_INTEGRATION"), reason="integration")
def test_query_arxiv():
    with tempfile.NamedTemporaryFile(suffix=".csv", delete=False) as f:
        path = f.name
    try:
        file_path, preview = query_arxiv("machine learning", max_results=3, file_path=path)
        assert os.path.exists(file_path)
        assert "title" in preview.lower()
    finally:
        os.unlink(path)
