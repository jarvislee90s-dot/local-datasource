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
        # 字面匹配(regex=False),避免用户关键字含正则元字符(如银行+)时报错
        mask = df["债券简称"].astype(str).str.contains(keyword, na=False, regex=False) | \
               df["正股简称"].astype(str).str.contains(keyword, na=False, regex=False)
        df = df[mask].copy()
        if df.empty:
            raise ValueError(f"No CB matched keyword: {keyword}")
    return df


def _query_terms() -> pd.DataFrame:
    """可转债条款信息:集思录强赎状态 + 剩余期限/到期税前收益。

    合并 bond_cb_redeem_jsl()(强赎/回售/下修)与 bond_cb_summary()(剩余期限/到期收益)。
    若 bond_cb_summary 不可用则仅返回强赎表。
    """
    redeem = ak.bond_cb_redeem_jsl()
    if redeem is None or redeem.empty:
        raise ValueError("No CB redeem data from jsl")
    try:
        summary = ak.bond_cb_summary()
        if summary is not None and not summary.empty:
            return redeem.merge(summary, on="债券代码", how="left")
    except Exception:
        pass
    return redeem


def _query_history(symbol: str, start_date: str, end_date: str, period: str) -> pd.DataFrame:
    """可转债历史K线。

    period=daily → bond_zh_hs_cov_daily(日K)
    period=min  → bond_zh_hs_cov_min(分钟K)
    """
    code = _normalize_cb_code(symbol)
    if period == "daily":
        df = ak.bond_zh_hs_cov_daily(symbol=code)
        if df.empty:
            raise ValueError(f"No daily history for {symbol}")
        df = df.copy()
        df["date"] = pd.to_datetime(df["date"]).dt.strftime("%Y-%m-%d")
        return df[(df["date"] >= start_date) & (df["date"] <= end_date)].copy()
    elif period == "min":
        df = ak.bond_zh_hs_cov_min(symbol=code)
        if df.empty:
            raise ValueError(f"No minute history for {symbol}")
        return df
    else:
        raise ValueError(f"Unsupported period: {period}, use 'daily' or 'min'")


def _resolve_stock_code_from_cb(bond_code: str) -> tuple[str, str] | None:
    """从可转债代码解析出正股代码与发行人名称。

    通过 bond_zh_cov() 全表过滤出对应正股代码。
    返回 (正股代码, 发行人名称) 或 None(非上市发行人/未找到)。

    注意:bond_code 若不是转债代码(如企业债/城投债 2180495.IB),
    归一化会失败,此时返回 None 走非上市引导提示,不抛异常。
    """
    try:
        code = _normalize_cb_code(bond_code)
    except ValueError:
        # 非转债代码(如企业债/银行间债)无法解析正股 → 视为非上市发行人
        return None
    plain_code = re.sub(r"^(sh|sz)", "", code)
    df = ak.bond_zh_cov()
    if df.empty:
        return None
    row = df[df["债券代码"].astype(str) == plain_code]
    if row.empty:
        return None
    stock_code = str(row.iloc[0]["正股代码"])
    issuer_name = str(row.iloc[0]["正股简称"])
    if stock_code.startswith("6"):
        stock_code = f"sh{stock_code}"
    else:
        stock_code = f"sz{stock_code}"
    return stock_code, issuer_name


def _build_nonlisted_hint(issuer_name: str) -> pd.DataFrame:
    """构造非上市发行人财务缺口的引导性提示 DataFrame(不报错)。"""
    return pd.DataFrame([{
        "提示": f"发行人 {issuer_name} 为非上市主体,免费层无财务数据,建议查 Wind/企业预警通",
    }])


def _query_issuer_finance(
    bond_code: str | None,
    stock_code: str | None,
    report_type: str,
) -> pd.DataFrame:
    """发行人财务三大报表。

    - stock_code 给定 → 直接查该正股
    - bond_code 给定 → 先解析正股代码,再查;解析失败(城投/非上市)→ 返回引导性提示
    """
    if stock_code:
        sc = stock_code.lower()
        if not re.match(r"^(sh|sz)\d+$", sc):
            if sc.isdigit() and len(sc) == 6:
                sc = f"sh{sc}" if sc.startswith("6") else f"sz{sc}"
            else:
                raise ValueError(f"Invalid stock_code: {stock_code}")
        df = ak.stock_financial_report_sina(stock=sc, symbol=report_type)
        if df.empty:
            raise ValueError(f"No financial data for stock {stock_code}")
        return df
    resolved = _resolve_stock_code_from_cb(bond_code)
    if resolved is None:
        return _build_nonlisted_hint(bond_code or "未知发行人")
    stock_code_resolved, issuer_name = resolved
    df = ak.stock_financial_report_sina(stock=stock_code_resolved, symbol=report_type)
    if df.empty:
        return _build_nonlisted_hint(issuer_name)
    return df


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
