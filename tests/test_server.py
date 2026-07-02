# tests/test_server.py
from local_datasource.server import build_tools


def test_build_tools_count():
    tools = build_tools()
    assert len(tools) == 6
    names = {t.name for t in tools}
    assert names == {
        "query_stock", "query_yfinance", "query_worldbank", "query_arxiv",
        "query_bond", "query_convertible_bond",
    }


def test_query_bond_schema_has_kind_enum():
    tools = {t.name: t for t in build_tools()}
    schema = tools["query_bond"].inputSchema
    assert "kind" in schema["properties"]
    assert set(schema["properties"]["kind"]["enum"]) == {"yield_curve", "issue_info", "credit_daily"}


def test_query_convertible_bond_schema_has_kind_enum():
    tools = {t.name: t for t in build_tools()}
    schema = tools["query_convertible_bond"].inputSchema
    assert "kind" in schema["properties"]
    assert set(schema["properties"]["kind"]["enum"]) == {"overview", "terms", "history", "issuer_finance"}
