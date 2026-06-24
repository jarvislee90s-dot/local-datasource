"""Yahoo Finance 风格的美股/全球资产数据 provider。

默认使用 akshare 的美股日线接口（免 key、在当前网络更稳定）；
设置 ``use_yfinance=True`` 可回退到 yfinance。
"""
from __future__ import annotations

from datetime import datetime, timedelta
from typing import Literal

import akshare as ak
import pandas as pd
import yfinance as yf

from local_datasource.formatters import format_csv_output


Period = Literal["1d", "5d", "1mo", "3mo", "6mo", "1y", "2y", "5y", "10y", "max"]

# period 到近似天数的映射，用于 akshare 默认路径的日期过滤
_PERIOD_DAYS = {
    "1d": 1,
    "5d": 5,
    "1mo": 30,
    "3mo": 90,
    "6mo": 180,
    "1y": 365,
    "2y": 730,
    "5y": 1825,
    "10y": 3650,
    "max": 36500,
}


def _period_to_dates(period: Period, end_date: datetime | None = None) -> tuple[str, str]:
    """将 period 转换为 ``(start_date, end_date)`` 日期字符串。"""
    end = end_date or datetime.now()
    days = _PERIOD_DAYS.get(period, 365)
    start = end - timedelta(days=days)
    return start.strftime("%Y-%m-%d"), end.strftime("%Y-%m-%d")


def _query_akshare(ticker: str, start_date: str, end_date: str) -> pd.DataFrame:
    """通过 akshare 获取美股日线数据并按日期过滤。"""
    df = ak.stock_us_daily(symbol=ticker.upper())
    df = df[(df["date"] >= start_date) & (df["date"] <= end_date)].copy()
    if df.empty:
        raise ValueError(f"No akshare data for {ticker}")
    return df


def _query_yfinance(ticker: str, period: Period, start_date: str | None, end_date: str | None) -> pd.DataFrame:
    """通过 yfinance 下载数据。"""
    kwargs: dict = {"progress": False}
    if start_date and end_date:
        kwargs["start"] = start_date
        kwargs["end"] = end_date
    else:
        kwargs["period"] = period

    df = yf.download(ticker.upper(), **kwargs)
    if df.empty:
        raise ValueError(f"No yfinance data for {ticker}")

    # 某些版本的 yfinance 返回多层列索引，需要展平
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = [" ".join(col).strip() for col in df.columns.values]

    df = df.reset_index()
    return df


def query_yfinance(
    ticker: str,
    period: Period = "1y",
    file_path: str = "",
    start_date: str | None = None,
    end_date: str | None = None,
    use_yfinance: bool = False,
) -> tuple[str, str]:
    """查询美股/全球资产历史价格并输出 CSV。

    参数:
        ticker: 资产代码
        period: 时间跨度
        file_path: 输出 CSV 路径
        start_date / end_date: 可选的显式日期范围
        use_yfinance: 是否使用 yfinance，默认 False（使用 akshare）
    """
    if start_date and end_date:
        s, e = start_date, end_date
    else:
        s, e = _period_to_dates(period)

    if use_yfinance:
        df = _query_yfinance(ticker, period, start_date, end_date)
    else:
        try:
            df = _query_akshare(ticker, s, e)
        except Exception as ex:
            raise RuntimeError(f"akshare failed for {ticker}: {ex}. Try use_yfinance=True or check the ticker.") from ex

    return format_csv_output(df, file_path)
