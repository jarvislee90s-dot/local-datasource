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


def _query_yield_curve(start_date: str, end_date: str) -> pd.DataFrame:
    """国债到期收益率曲线(bond_china_yield)。"""
    start_fmt = datetime.strptime(start_date, "%Y-%m-%d").strftime("%Y%m%d")
    end_fmt = datetime.strptime(end_date, "%Y-%m-%d").strftime("%Y%m%d")
    df = ak.bond_china_yield(start_date=start_fmt, end_date=end_fmt)
    if df.empty:
        raise ValueError(f"No yield curve data between {start_date} and {end_date}")
    return df


def _query_issue_info(bond_code: str) -> pd.DataFrame:
    """信用债发行信息(bond_info_cm),精确过滤排除子串误匹配。

    实测 bond_info_cm(bond_code='2180495') 会返回 2 条:
      - 21徐州新盛03 / 2180495(目标)
      - 21赣州银行CD111 / 112180495(子串误命中)
    必须精确匹配 df['债券代码']==code 后再返回。
    """
    code = _normalize_bond_code(bond_code)
    df = ak.bond_info_cm(bond_code=code)
    if df.empty:
        raise ValueError(f"No bond found for code: {bond_code}")
    df = df[df["债券代码"].astype(str) == code].copy()
    if df.empty:
        raise ValueError(f"No exact match for bond code: {bond_code}")
    return df


def _query_credit_daily(symbol: str, start_date: str, end_date: str) -> pd.DataFrame:
    raise NotImplementedError("credit_daily implemented in Task 4")


def query_bond(
    kind: BondKind,
    file_path: str,
    start_date: str | None = None,
    end_date: str | None = None,
    bond_code: str | None = None,
    symbol: str | None = None,
) -> tuple[str, str]:
    """查询中国境内债券数据并输出 CSV。"""
    if kind == "yield_curve":
        if not start_date or not end_date:
            raise ValueError("yield_curve requires start_date and end_date")
        df = _query_yield_curve(start_date, end_date)
    elif kind == "issue_info":
        if not bond_code:
            raise ValueError("issue_info requires bond_code")
        df = _query_issue_info(bond_code)
    elif kind == "credit_daily":
        if not symbol or not start_date or not end_date:
            raise ValueError("credit_daily requires symbol, start_date, end_date")
        df = _query_credit_daily(symbol, start_date, end_date)
    else:
        raise ValueError(f"Unsupported bond kind: {kind}")

    if df.empty:
        raise ValueError(f"No data returned for bond kind={kind}")

    return format_csv_output(df, file_path)
