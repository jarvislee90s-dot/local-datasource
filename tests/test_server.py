# tests/test_server.py
"""入口层契约(2.x 形状):经 MCPServer.list_tools() 锁定工具名/required/enum。"""
import asyncio

from local_datasource.server import mcp


def _tools_by_name() -> dict:
    return {t.name: t for t in asyncio.run(mcp.list_tools())}


def _prop(schema: dict, key: str) -> dict:
    """取参数 schema:2.x 对可空参数(T | None = None)渲染为 anyOf [T, null](spec §4.4),
    无顶层 type——此处取非 null 分支,断言语义与 1.x 手写版一致。"""
    prop = schema["properties"][key]
    if "type" not in prop:
        prop = next(
            (branch for branch in prop["anyOf"] if branch["type"] != "null"),
            None,
        )
    assert prop is not None, f"{key}: 非 anyOf[T, null] 渲染"
    return prop


def test_tools_count_and_names():
    tools = _tools_by_name()
    assert len(tools) == 16
    assert set(tools) == {
        "query_stock", "query_yfinance", "query_worldbank", "query_arxiv",
        "query_bond", "query_convertible_bond", "resolve_stock_code",
        "query_futures", "query_index", "query_etf", "query_options",
        "query_global_rates", "query_fx", "query_spot", "align_series",
        "query_trading_rules",
    }


def test_align_series_schema():
    tools = _tools_by_name()
    schema = tools["align_series"].input_schema
    for key in ("file_paths", "columns", "names"):
        prop = _prop(schema, key)
        assert prop["type"] == "array"
        assert prop["items"] == {"type": "string"}
    assert set(schema["properties"]["align"]["enum"]) == {"outer", "inner"}
    assert set(schema["properties"]["fill"]["enum"]) == {"none", "ffill"}
    assert set(schema["properties"]["resample"]["enum"]) == {"none", "week", "month"}
    assert set(schema["required"]) == {"file_paths", "file_path"}


def test_query_spot_schema():
    tools = _tools_by_name()
    schema = tools["query_spot"].input_schema
    assert set(schema["properties"]["kind"]["enum"]) == {"sge", "sy"}
    symbols = _prop(schema, "symbols")
    assert symbols["type"] == "array"
    assert symbols["items"] == {"type": "string"}
    assert set(schema["required"]) == {"kind", "file_path"}


def test_query_futures_schema():
    tools = _tools_by_name()
    schema = tools["query_futures"].input_schema
    assert set(schema["properties"]["kind"]["enum"]) == {"hist", "contracts"}
    assert set(schema["properties"]["period"]["enum"]) == {"daily", "min"}
    assert set(schema["required"]) == {"symbol", "file_path"}


def test_query_options_schema():
    tools = _tools_by_name()
    schema = tools["query_options"].input_schema
    assert set(schema["properties"]["kind"]["enum"]) == {"months", "contracts", "hist"}
    assert set(schema["required"]) == {"kind", "file_path"}


def test_query_global_rates_and_fx_required():
    tools = _tools_by_name()
    for name in ("query_global_rates", "query_fx"):
        assert set(tools[name].input_schema["required"]) == {"kind", "file_path"}


def test_resolve_stock_code_schema():
    tools = _tools_by_name()
    schema = tools["resolve_stock_code"].input_schema
    assert "keyword" in schema["properties"]
    assert set(schema["required"]) == {"keyword", "file_path"}


def test_query_bond_schema_has_kind_enum():
    tools = _tools_by_name()
    schema = tools["query_bond"].input_schema
    assert set(schema["properties"]["kind"]["enum"]) == {"yield_curve", "issue_info", "credit_daily"}


def test_query_convertible_bond_schema_has_kind_enum():
    tools = _tools_by_name()
    schema = tools["query_convertible_bond"].input_schema
    assert set(schema["properties"]["kind"]["enum"]) == {
        "overview", "terms", "history", "issuer_finance",
    }


def test_query_trading_rules_schema():
    tools = _tools_by_name()
    schema = tools["query_trading_rules"].input_schema
    assert set(schema["properties"]["market"]["enum"]) == {
        "a", "etf", "cffex", "treasury_futures", "margin", "option", "hk_connect", "commodity_futures",
    }
    assert "as_of" in schema["properties"]
    assert "parameter" in schema["properties"]
    assert set(schema["required"]) == {"market", "file_path"}
