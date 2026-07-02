"""可转债数据 provider。

通过 akshare 获取可转债一览、条款、历史K线与发行人财务,统一输出 CSV。
"""
from __future__ import annotations

import re
from typing import Literal

import akshare as ak
import pandas as pd

from local_datasource.formatters import format_csv_output


CbKind = Literal["overview", "terms", "history", "issuer_finance"]
ReportType = Literal["资产负债表", "利润表", "现金流量表"]


def _normalize_cb_code(code: str) -> str:
    """将可转债代码归一为 akshare 所需的 ``shxxxxxx`` / ``szxxxxxx`` 格式。

    转债代码首位决定市场:
    - 11 开头(如 113682)→ 沪市 sh
    - 12 开头(如 128039)→ 深市 sz
    """
    stripped = re.sub(r"\.(SH|SZ|sh|sz)$", "", code)
    # 已带前缀
    if re.match(r"^(sh|sz)\d+$", stripped, re.IGNORECASE):
        return stripped.lower()
    # 纯数字 → 按首位补前缀
    if stripped.isdigit() and len(stripped) == 6:
        if stripped.startswith("11"):
            return f"sh{stripped}"
        if stripped.startswith("12"):
            return f"sz{stripped}"
        raise ValueError(f"Unrecognized CB code prefix: {code}")
    raise ValueError(f"Invalid CB code: {code}")


def _query_overview(keyword: str | None = None) -> pd.DataFrame:
    """可转债一览(bond_zh_cov),含转股溢价率/评级/规模。可选关键字过滤。"""
    df = ak.bond_zh_cov()
    if df.empty:
        raise ValueError("No convertible bond overview data")
    if keyword:
        mask = df["债券简称"].astype(str).str.contains(keyword, na=False) | \
               df["正股简称"].astype(str).str.contains(keyword, na=False)
        df = df[mask].copy()
        if df.empty:
            raise ValueError(f"No CB matched keyword: {keyword}")
    return df


def _query_terms() -> pd.DataFrame:
    raise NotImplementedError("terms implemented in Task 8")


def _query_history(symbol: str, start_date: str, end_date: str, period: str) -> pd.DataFrame:
    raise NotImplementedError("history implemented in Task 9")


def _query_issuer_finance(bond_code: str | None, stock_code: str | None, report_type: str) -> pd.DataFrame:
    raise NotImplementedError("issuer_finance implemented in Task 10")


def query_convertible_bond(
    kind: CbKind,
    file_path: str,
    symbol: str | None = None,
    start_date: str | None = None,
    end_date: str | None = None,
    period: str = "daily",
    bond_code: str | None = None,
    stock_code: str | None = None,
    report_type: ReportType = "资产负债表",
    keyword: str | None = None,
) -> tuple[str, str]:
    """查询可转债数据并输出 CSV。"""
    if kind == "overview":
        df = _query_overview(keyword=keyword)
    elif kind == "terms":
        df = _query_terms()
    elif kind == "history":
        if not symbol or not start_date or not end_date:
            raise ValueError("history requires symbol, start_date, end_date")
        df = _query_history(symbol, start_date, end_date, period)
    elif kind == "issuer_finance":
        if not bond_code and not stock_code:
            raise ValueError("issuer_finance requires bond_code or stock_code")
        df = _query_issuer_finance(bond_code, stock_code, report_type)
    else:
        raise ValueError(f"Unsupported CB kind: {kind}")

    if df.empty:
        raise ValueError(f"No data returned for CB kind={kind}")

    return format_csv_output(df, file_path)
