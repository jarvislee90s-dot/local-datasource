# tests/test_server.py
from local_datasource.server import build_tools


def test_build_tools_count():
    tools = build_tools()
    assert len(tools) == 16
    names = {t.name for t in tools}
    assert names == {
        "query_stock", "query_yfinance", "query_worldbank", "query_arxiv",
        "query_bond", "query_convertible_bond", "resolve_stock_code",
        "query_futures", "query_index", "query_etf", "query_options",
        "query_global_rates", "query_fx", "query_spot", "align_series",
        "query_trading_rules",
    }


def test_align_series_schema():
    """align_series:file_paths/columns/names 为字符串数组,三个枚举,required 恰为 file_paths + file_path。"""
    tools = {t.name: t for t in build_tools()}
    schema = tools["align_series"].inputSchema
    for key in ("file_paths", "columns", "names"):
        assert schema["properties"][key]["type"] == "array"
        assert schema["properties"][key]["items"] == {"type": "string"}
    assert set(schema["properties"]["align"]["enum"]) == {"outer", "inner"}
    assert set(schema["properties"]["fill"]["enum"]) == {"none", "ffill"}
    assert set(schema["properties"]["resample"]["enum"]) == {"none", "week", "month"}
    assert set(schema["required"]) == {"file_paths", "file_path"}


def test_query_spot_schema():
    """query_spot:sge/sy 枚举,symbols 为字符串数组,required 恰为 kind + file_path。"""
    tools = {t.name: t for t in build_tools()}
    schema = tools["query_spot"].inputSchema
    assert set(schema["properties"]["kind"]["enum"]) == {"sge", "sy"}
    assert schema["properties"]["symbols"]["type"] == "array"
    assert schema["properties"]["symbols"]["items"] == {"type": "string"}
    assert set(schema["required"]) == {"kind", "file_path"}


def test_query_futures_schema():
    tools = {t.name: t for t in build_tools()}
    schema = tools["query_futures"].inputSchema
    assert set(schema["properties"]["kind"]["enum"]) == {"hist", "contracts"}
    assert set(schema["properties"]["period"]["enum"]) == {"daily", "min"}
    assert set(schema["required"]) == {"symbol", "file_path"}


def test_query_options_schema():
    tools = {t.name: t for t in build_tools()}
    schema = tools["query_options"].inputSchema
    assert set(schema["properties"]["kind"]["enum"]) == {"months", "contracts", "hist"}
    assert set(schema["required"]) == {"kind", "file_path"}


def test_query_global_rates_and_fx_required():
    """M1 新增两工具的 required 恰为 kind + file_path。"""
    tools = {t.name: t for t in build_tools()}
    for name in ("query_global_rates", "query_fx"):
        schema = tools[name].inputSchema
        assert set(schema["required"]) == {"kind", "file_path"}


def test_resolve_stock_code_schema():
    """resolve_stock_code 的 inputSchema 含 keyword + file_path。"""
    tools = {t.name: t for t in build_tools()}
    schema = tools["resolve_stock_code"].inputSchema
    assert "keyword" in schema["properties"]
    assert "file_path" in schema["properties"]
    assert set(schema["required"]) == {"keyword", "file_path"}


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


def test_query_trading_rules_schema():
    """query_trading_rules:market 8 值枚举,required 恰为 market + file_path。"""
    tools = {t.name: t for t in build_tools()}
    schema = tools["query_trading_rules"].inputSchema
    assert set(schema["properties"]["market"]["enum"]) == {
        "a", "etf", "cffex", "treasury_futures", "margin", "option", "hk_connect", "commodity_futures",
    }
    assert "as_of" in schema["properties"]
    assert "parameter" in schema["properties"]
    assert set(schema["required"]) == {"market", "file_path"}
