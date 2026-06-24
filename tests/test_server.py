# tests/test_server.py
from local_datasource.server import build_tools


def test_build_tools_count():
    tools = build_tools()
    assert len(tools) == 4
    names = {t.name for t in tools}
    assert names == {"query_stock", "query_yfinance", "query_worldbank", "query_arxiv"}
