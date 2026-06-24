"""A 股 / 港股 / 美股行情数据 provider。

通过 akshare 获取日线行情，按日期过滤后统一输出 CSV。
"""
from __future__ import annotations

import re
from datetime import datetime
from typing import Literal

import akshare as ak
import pandas as pd

from local_datasource.formatters import format_csv_output


Market = Literal["a", "hk", "us"]


def _filter_by_date(df: pd.DataFrame, start_date: str, end_date: str) -> pd.DataFrame:
    """统一把 ``date`` 列转成 ``YYYY-MM-DD`` 字符串后再按日期过滤。"""
    df = df.copy()
    df["date"] = pd.to_datetime(df["date"]).dt.strftime("%Y-%m-%d")
    return df[(df["date"] >= start_date) & (df["date"] <= end_date)].copy()


def _normalize_a_code(ticker: str) -> str:
    """将 A 股代码统一为 akshare 所需的 ``shxxxxxx`` / ``szxxxxxx`` / ``bjxxxxxx`` 格式。"""
    code = re.sub(r"\.(sh|sz|bj)$", "", ticker, flags=re.IGNORECASE)
    if code.startswith(("6", "5", "9")):
        return f"sh{code}"
    if code.startswith(("0", "1", "2", "3")):
        return f"sz{code}"
    if code.startswith(("4", "8", "43")):
        return f"bj{code}"
    return code


def _normalize_hk_code(ticker: str) -> str:
    """将港股代码去掉 ``.hk`` 后缀并补齐为 5 位数字。"""
    return re.sub(r"\.hk$", "", ticker, flags=re.IGNORECASE).zfill(5)


def _normalize_us_code(ticker: str) -> str:
    """将美股代码统一为大写。"""
    return ticker.upper()


def query_stock(
    ticker: str,
    market: Market,
    start_date: str,
    end_date: str,
    file_path: str,
    adjust: str = "qfq",
) -> tuple[str, str]:
    """查询指定市场的股票历史行情并输出 CSV。

    参数:
        ticker: 股票代码
        market: ``a`` / ``hk`` / ``us``
        start_date: 开始日期 ``YYYY-MM-DD``
        end_date: 结束日期 ``YYYY-MM-DD``
        file_path: 输出 CSV 路径
        adjust: 复权方式，``qfq`` / ``hfq`` / ``none``
    """
    # akshare 部分接口需要 ``YYYYMMDD`` 格式的日期字符串
    start_fmt = datetime.strptime(start_date, "%Y-%m-%d").strftime("%Y%m%d")
    end_fmt = datetime.strptime(end_date, "%Y-%m-%d").strftime("%Y%m%d")

    if market == "a":
        symbol = _normalize_a_code(ticker)
        df = ak.stock_zh_a_daily(symbol=symbol, start_date=start_fmt, end_date=end_fmt, adjust=adjust)
    elif market == "hk":
        symbol = _normalize_hk_code(ticker)
        df = ak.stock_hk_daily(symbol=symbol)
        df = _filter_by_date(df, start_date, end_date)
    elif market == "us":
        symbol = _normalize_us_code(ticker)
        df = ak.stock_us_daily(symbol=symbol)
        df = _filter_by_date(df, start_date, end_date)
    else:
        raise ValueError(f"Unsupported market: {market}")

    if df.empty:
        raise ValueError(f"No data returned for {ticker} ({market}) between {start_date} and {end_date}")

    return format_csv_output(df, file_path)
