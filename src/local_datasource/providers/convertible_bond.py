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


def query_convertible_bond(kind: CbKind, file_path: str, **kwargs) -> tuple[str, str]:
    """查询可转债数据并输出 CSV。(桩,后续 Task 填充)"""
    raise NotImplementedError("query_convertible_bond implemented in later tasks")
