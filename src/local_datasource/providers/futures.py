"""国内期货 provider:单合约/主连行情 + 合约清单。

- hist·daily:单合约全历史(新浪,自上市含持仓量);主连约 158 日(新浪)
- hist·min:新浪源,约 4 个交易日,超覆盖按守卫报错
- contracts:交易所官方挂牌表(CFFEX/CZCE/SHFE/INE/DCE/GFEX),按品种前缀过滤

按需拉取,统一输出 CSV。
"""
from __future__ import annotations

import re
from datetime import datetime
from typing import Literal

import akshare as ak
import pandas as pd

from local_datasource.formatters import format_csv_output
from local_datasource.providers.common import (
    filter_by_date,
    filter_by_datetime,
    guard_minute_depth,
    to_compact_date,
)


FuturesKind = Literal["hist", "contracts"]
FuturesPeriod = Literal["daily", "min"]

# 品种前缀 → 交易所(kind=contracts 路由)。未收录品种报错提示补充映射。
_VARIETY_EXCHANGE: dict[str, list[str]] = {
    "CFFEX": ["IF", "IH", "IC", "IM", "TS", "TF", "T", "TL", "IO", "HO", "MO"],
    "SHFE": ["CU", "AL", "ZN", "PB", "NI", "SN", "AU", "AG", "RB", "WR", "FU", "BU",
             "RU", "SP", "SS", "AO", "BC", "LU", "BR", "HC"],
    "DCE": ["A", "B", "M", "Y", "P", "C", "CS", "JD", "L", "V", "PP", "J", "JM", "I",
            "EG", "EB", "PG", "RR", "LH"],
    "CZCE": ["WH", "PM", "RI", "RS", "JR", "LR", "OI", "RM", "CF", "CY", "SR", "TA",
             "MA", "FG", "SA", "UR", "PF", "SH", "PX",
             "AP", "CJ", "PK", "PL", "PR", "SF", "SM", "ZC"],
    "INE": ["SC", "NR", "EC"],
    "GFEX": ["SI", "LC", "PS"],
}

_CONTRACT_INFO_APIS: dict[str, callable] = {
    "CFFEX": lambda d: ak.futures_contract_info_cffex(date=d),
    "CZCE": lambda d: ak.futures_contract_info_czce(date=d),
    "SHFE": lambda d: ak.futures_contract_info_shfe(date=d),
    "INE": lambda d: ak.futures_contract_info_ine(date=d),
    "DCE": lambda d: ak.futures_contract_info_dce(),
    "GFEX": lambda d: ak.futures_contract_info_gfex(),
}


def _normalize_futures_code(symbol: str) -> str:
    """合约/主连代码归一:大写、去空格与连字符;``IM主连``/``im0`` → ``IM0``。"""
    s = re.sub(r"[\s\-]", "", str(symbol)).upper()
    m = re.fullmatch(r"([A-Z]{1,2})(主连|0)", s)
    if m:
        return m.group(1) + "0"
    if re.fullmatch(r"[A-Z]{1,2}\d{3,4}", s):
        return s
    raise ValueError(f"Unrecognized futures code: {symbol}(示例: IM2612 / IM0)")


def _exchange_of_variety(variety: str) -> str:
    for exch, varieties in _VARIETY_EXCHANGE.items():
        if variety.upper() in varieties:
            return exch
    raise ValueError(f"未识别品种: {variety}。已支持品种见 provider 映射表,可在 issue 中补充")


def _query_hist_daily(code: str, start_date: str | None, end_date: str | None) -> pd.DataFrame:
    """日线:``IM0`` 走主连接口(约 158 日),其余走单合约全历史。"""
    if re.fullmatch(r"[A-Z]{1,2}0", code):
        df = ak.futures_main_sina(
            symbol=code,
            start_date=to_compact_date(start_date) if start_date else "19900101",
            end_date=to_compact_date(end_date) if end_date else datetime.now().strftime("%Y%m%d"),
        )
        date_col = "日期"
    else:
        df = ak.futures_zh_daily_sina(symbol=code)
        date_col = "date"
    if df.empty:
        raise ValueError(f"No daily data for futures {code}")
    if start_date or end_date:
        return filter_by_date(
            df, start_date or "0001-01-01", end_date or "9999-12-31", date_col=date_col
        )
    return df


def _query_hist_minute(code: str, freq: str, start_date: str, end_date: str) -> pd.DataFrame:
    """分钟:新浪源约 4 个交易日,超覆盖由守卫报错(不静默降级)。"""
    df = ak.futures_zh_minute_sina(symbol=code, period=freq)
    guard_minute_depth(df, start_date, source="新浪")
    df = filter_by_datetime(df, start_date, end_date)
    if df.empty:
        raise ValueError(f"No minute data for futures {code} between {start_date} and {end_date}")
    return df


def _query_contracts(variety: str, trade_date: str | None) -> pd.DataFrame:
    """交易所官方挂牌表按品种前缀过滤;列名随 akshare 版本可能有差异,做候选列匹配。"""
    exch = _exchange_of_variety(variety)
    df = _CONTRACT_INFO_APIS[exch](to_compact_date(trade_date))
    code_col = next((c for c in ("合约代码", "代码", "symbol") if c in df.columns), None)
    if code_col is None:
        raise ValueError("该交易所合约清单列名不受支持,请检查 akshare 版本")
    out = df[df[code_col].astype(str).str.upper().str.match(rf"^{re.escape(variety.upper())}\d")].copy()
    if out.empty:
        raise ValueError(f"No contracts matched variety: {variety}")
    return out


def query_futures(
    symbol: str,
    file_path: str,
    kind: FuturesKind = "hist",
    period: FuturesPeriod = "daily",
    freq: str = "1",
    start_date: str | None = None,
    end_date: str | None = None,
    trade_date: str | None = None,
) -> tuple[str, str]:
    """查询国内期货并输出 CSV。

    参数:
        symbol: 合约(IM2612)/主连(IM0)/品种(IM, kind=contracts)
        kind: ``hist`` 默认 / ``contracts``
        period: ``daily`` 默认 / ``min``(需 start_date+end_date)
        freq: 分钟粒度 1/5/15/30/60,默认 1
        start_date/end_date: ``YYYY-MM-DD``
        trade_date: contracts 用,``YYYY-MM-DD``,默认今天
    """
    if kind == "contracts":
        variety = re.match(r"^[A-Za-z]+", str(symbol).strip())
        if not variety:
            raise ValueError(f"kind=contracts 需要品种代码(如 IM/RB),got: {symbol}")
        df = _query_contracts(variety.group(0), trade_date)
    elif kind == "hist":
        code = _normalize_futures_code(symbol)
        if period == "daily":
            df = _query_hist_daily(code, start_date, end_date)
        elif period == "min":
            if not start_date or not end_date:
                raise ValueError("period=min 需提供 start_date 与 end_date(分钟深度有限,用于覆盖校验)")
            df = _query_hist_minute(code, freq, start_date, end_date)
        else:
            raise ValueError(f"Unsupported period: {period}, use 'daily' or 'min'")
    else:
        raise ValueError(f"Unsupported futures kind: {kind}, use 'hist' or 'contracts'")

    if df.empty:
        raise ValueError(f"No data returned for futures kind={kind}")
    return format_csv_output(df, file_path)
