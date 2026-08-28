"""期权 provider:ETF 期权(上交所)+ 股指期权(中金所 IO/HO/MO),本轮仅日线。

- months:到期月份清单(SSE 官方当日表统一推导 / CFFEX list)
- contracts:当月合约清单(CFFEX 用交易所官方挂牌表;SSE 用上交所官方当日全表,
  akshare 的 option_sse_codes_sina 在 1.18.64 有解析 bug,不依赖)
- hist:单合约日线(SSE 8 位码 / CFFEX io2609C4200 格式)
"""
from __future__ import annotations

import re
from typing import Literal

import akshare as ak
import pandas as pd

from local_datasource.formatters import format_csv_output
from local_datasource.providers.common import filter_by_date, to_compact_date


OptionKind = Literal["months", "contracts", "hist"]

_SSE_UNDERLYINGS = {"50ETF", "300ETF", "500ETF", "科创50ETF"}
_CFFEX_UNDERLYINGS = {"IO", "HO", "MO"}

# 品种 → akshare 函数名(存名字而非函数引用,调用时 getattr 解析,
# 保证测试 monkeypatch options.ak.* 能生效)
_CFFEX_LIST_FUNCS = {
    "IO": "option_cffex_hs300_list_sina",
    "HO": "option_cffex_sz50_list_sina",
    "MO": "option_cffex_zz1000_list_sina",
}
_CFFEX_DAILY_FUNCS = {
    "IO": "option_cffex_hs300_daily_sina",
    "HO": "option_cffex_sz50_daily_sina",
    "MO": "option_cffex_zz1000_daily_sina",
}

# SSE 官方当日表的标的标签(实测为 50ETF(510050)/科创50(588000) 等),
# 按 6 位标的代码锚定过滤,避免名称子串误匹配
_SSE_LABEL_CODES = {
    "50ETF": ("510050",),
    "300ETF": ("510300",),
    "500ETF": ("510500",),
    "科创50ETF": ("588000", "588080"),
}


def _normalize_option_code(symbol: str) -> tuple[str, str]:
    """期权合约代码归一,返回 ``(sina 查询代码, 市场)``。

    - SSE:8 位数字(如 ``10003889``)
    - CFFEX:宽容格式 ``IO2706-P-5600``/``io2609C4200``/``HO 2706 C 5600`` → 紧凑小写
    """
    s = re.sub(r"[\s\-]", "", str(symbol)).lower()
    if re.fullmatch(r"\d{8}", s):
        return s, "sse"
    m = re.fullmatch(r"([a-z]{2})(\d{4})([cp])(\d+)", s)
    if m and m.group(1).upper() in _CFFEX_UNDERLYINGS:
        return s, "cffex"
    raise ValueError(f"Unrecognized option code: {symbol}(示例: 10003889 / IO2706-P-5600 / io2609C4200)")


def _check_underlying(underlying: str | None) -> str:
    u = str(underlying or "").strip().upper()
    if not u:
        raise ValueError("kind=months/contracts 需要 underlying(SSE: 50ETF/300ETF/500ETF/科创50ETF; CFFEX: IO/HO/MO)")
    if u not in _SSE_UNDERLYINGS and u not in _CFFEX_UNDERLYINGS:
        raise ValueError(f"Unrecognized underlying: {u}(SSE: 50ETF/300ETF/500ETF/科创50ETF; CFFEX: IO/HO/MO)")
    return u


def _sse_underlying_rows(underlying: str) -> pd.DataFrame:
    """上交所官方当日全表按 6 位标的代码锚定过滤(months 与 contracts 共用)。"""
    df = ak.option_current_day_sse()
    if "标的券名称及代码" not in df.columns or "到期日" not in df.columns:
        raise ValueError("上交所官方合约表列名不符,请检查 akshare 版本")
    codes = df["标的券名称及代码"].astype(str).str.extract(r"\((\d{6})\)")[0]
    df = df[codes.isin(_SSE_LABEL_CODES[underlying])].copy()
    if df.empty:
        raise ValueError(f"No contracts matched underlying: {underlying}")
    return df


def _query_months(underlying: str) -> pd.DataFrame:
    u = _check_underlying(underlying)
    if u in _SSE_UNDERLYINGS:
        # 官方当日表锚定标的代码取唯一到期月:四个标的统一路径,
        # 不依赖新浪关键字接口(其文档仅声明支持 50ETF/300ETF)
        df = _sse_underlying_rows(u)
        months = sorted(pd.to_datetime(df["到期日"]).dt.strftime("%Y%m").unique())
        return pd.DataFrame({"标的": u, "到期月份": months})
    raw = getattr(ak, _CFFEX_LIST_FUNCS[u])()
    codes = next(iter(raw.values()), [])
    months = sorted({f"20{re.sub(r'^[a-z]+', '', c)}" for c in codes})
    return pd.DataFrame({"标的": u, "到期月份": months})


def _query_contracts(underlying: str, trade_date: str | None) -> pd.DataFrame:
    u = _check_underlying(underlying)
    if u in _SSE_UNDERLYINGS:
        df = _sse_underlying_rows(u)
        near = pd.to_datetime(df["到期日"]).min().strftime("%Y-%m")
        df = df[pd.to_datetime(df["到期日"]).dt.strftime("%Y-%m") == near].copy()
        return df
    # CFFEX:交易所官方挂牌表(期货/期权同表),按品种前缀过滤
    df = ak.futures_contract_info_cffex(date=to_compact_date(trade_date))
    out = df[df["合约代码"].astype(str).str.upper().str.match(rf"^{u}\d")].copy()
    if out.empty:
        raise ValueError(f"No contracts matched underlying: {u}")
    return out


def _query_hist(symbol: str, start_date: str | None, end_date: str | None) -> pd.DataFrame:
    code, market = _normalize_option_code(symbol)
    if market == "sse":
        df = ak.option_sse_daily_sina(symbol=code)
        date_col = "日期"
    else:
        variety = code[:2].upper()
        df = getattr(ak, _CFFEX_DAILY_FUNCS[variety])(symbol=code)
        date_col = "date"
    if df.empty:
        raise ValueError(f"No history for option {symbol}")
    if start_date or end_date:
        return filter_by_date(
            df, start_date or "0001-01-01", end_date or "9999-12-31", date_col=date_col
        )
    return df


def query_options(
    kind: OptionKind,
    file_path: str,
    underlying: str | None = None,
    symbol: str | None = None,
    start_date: str | None = None,
    end_date: str | None = None,
    trade_date: str | None = None,
):
    """查询期权并输出 CSV。

    参数:
        kind: ``months`` / ``contracts`` / ``hist``
        underlying: 标的,months/contracts 必填(SSE: 50ETF/300ETF/500ETF/科创50ETF; CFFEX: IO/HO/MO)
        symbol: 合约代码,hist 必填(SSE 8 位 / CFFEX 如 IO2706-P-5600)
        start_date/end_date: hist 可选,``YYYY-MM-DD``
        trade_date: contracts(CFFEX)可选,``YYYY-MM-DD``,默认今天
    """
    if kind == "months":
        df = _query_months(underlying)
    elif kind == "contracts":
        df = _query_contracts(underlying, trade_date)
    elif kind == "hist":
        if not symbol:
            raise ValueError("kind=hist 需要 symbol(合约代码,可先用 kind=contracts 查清单)")
        df = _query_hist(symbol, start_date, end_date)
    else:
        raise ValueError(f"Unsupported option kind: {kind}")

    if df.empty:
        raise ValueError(f"No data returned for option kind={kind}")
    return format_csv_output(df, file_path)
