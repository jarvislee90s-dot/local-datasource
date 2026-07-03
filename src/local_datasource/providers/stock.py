"""A 股 / 港股 / 美股行情数据 provider。

通过 akshare 获取日线行情，按日期过滤后统一输出 CSV。
"""
from __future__ import annotations

import re
from datetime import datetime
from typing import Literal

import akshare as ak
import pandas as pd
import requests

from local_datasource.formatters import format_csv_output


Market = Literal["a", "hk", "us"]


def _filter_by_date(df: pd.DataFrame, start_date: str, end_date: str) -> pd.DataFrame:
    """统一把 ``date`` 列转成 ``YYYY-MM-DD`` 字符串后再按日期过滤。"""
    df = df.copy()
    df["date"] = pd.to_datetime(df["date"]).dt.strftime("%Y-%m-%d")
    return df[(df["date"] >= start_date) & (df["date"] <= end_date)].copy()


def _normalize_a_code(ticker: str) -> str:
    """将 A 股代码统一为 akshare 所需的 ``shxxxxxx`` / ``szxxxxxx`` / ``bjxxxxxx`` 格式。"""
    code = re.sub(r"\.(sh|sz|bj)$", "", ticker, flags=re.IGNORECASE)
    if code.startswith(("6", "5", "9")):
        return f"sh{code}"
    if code.startswith(("0", "1", "2", "3")):
        return f"sz{code}"
    if code.startswith(("4", "8", "43")):
        return f"bj{code}"
    return code


def _normalize_hk_code(ticker: str) -> str:
    """将港股代码去掉 ``.hk`` 后缀并补齐为 5 位数字。"""
    return re.sub(r"\.hk$", "", ticker, flags=re.IGNORECASE).zfill(5)


def _normalize_us_code(ticker: str) -> str:
    """将美股代码统一为大写。"""
    return ticker.upper()


def query_stock(
    ticker: str,
    market: Market,
    start_date: str,
    end_date: str,
    file_path: str,
    adjust: str = "qfq",
) -> tuple[str, str]:
    """查询指定市场的股票历史行情并输出 CSV。

    参数:
        ticker: 股票代码
        market: ``a`` / ``hk`` / ``us``
        start_date: 开始日期 ``YYYY-MM-DD``
        end_date: 结束日期 ``YYYY-MM-DD``
        file_path: 输出 CSV 路径
        adjust: 复权方式，``qfq`` / ``hfq`` / ``none``
    """
    # akshare 部分接口需要 ``YYYYMMDD`` 格式的日期字符串
    start_fmt = datetime.strptime(start_date, "%Y-%m-%d").strftime("%Y%m%d")
    end_fmt = datetime.strptime(end_date, "%Y-%m-%d").strftime("%Y%m%d")

    if market == "a":
        symbol = _normalize_a_code(ticker)
        df = ak.stock_zh_a_daily(symbol=symbol, start_date=start_fmt, end_date=end_fmt, adjust=adjust)
    elif market == "hk":
        symbol = _normalize_hk_code(ticker)
        df = ak.stock_hk_daily(symbol=symbol)
        df = _filter_by_date(df, start_date, end_date)
    elif market == "us":
        symbol = _normalize_us_code(ticker)
        df = ak.stock_us_daily(symbol=symbol)
        df = _filter_by_date(df, start_date, end_date)
    else:
        raise ValueError(f"Unsupported market: {market}")

    if df.empty:
        raise ValueError(f"No data returned for {ticker} ({market}) between {start_date} and {end_date}")

    return format_csv_output(df, file_path)


def _resolve_via_sina(keyword: str) -> pd.DataFrame:
    """用新浪 suggest API 按名称反查股票代码(支持简称与全称)。

    新浪返回 GBK 编码,逗号分隔字段:[名称,类型,代码,带前缀代码,简称,...,关联字段]。
    - 类型 11 = 股票;简称搜索时直接命中类型11行
    - 全称搜索时,结果多为持有该股的基金(类型201),但每条关联字段含
      ``sh600519|贵州茅台酒股份有限公司|权重``,从中提取 sh/sz+6位代码去重

    返回 DataFrame(代码,名称),无结果返回空 DataFrame。
    """
    try:
        r = requests.get(
            "https://suggest3.sinajs.cn/suggest/type=",
            params={"key": keyword},
            timeout=10,
            headers={"User-Agent": "Mozilla/5.0"},
        )
        r.encoding = "gbk"
    except Exception:
        return pd.DataFrame(columns=["代码", "名称"])

    m = re.search(r'suggestvalue="(.*)"', r.text, re.S)
    if not m or not m.group(1):
        return pd.DataFrame(columns=["代码", "名称"])

    rows = []
    seen = set()
    for cand in m.group(1).split(";"):
        if not cand:
            continue
        parts = cand.split(",")
        # parts[1]=类型, parts[2]=代码, parts[3]=带前缀代码, parts[4]=简称
        typ = parts[1] if len(parts) > 1 else ""
        prefix_code = parts[3] if len(parts) > 3 else ""
        name = parts[4] if len(parts) > 4 else ""
        # 类型11(股票)直接取
        if typ == "11" and prefix_code and prefix_code not in seen:
            seen.add(prefix_code)
            rows.append({"代码": re.sub(r"^(sh|sz)", "", prefix_code),
                         "名称": name})
        # 全称场景:从最后含 | 的关联字段提取 sh/sz+6位代码
        for field in parts:
            mm = re.search(r"\b(sh|sz)(\d{6})\|", field)
            if mm:
                code = mm.group(2)
                if code not in seen:
                    seen.add(code)
                    rows.append({"代码": code, "名称": name})
    return pd.DataFrame(rows, columns=["代码", "名称"]) if rows else pd.DataFrame(columns=["代码", "名称"])


def resolve_stock_code(keyword: str, file_path: str) -> tuple[str, str]:
    """股票名称(简称或全称)→ 代码候选列表,输出 CSV。

    首选新浪 suggest API(支持全称反查);新浪失败或无结果时降级
    akshare ``stock_zh_a_spot_em()`` 全表按简称 contains 匹配(仅简称有效)。
    - 简称(如"茅台")→ 新浪类型11直接命中
    - 全称(如"贵州茅台酒股份有限公司")→ 新浪从关联字段提取代码
    - 城投/非上市发行人 → 候选为空(不报错)

    多候选时返回全部,Agent/用户从中选,再调 ``query_stock`` 查行情。
    """
    if not keyword:
        raise ValueError("resolve_stock_code requires keyword")

    # 首选新浪
    result = _resolve_via_sina(keyword)
    if result.empty:
        # 降级:akshare 全表按简称 contains
        try:
            df = ak.stock_zh_a_spot_em()
            if not df.empty:
                mask = df["名称"].astype(str).str.contains(keyword, na=False, regex=False)
                result = df[mask][["代码", "名称"]].copy()
        except Exception:
            pass
    return format_csv_output(result, file_path)
