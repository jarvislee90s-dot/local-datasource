"""A股场内 ETF provider:日线(新浪,约 2012 起全历史)+ 分钟(腾讯,约 8 个交易日)。

新浪 ETF 日线源无复权参数,返回原始价格(已在 SKILL.md 注意中明示)。
"""
from __future__ import annotations

import re
from typing import Literal

import akshare as ak

from local_datasource.formatters import format_csv_output
from local_datasource.providers.common import fetch_tencent_minute, filter_by_date


EtfPeriod = Literal["daily", "min"]


def _normalize_etf_code(symbol: str) -> str:
    """ETF 代码归一为 ``sh/sz + 6 位``:``5`` 开头沪市,``1`` 开头(15x/16x)深市。"""
    s = re.sub(r"\.(sh|sz)$", "", str(symbol).strip(), flags=re.IGNORECASE).lower()
    m = re.fullmatch(r"(sh|sz)(\d{6})", s)
    if m:
        return s
    if re.fullmatch(r"\d{6}", s):
        if s.startswith("5"):
            return f"sh{s}"
        if s.startswith(("15", "16")):
            return f"sz{s}"
        raise ValueError(f"Not an ETF code (ETF: 5 开头沪市 / 15x·16x 深市): {symbol}")
    raise ValueError(f"Invalid ETF code: {symbol}(示例: 510300 / sh510300)")


def query_etf(
    symbol: str,
    file_path: str,
    period: EtfPeriod = "daily",
    freq: str = "1",
    start_date: str | None = None,
    end_date: str | None = None,
):
    """查询 A 股场内 ETF 并输出 CSV。

    参数:
        symbol: ETF 代码,如 ``510300``/``sh510300``
        period: ``daily`` 默认 / ``min``
        freq: 分钟粒度 1/5/15/30/60,默认 1
        start_date/end_date: ``YYYY-MM-DD``(min 必填)
    """
    code = _normalize_etf_code(symbol)

    if period == "min":
        if not start_date or not end_date:
            raise ValueError("period=min 需提供 start_date 与 end_date(分钟深度有限,用于覆盖校验)")
        df = fetch_tencent_minute(code, freq, start_date, end_date)
        return format_csv_output(df, file_path)

    if period != "daily":
        raise ValueError(f"Unsupported period: {period}, use 'daily' or 'min'")

    df = ak.fund_etf_hist_sina(symbol=code)
    if df.empty:
        raise ValueError(f"No daily data for ETF {symbol}")
    if start_date or end_date:
        df = filter_by_date(df, start_date or "0001-01-01", end_date or "9999-12-31")
    if df.empty:
        raise ValueError(f"No data returned for ETF {symbol}")
    return format_csv_output(df, file_path)
