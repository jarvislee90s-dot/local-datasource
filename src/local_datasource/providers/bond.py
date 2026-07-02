"""中国境内债券(标债)数据 provider。

通过 akshare 获取国债收益率曲线、信用债发行信息与交易所行情,统一输出 CSV。

已知限制(akshare 免费层):
- 中债估值 YTM / 全价:无(Wind/中债登付费)
- 标债赎回回售条款详情 / 票息 / 到期日 / 剩余期限:无(在募集说明书里)
- bond_info_detail_cm 接口有上游 bug,本期不调用
"""
from __future__ import annotations

import re
from datetime import datetime
from typing import Literal

import akshare as ak
import pandas as pd

from local_datasource.formatters import format_csv_output


BondKind = Literal["yield_curve", "issue_info", "credit_daily"]


def _normalize_bond_code(code: str) -> str:
    """将债券代码归一为 akshare 所需格式。"""
    stripped = re.sub(r"\.(IB|SH|SZ|sh|sz|ib)$", "", code)
    if stripped.isdigit():
        return stripped
    if re.match(r"^(sh|sz|bj)\d+$", stripped, re.IGNORECASE):
        return stripped.lower()
    raise ValueError(f"Invalid bond code: {code}")


def query_bond(*args, **kwargs) -> tuple[str, str]:
    """查询中国境内债券数据并输出 CSV(将在 Task 2 中实现)。"""
    raise NotImplementedError("query_bond implemented in Task 2")
