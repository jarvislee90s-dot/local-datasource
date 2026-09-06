"""provider 共享工具:日期过滤、上游列守卫、分钟深度守卫、腾讯分钟通用路径。

分钟深度守卫是本仓库的明确设计决策(spec 2026-08-28 第三节):
请求区间早于数据源实际覆盖时报错并给补数指引,绝不静默返回残缺数据;
覆盖深度按返回数据的实际最早时间戳动态判定,不写死天数。
"""
from __future__ import annotations

from datetime import datetime

import akshare as ak
import pandas as pd
import yfinance as yf


class CoverageError(ValueError):
    """分钟深度不足:请求区间早于数据源实际覆盖。

    独立类型便于消费方(如 quant-chart)精确捕获并触发自己的补数流程;
    继承 ValueError,存量 ``except ValueError`` 行为不变。
    message 固定含覆盖区间(``YYYY-MM-DD``)与"补数"指引。
    """


def require_columns(
    df: pd.DataFrame, expected_columns: list[str], subject: str,
    hint: str = "请检查 akshare 版本",
) -> None:
    """上游列漂移守卫:缺列时报可读错误(缺失列 + 数据源 + 版本指引)。"""
    missing = [c for c in expected_columns if c not in df.columns]
    if missing:
        raise ValueError(f"{subject} 列名不受支持(缺 {missing}),{hint}")


def filter_by_date(
    df: pd.DataFrame,
    start_date: str | None = None,
    end_date: str | None = None,
    date_col: str = "date",
) -> pd.DataFrame:
    """把日期列统一为 ``YYYY-MM-DD`` 字符串后按闭区间过滤;边界为 None 表示该侧不设限。"""
    if df.empty or date_col not in df.columns:
        return df.iloc[0:0]
    df = df.copy()
    df[date_col] = pd.to_datetime(df[date_col]).dt.strftime("%Y-%m-%d")
    start = start_date or "0001-01-01"
    end = end_date or "9999-12-31"
    return df[(df[date_col] >= start) & (df[date_col] <= end)]


def filter_by_datetime(
    df: pd.DataFrame,
    start_date: str | None = None,
    end_date: str | None = None,
    dt_col: str = "datetime",
) -> pd.DataFrame:
    """把 datetime 列(``YYYY-MM-DD HH:MM:SS``)取日期部分后按闭区间过滤;None 表示不设限。"""
    if df.empty or dt_col not in df.columns:
        return df.iloc[0:0]
    df = df.copy()
    day = pd.to_datetime(df[dt_col]).dt.strftime("%Y-%m-%d")
    start = start_date or "0001-01-01"
    end = end_date or "9999-12-31"
    return df[(day >= start) & (day <= end)]


def validate_period(period: str) -> None:
    """统一校验 period 枚举,非法值报错而非静默按 daily。"""
    if period not in ("daily", "min"):
        raise ValueError(f"Unsupported period: {period}, use 'daily' or 'min'")


def check_kind_params(kind: str, *specs: tuple[str, object, str]) -> None:
    """kind 专属参数守卫:specs 形如 ``(参数名, 值, 允许的 kind)``。

    专属参数传到其他 kind 时显式报错(不静默忽略),报错文案在
    fx/spot/global_rates 三个聚合工具间保持统一。
    """
    for name, value, allowed in specs:
        if value is not None and kind != allowed:
            raise ValueError(f"{name} 仅在 kind={allowed} 时有效, kind={kind} 不支持")


def require_minute_range(start_date: str | None, end_date: str | None) -> None:
    """分钟模式必须提供起止日期(深度有限,用于覆盖校验)。"""
    if not start_date or not end_date:
        raise ValueError("period=min 需提供 start_date 与 end_date(分钟深度有限,用于覆盖校验)")


def guard_minute_depth(df: pd.DataFrame, start_date: str, dt_col: str = "datetime", source: str = "腾讯") -> None:
    """分钟深度守卫:请求起点早于数据实际最早时间戳时报错。

    空表不在此报错,由上层统一抛 No data。
    """
    if df.empty:
        return
    times = pd.to_datetime(df[dt_col])
    earliest = times.min().strftime("%Y-%m-%d")
    latest = times.max().strftime("%Y-%m-%d")
    if start_date < earliest:
        raise CoverageError(
            f"分钟数据仅覆盖 {earliest} 至 {latest}(源: {source}),"
            f"更早区间请从 Wind/终端导出 Excel 提供补数"
        )


def to_compact_date(date_str: str | None, default_today: bool = True) -> str:
    """``YYYY-MM-DD`` → ``YYYYMMDD``;缺省取今天。"""
    if not date_str:
        if default_today:
            return datetime.now().strftime("%Y%m%d")
        raise ValueError("date required")
    return datetime.strptime(date_str, "%Y-%m-%d").strftime("%Y%m%d")


def fetch_tencent_minute(symbol: str, freq: str, start_date: str, end_date: str) -> pd.DataFrame:
    """腾讯分钟通用路径(个股/指数/ETF 共用):拉取→列名归一→守卫→区间过滤。

    返回 DataFrame 含 ``datetime`` 列;过滤后为空时抛 ValueError。
    """
    df = ak.stock_zh_a_minute(symbol=symbol, period=freq, adjust="")
    df = df.rename(columns={"day": "datetime"})
    guard_minute_depth(df, start_date, source="腾讯")
    df = filter_by_datetime(df, start_date, end_date)
    if df.empty:
        raise ValueError(f"No minute data for {symbol} between {start_date} and {end_date}")
    return df


def fetch_yahoo_daily(
    ticker: str,
    start_date: str | None,
    end_date: str | None,
    columns: list[str],
) -> pd.DataFrame:
    """Yahoo Finance 日线通用路径(美元指数回退源/离岸与交叉盘共用)。

    yfinance 的 ``end`` 为排他区间,repo 契约是闭区间 → 补一天,再由
    ``filter_by_date`` 截齐;start/end 缺任一时取 ``period="max"``。
    Yahoo 异常,以及被拒/限流时 yfinance 不抛异常而返回空表的情形,
    统一报含"不可达"的网络指引并保留异常链。
    """
    kwargs: dict = {"progress": False}
    if start_date and end_date:
        kwargs["start"] = start_date
        kwargs["end"] = (pd.Timestamp(end_date) + pd.Timedelta(days=1)).strftime("%Y-%m-%d")
    else:
        kwargs["period"] = "max"
    try:
        df = yf.download(ticker, **kwargs)
    except Exception as e:  # noqa: BLE001 - Yahoo 限流/断网时异常类型不定,统一报网络指引
        raise ValueError(
            f"Yahoo Finance({ticker})请求失败: {e}。该源在当前网络不可达,请检查网络/代理后重试"
        ) from e
    if df is None or df.empty:
        raise ValueError(
            f"Yahoo Finance({ticker})返回空数据。该源在当前网络不可达(或代码无数据),"
            f"请检查网络/代理后重试"
        )
    if isinstance(df.columns, pd.MultiIndex):  # 单标的下载也会带 ticker 层,取价格层
        df.columns = df.columns.get_level_values(0)
    df = df.reset_index()
    df.columns = [str(c).lower() for c in df.columns]
    require_columns(df, columns, f"yfinance {ticker}", hint="请检查 yfinance 版本")
    return df[columns]