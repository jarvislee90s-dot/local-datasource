"""现货 provider:上金所贵金属现货 + 生意社大宗商品现货(含基差)。

- sge:上海黄金交易所历史行情 ``spot_hist_sge``,深度约 10 年(2016-12 起);
  源列顺序是 date/open/close/low/high(异常),重排为 date,open,high,low,close;
  symbol 必填,须在品种表内(清单由 ``spot_symbol_table_sge`` 给出,17 品种,
  该表为 akshare 内置硬编码,每次调用现取,不做任何缓存)
- sy:生意社大宗现货 ``futures_spot_price_daily``,含现货价/主力合约价/基差;
  该源逐日抓取较慢,起止日期必填且单次区间最长 1 年(超限报错提示缩小范围);
  输出精选 7 列 date/symbol/spot_price/dominant_contract/dominant_contract_price/
  dom_basis/dom_basis_rate
"""
from __future__ import annotations

from datetime import datetime
from typing import Literal

import akshare as ak
import pandas as pd

from local_datasource.formatters import format_csv_output
from local_datasource.providers.common import filter_by_date, require_columns


SpotKind = Literal["sge", "sy"]

# sge:源列顺序 date/open/close/low/high(close 在 low/high 之前,异常)→ 重排输出
_SGE_SOURCE_COLUMNS = ["date", "open", "close", "low", "high"]
_SGE_OUTPUT_COLUMNS = ["date", "open", "high", "low", "close"]

# sy:futures_spot_price_daily 源返回 13 列,精选 7 列输出(保持源内相对顺序)
_SY_OUTPUT_COLUMNS = [
    "date",
    "symbol",
    "spot_price",
    "dominant_contract",
    "dominant_contract_price",
    "dom_basis",
    "dom_basis_rate",
]

# sy 单次请求区间上限:365 天(366 天起报错);源逐日抓取,过慢
_SY_MAX_SPAN_DAYS = 365


def _check_param_scope(kind: str, symbol: str | None, symbols: list[str] | None) -> None:
    """kind 专属参数传错 kind 时显式报错(不静默忽略,对齐 fx.py 的参数守卫)。"""
    if symbol is not None and kind != "sge":
        raise ValueError(f"symbol 仅在 kind=sge 时有效, kind={kind} 不支持")
    if symbols is not None and kind != "sy":
        raise ValueError(f"symbols 仅在 kind=sy 时有效, kind={kind} 不支持")


def _load_sge_symbols() -> list[str]:
    """上金所品种表(akshare 内置硬编码,离线且零开销):每次现取,不做缓存。"""
    table = ak.spot_symbol_table_sge()
    if table is None or table.empty or "品种" not in table.columns:
        raise ValueError("上金所品种表(spot_symbol_table_sge)返回空数据或缺 品种 列,请检查 akshare 版本")
    return table["品种"].astype(str).tolist()


def _query_sge(symbol: str | None, start_date: str | None, end_date: str | None) -> pd.DataFrame:
    """上金所贵金属现货日线:重排为 date/open/high/low/close,可选区间过滤,升序。

    深度约 10 年(2016-12 起);symbol 必填且须在品种表内。
    """
    if not symbol or not str(symbol).strip():
        raise ValueError(
            "kind=sge 需提供 symbol(上金所品种,如 'Au99.99'/'Ag99.99'/'Au(T+D)';"
            "品种清单可由 ak.spot_symbol_table_sge() 获得)"
        )
    symbol = str(symbol).strip()
    valid = _load_sge_symbols()
    if symbol not in valid:
        raise ValueError(
            f"未知上金所品种: {symbol}(有效品种 {len(valid)} 个: {', '.join(valid)})"
        )
    df = ak.spot_hist_sge(symbol=symbol)
    if df is None or df.empty:
        raise ValueError(f"上金所现货(spot_hist_sge, symbol={symbol})返回空数据")
    require_columns(df, _SGE_SOURCE_COLUMNS, "上金所 spot_hist_sge")
    df = filter_by_date(df[_SGE_OUTPUT_COLUMNS], start_date, end_date)
    if df.empty:
        raise ValueError(
            f"上金所现货 {symbol} 在 {start_date or '最早'}~{end_date or '最新'} 区间无数据"
            f"(数据深度约 10 年,自 2016-12 起)"
        )
    return df.sort_values("date", kind="stable").reset_index(drop=True)


def _normalize_sy_symbols(symbols: list[str] | None) -> list[str]:
    """品种代码归一:strip + 大写 + 去重保序(生意社品种代码均为大写,如 CU/RB)。"""
    if isinstance(symbols, str):  # 容错:单个代码误传为字符串
        symbols = [symbols]
    normalized: list[str] = []
    for raw in symbols or []:
        token = str(raw).strip().upper()
        if token and token not in normalized:
            normalized.append(token)
    if not normalized:
        raise ValueError(
            "kind=sy 需提供 symbols(生意社品种代码列表,如 ['CU','RB'])"
        )
    return normalized


def _query_sy(symbols: list[str] | None, start_date: str | None, end_date: str | None) -> pd.DataFrame:
    """生意社大宗现货(含主力合约价与基差):精选 7 列输出,日期升序。

    起止必填;区间 > 365 天(即 1 年)报错提示缩小范围 —— 源按日逐日抓取,
    长区间耗时不可接受,提前拦截而非让用户干等。
    """
    if not start_date or not end_date:
        raise ValueError(
            "kind=sy 需提供 start_date 与 end_date(YYYY-MM-DD;生意社源按日抓取,区间最长 1 年)"
        )
    # pd.Timestamp 对 "20260101"/"2026/01/01" 等宽松解析,而后续过滤是字符串比较,
    # 会静默过滤掉全部行并误报"区间无数据" → 区间检查前先严格校验格式
    for label, value in (("start_date", start_date), ("end_date", end_date)):
        try:
            datetime.strptime(value, "%Y-%m-%d")
        except (TypeError, ValueError):
            raise ValueError(f"{label}({value})日期格式需为 YYYY-MM-DD") from None
    span = (pd.Timestamp(end_date) - pd.Timestamp(start_date)).days
    if span < 0:
        raise ValueError(f"start_date({start_date})不能晚于 end_date({end_date})")
    if span > _SY_MAX_SPAN_DAYS:
        raise ValueError(
            f"kind=sy 的区间过长({span} 天 > 1 年)。生意社源逐日抓取较慢,"
            f"单次最多查询 1 年(365 天),请缩小范围后分次查询"
        )
    symbols = _normalize_sy_symbols(symbols)
    df = ak.futures_spot_price_daily(start_day=start_date, end_day=end_date, vars_list=symbols)
    if df is None or df.empty:
        raise ValueError(
            f"生意社现货(futures_spot_price_daily, symbols={symbols})"
            f"在 {start_date}~{end_date} 返回空数据"
            f"(请确认品种代码与区间;数据自约 2013-06 起,更早区间源端报错,非交易日无数据)"
        )
    require_columns(df, _SY_OUTPUT_COLUMNS, "生意社 futures_spot_price_daily")
    df = filter_by_date(df[_SY_OUTPUT_COLUMNS], start_date, end_date)
    if df.empty:
        raise ValueError(f"生意社现货 {symbols} 在 {start_date}~{end_date} 区间无数据")
    # 源为逐日逐品种行,稳定排序保持同日内品种顺序
    return df.sort_values("date", kind="stable").reset_index(drop=True)


def query_spot(
    kind: SpotKind,
    file_path: str,
    symbol: str | None = None,
    symbols: list[str] | None = None,
    start_date: str | None = None,
    end_date: str | None = None,
) -> tuple[str, str]:
    """查询现货数据(上金所贵金属/生意社大宗含基差)并输出 CSV。

    参数:
        kind: ``sge`` / ``sy``
        symbol: 仅 sge,上金所品种(如 ``Au99.99``/``Ag99.99``/``Au(T+D)``),必填
        symbols: 仅 sy,生意社品种代码列表(如 ``['CU','RB']``),必填
        start_date/end_date: ``YYYY-MM-DD``;sy 必填(区间最长 1 年),sge 可选过滤
    """
    if kind not in ("sge", "sy"):
        raise ValueError(f"Unsupported spot kind: {kind}, use 'sge' or 'sy'")
    _check_param_scope(kind, symbol, symbols)
    if kind == "sge":
        df = _query_sge(symbol, start_date, end_date)
    else:
        df = _query_sy(symbols, start_date, end_date)

    if df.empty:
        raise ValueError(f"No data returned for spot kind={kind}")
    return format_csv_output(df, file_path)
