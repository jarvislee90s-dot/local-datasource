"""国内指数 provider:沪深指数(新浪日线 2014 起)+ 中证系列(官网日线)+ 分钟(腾讯)。

中证系列(930xxx/950xxx)新浪源不可用(实测),走中证官网源,拉取较慢(约 10 秒);
官网源无分钟数据,请求 period=min 直接报错说明。
"""
from __future__ import annotations

import re
from datetime import datetime
from typing import Literal

import akshare as ak

from local_datasource.formatters import format_csv_output
from local_datasource.providers.common import (
    fetch_tencent_minute,
    filter_by_date,
    require_minute_range,
    to_compact_date,
    validate_period,
)


IndexPeriod = Literal["daily", "min"]


def _normalize_index_code(symbol: str) -> tuple[str, str]:
    """指数代码归一,返回 ``(查询代码, 系列)``。

    - ``000xxx`` → ``sh000xxx``(新浪);``399xxx`` → ``sz399xxx``(新浪)
    - ``93xxxx``/``95xxxx`` 中证系列 → 纯 6 位(中证官网),已带 sh/sz 前缀也归到官网
    """
    s = re.sub(r"\.(sh|sz|csi)$", "", str(symbol).strip().lower(), flags=re.IGNORECASE)
    m = re.fullmatch(r"(sh|sz)(\d{6})", s)
    digits = m.group(2) if m else s
    if re.fullmatch(r"9[35]\d{4}", digits):
        return digits, "csindex"
    if m:
        if not (digits.startswith("000") or digits.startswith("399")):
            raise ValueError(f"Unrecognized index code: {symbol}(示例: 000852 / 930050 / sh000300)")
        return s, "sina"
    if re.fullmatch(r"000\d{3}", digits):
        return f"sh{digits}", "sina"
    if re.fullmatch(r"399\d{3}", digits):
        return f"sz{digits}", "sina"
    raise ValueError(f"Unrecognized index code: {symbol}(示例: 000852 / 930050 / sh000300)")


def query_index(
    symbol: str,
    file_path: str,
    period: IndexPeriod = "daily",
    freq: str = "1",
    start_date: str | None = None,
    end_date: str | None = None,
):
    """查询国内指数并输出 CSV。

    参数:
        symbol: 指数代码,如 ``000852``/``sh000300``/``930050``
        period: ``daily`` 默认 / ``min``(沪深指数,腾讯源约 8 个交易日)
        freq: 分钟粒度 1/5/15/30/60,默认 1
        start_date/end_date: ``YYYY-MM-DD``(min 必填)
    """
    code, series = _normalize_index_code(symbol)
    validate_period(period)

    if period == "min":
        if series == "csindex":
            raise ValueError("中证系列官网源无分钟数据,仅支持日线;沪深指数(000/399 开头)支持分钟")
        require_minute_range(start_date, end_date)
        df = fetch_tencent_minute(code, freq, start_date, end_date)
        return format_csv_output(df, file_path)

    if series == "sina":
        df = ak.stock_zh_index_daily(symbol=code)
        if df.empty:
            raise ValueError(f"No daily data for index {symbol}")
        df = filter_by_date(df, start_date, end_date)
    else:  # csindex,慢源(约 10 秒)
        start = to_compact_date(start_date) if start_date else "19900101"
        end = to_compact_date(end_date) if end_date else datetime.now().strftime("%Y%m%d")
        df = ak.stock_zh_index_hist_csindex(symbol=code, start_date=start, end_date=end)
        if df.empty:
            raise ValueError(f"No daily data for index {symbol}")

    if df.empty:
        raise ValueError(f"No data returned for index {symbol}")
    return format_csv_output(df, file_path)
