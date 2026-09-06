# tests/test_contract_regression.py
"""契约回归基线(Task 0,先于一切改动):把现存对外契约钉死。

全部离线,无网络调用。本文件不提交(tests/ 已被 .gitignore 忽略)。

后续任务约定(改这里时只动 EXPECTED_TOOL_NAMES 与注释,其余断言不动):
- Task 1 后工具数 11 → 12(query_global_rates)
- Task 5 后工具数 12 → 13
- Task 6 后工具数 13 → 14(query_spot)
- Task 7 后工具数 14 → 15(align_series)
- Task 11 后工具数 15 → 16(query_trading_rules)
- Task 12 后:文档同步(README/SKILL/CHANGELOG)
"""
import re

import pandas as pd
import pytest

from local_datasource.providers.common import CoverageError, guard_minute_depth
from local_datasource.providers.futures import query_futures
from local_datasource.server import build_tools


# ---------- 基线(写死,来自 src/local_datasource/server.py @ Task 0) ----------

EXPECTED_TOOL_NAMES = [
    "query_stock",
    "query_yfinance",
    "query_worldbank",
    "query_arxiv",
    "query_bond",
    "query_convertible_bond",
    "resolve_stock_code",
    "query_futures",
    "query_index",
    "query_etf",
    "query_options",
    "query_global_rates",
    "query_fx",
    "query_spot",
    "align_series",
    "query_trading_rules",
]

# 扩容中最易被触碰的查询工具:required 字段与现存值一致(顺序无关)
EXPECTED_REQUIRED = {
    "query_stock": ["ticker", "market", "start_date", "end_date", "file_path"],
    "query_futures": ["symbol", "file_path"],
    "query_index": ["symbol", "file_path"],
    "query_global_rates": ["kind", "file_path"],
    "query_fx": ["kind", "file_path"],
}


# ---------- 工具清单 ----------

def test_build_tools_count():
    """工具数 = EXPECTED_TOOL_NAMES 长度(单一改动点)。

    Task 11 起基线 16(query_trading_rules 已入列)。
    """
    tools = build_tools()
    assert len(tools) == len(EXPECTED_TOOL_NAMES)


def test_build_tools_names_exact():
    """注册名恰为 EXPECTED_TOOL_NAMES:既查集合(无缺失/多余),也查无重复。"""
    names = [t.name for t in build_tools()]
    assert set(names) == set(EXPECTED_TOOL_NAMES)
    assert len(names) == len(set(names)), "存在重复注册的工具名"


# ---------- required 字段 ----------

def test_required_fields_of_stock_futures_index():
    tools = {t.name: t for t in build_tools()}
    for name, expected in EXPECTED_REQUIRED.items():
        actual = tools[name].inputSchema["required"]
        assert sorted(actual) == sorted(expected), f"{name}.required 变动: {actual}"


# ---------- CoverageError / 分钟深度守卫 ----------

def test_coverage_error_is_value_error():
    assert issubclass(CoverageError, ValueError)
    # 存量 ``except ValueError`` 行为不变:CoverageError 可被 ValueError 捕获
    with pytest.raises(ValueError):
        raise CoverageError("probe")


def test_guard_minute_depth_message_contains_range_and_fix_hint():
    df = pd.DataFrame({
        "datetime": ["2026-08-26 09:31:00", "2026-08-27 15:00:00"],
        "open": [1.0, 1.1], "close": [1.0, 1.1],
    })
    with pytest.raises(CoverageError) as exc_info:
        guard_minute_depth(df, start_date="2026-08-01")
    msg = str(exc_info.value)
    assert re.search(r"\d{4}-\d{2}-\d{2}", msg), f"message 缺覆盖区间: {msg}"
    assert "补数" in msg, f"message 缺补数指引: {msg}"


def test_guard_minute_depth_passes_when_start_within_coverage():
    """正向对照:请求起点在覆盖区间内不报错(防止守卫退化为永远报错)。"""
    df = pd.DataFrame({
        "datetime": ["2026-08-26 09:31:00", "2026-08-27 15:00:00"],
        "open": [1.0, 1.1], "close": [1.0, 1.1],
    })
    guard_minute_depth(df, start_date="2026-08-26")  # 不抛即通过


# ---------- 期货日线列名契约(主连归一 + 单合约基准,M2) ----------

_FUTURES_DAILY_COLUMNS = ["date", "open", "high", "low", "close", "volume", "hold", "settle"]

_MAIN_CN_DF = pd.DataFrame({
    "日期": ["2026-08-26", "2026-08-27"],
    "开盘价": [3900.0, 3910.0], "最高价": [3950.0, 3960.0],
    "最低价": [3880.0, 3890.0], "收盘价": [3920.0, 3930.0],
    "成交量": [1000, 1100], "持仓量": [5000, 5100], "动态结算价": [3920.0, 3930.0],
})

_SINGLE_EN_DF = pd.DataFrame({
    "date": ["2026-08-26", "2026-08-27"],
    "open": [3900.0, 3910.0], "high": [3950.0, 3960.0],
    "low": [3880.0, 3890.0], "close": [3920.0, 3930.0],
    "volume": [1000, 1100], "hold": [5000, 5100], "settle": [3920.0, 3930.0],
})


def test_futures_main_and_single_contract_identical_columns(monkeypatch, tmp_path):
    """主连列名归一契约:主连(中文列上游)与单合约输出为完全相同的 8 列(含顺序)。"""
    from local_datasource.providers import futures
    monkeypatch.setattr(
        futures.ak, "futures_main_sina",
        lambda symbol, start_date, end_date: _MAIN_CN_DF.copy(),
    )
    monkeypatch.setattr(
        futures.ak, "futures_zh_daily_sina",
        lambda symbol: _SINGLE_EN_DF.copy(),
    )
    main_path = str(tmp_path / "main.csv")
    single_path = str(tmp_path / "single.csv")
    query_futures(symbol="IM0", file_path=main_path, period="daily")
    query_futures(symbol="IM2612", file_path=single_path, period="daily")
    main_cols = list(pd.read_csv(main_path, encoding="utf-8-sig", nrows=1).columns)
    single_cols = list(pd.read_csv(single_path, encoding="utf-8-sig", nrows=1).columns)
    assert main_cols == single_cols == _FUTURES_DAILY_COLUMNS
