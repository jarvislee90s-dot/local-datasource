"""外汇 provider:人民币中间价 + 中行牌价 + 离岸 USDCNH + 交叉盘。

- mid:央行中间价 ``currency_boc_safe`` 全表(1994-01-01 起,25 币种),
  值保持"100 外币 = X 人民币"官方口径原样不换算;``currency`` 传逗号分隔
  币种代码(如 ``usd,eur``)时只输出指定列
- bochina:新浪中行人民币牌价 ``currency_boc_sina``,数据约 2012 年起,
  长区间分页拉取较慢;``symbol`` 为币种中文名(如 ``美元``/``港币``),
  起止日期必填(akshare 缺省值是任取的示例区间,静默透传会拿到错数据)
- usdcnh / cross:Yahoo Finance 日线收盘价(``USDCNH=X`` / ``<PAIR>=X``);
  yfinance 的 end 为排他区间 → 补一天再由闭区间过滤截齐;
  Yahoo 不可达时报含"不可达"的网络指引
"""
from __future__ import annotations

import re
from typing import Literal

import akshare as ak
import pandas as pd
import yfinance as yf

from local_datasource.formatters import format_csv_output
from local_datasource.providers.common import filter_by_date, to_compact_date


FxKind = Literal["mid", "bochina", "usdcnh", "cross"]

# mid:央行中间价中文币种列 → 小写 ISO 代码(值保持"100 外币"口径原样)
_BOC_SAFE_COLUMNS = {
    "美元": "usd", "欧元": "eur", "日元": "jpy", "港元": "hkd", "英镑": "gbp",
    "澳元": "aud", "新西兰元": "nzd", "新加坡元": "sgd", "瑞士法郎": "chf",
    "加元": "cad", "澳门元": "mop", "林吉特": "myr", "卢布": "rub", "兰特": "zar",
    "韩元": "krw", "迪拉姆": "aed", "里亚尔": "sar", "福林": "huf", "兹罗提": "pln",
    "丹麦克朗": "dkk", "瑞典克朗": "sek", "挪威克朗": "nok", "里拉": "try",
    "比索": "mxn", "泰铢": "thb",
}

# bochina:新浪中行牌价中文列 → 输出列(注意新浪侧币种叫"港币"非"港元")
_BOC_SINA_COLUMNS = {
    "日期": "date",
    "中行汇买价": "buy",
    "中行钞买价": "cash_buy",
    "中行钞卖价/汇卖价": "sell",
    "央行中间价": "mid",
    "中行折算价": "boc_ref",
}

_USDCNH_TICKER = "USDCNH=X"

_MID_UNIT_LINE = "单位：100 外币 = X 人民币（官方中间价口径）"


def _require_columns(df: pd.DataFrame, required: list[str], source: str,
                     hint: str = "请检查 akshare 版本") -> None:
    """上游列漂移守卫:缺列时报可读错误(对齐 global_rates.py 的版本指引文案)。"""
    missing = [c for c in required if c not in df.columns]
    if missing:
        raise ValueError(f"{source} 列名不受支持(缺 {missing}),{hint}")


def _select_mid_currencies(currency: str | None) -> list[str]:
    """解析 mid 的 ``currency`` 过滤(如 ``usd,eur``,逗号/空格分隔,大小写不敏感)。

    返回中文列名列表(保持用户书写顺序,去重);缺省返回全部 25 币种;
    未知代码报可读错误并列出有效代码。
    """
    if not currency or not currency.strip():
        return list(_BOC_SAFE_COLUMNS)
    code_to_cn = {code: cn for cn, code in _BOC_SAFE_COLUMNS.items()}
    codes: list[str] = []
    for token in re.split(r"[,\s;，、]+", currency.strip()):
        code = token.strip().lower()
        if not code:
            continue
        if code not in code_to_cn:
            raise ValueError(
                f"未知币种代码: {token}(有效代码: {', '.join(code_to_cn)};示例: usd,eur)"
            )
        if code not in codes:
            codes.append(code)
    return [code_to_cn[c] for c in codes] if codes else list(_BOC_SAFE_COLUMNS)


def _query_mid(currency: str | None, start_date: str | None, end_date: str | None) -> pd.DataFrame:
    """央行中间价全表:输出 date + 币种小写列,值保持"100 外币"口径原样(不 dropna,
    早期年份多数币种本就无牌价)。"""
    df = ak.currency_boc_safe()
    if df is None or df.empty:
        raise ValueError("央行中间价(currency_boc_safe)返回空数据")
    _require_columns(df, ["日期"], "央行中间价 currency_boc_safe")
    unknown = [c for c in df.columns if c != "日期" and c not in _BOC_SAFE_COLUMNS]
    if unknown:
        raise ValueError(
            f"currency_boc_safe 出现未映射币种列 {unknown},请检查 akshare 版本并在 fx.py 补充映射"
        )
    keep_cn = _select_mid_currencies(currency)
    _require_columns(df, keep_cn, "央行中间价 currency_boc_safe")
    df = df.rename(columns={"日期": "date", **_BOC_SAFE_COLUMNS})
    keep = ["date"] + [_BOC_SAFE_COLUMNS[c] for c in keep_cn]
    df = filter_by_date(df[keep], start_date, end_date)
    if df.empty:
        raise ValueError(f"mid 在 {start_date or '最早'}~{end_date or '最新'} 区间无数据")
    return df.sort_values("date").reset_index(drop=True)


def _query_bochina(symbol: str | None, start_date: str | None, end_date: str | None) -> pd.DataFrame:
    """中行人民币牌价:输出 date/buy/cash_buy/sell/mid/boc_ref(约 2012 年起,长区间慢)。"""
    if not symbol or not symbol.strip():
        raise ValueError(
            "kind=bochina 需提供 symbol(币种中文名,如 '美元';注意新浪侧是 '港币' 不是 '港元')"
        )
    if not start_date or not end_date:
        raise ValueError(
            "kind=bochina 需提供 start_date 与 end_date(YYYY-MM-DD;"
            "akshare 缺省值是任取的示例区间,静默透传会拿到错数据)"
        )
    df = ak.currency_boc_sina(
        symbol=symbol.strip(),
        start_date=to_compact_date(start_date, default_today=False),
        end_date=to_compact_date(end_date, default_today=False),
    )
    if df is None or df.empty:
        raise ValueError(
            f"中行牌价(currency_boc_sina, symbol={symbol})在 {start_date}~{end_date} 返回空数据"
            f"(数据约 2012 年起;币种中文名如 '美元'/'港币')"
        )
    _require_columns(df, list(_BOC_SINA_COLUMNS), "新浪 currency_boc_sina")
    df = filter_by_date(df.rename(columns=_BOC_SINA_COLUMNS), start_date, end_date)
    if df.empty:
        raise ValueError(f"中行牌价 symbol={symbol} 在 {start_date}~{end_date} 区间无数据")
    return df.sort_values("date").reset_index(drop=True)


def _query_yahoo_close(ticker: str, start_date: str | None, end_date: str | None) -> pd.DataFrame:
    """Yahoo Finance 日线收盘价:输出 date/close;yfinance 的 end 为排他区间 → 补一天。

    Yahoo 请求失败(异常或空表)时报含"不可达"的可读错误并保留异常链。
    """
    kwargs: dict = {"progress": False}
    if start_date and end_date:
        kwargs["start"] = start_date
        # yfinance 的 end 为排他区间,repo 契约是闭区间 → 补一天,再由 filter_by_date 截齐
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
        # 本机被 Yahoo 拒(429/403)时 yfinance 通常不抛异常而是返回空表
        raise ValueError(
            f"Yahoo Finance({ticker})返回空数据。该源在当前网络不可达(或代码无数据),"
            f"请检查网络/代理后重试"
        )
    if isinstance(df.columns, pd.MultiIndex):  # 单标的下载也会带 ticker 层,取价格层
        df.columns = df.columns.get_level_values(0)
    df = df.reset_index()
    df.columns = [str(c).lower() for c in df.columns]
    _require_columns(df, ["date", "close"], f"yfinance {ticker}", hint="请检查 yfinance 版本")
    return df[["date", "close"]]


def _query_usdcnh(start_date: str | None, end_date: str | None) -> pd.DataFrame:
    """离岸人民币 USDCNH=X 日线:输出 date/close 升序。"""
    df = _query_yahoo_close(_USDCNH_TICKER, start_date, end_date)
    df = filter_by_date(df, start_date, end_date)
    df = df.dropna(subset=["close"])  # 与 global_rates 一致:输出不残留 close 缺失行
    if df.empty:
        raise ValueError(f"usdcnh 在 {start_date or '最早'}~{end_date or '最新'} 区间无数据")
    return df.sort_values("date").reset_index(drop=True)


def _normalize_pair(pair: str) -> str:
    """货币对归一:``EUR/USD`` / ``eur-usd`` / ``eurusd`` → ``EURUSD``(大写无分隔)。"""
    s = re.sub(r"[\s/\-_:]", "", str(pair)).upper()
    if not re.fullmatch(r"[A-Z]{6}", s):
        raise ValueError(f"Unrecognized pair: {pair}(示例: EUR/USD 或 EURUSD,两个 ISO 货币代码)")
    return s


def _query_cross(pair: str | None, start_date: str | None, end_date: str | None) -> pd.DataFrame:
    """交叉盘 ``<PAIR>=X`` 日线:pair 归一为大写无分隔,输出 date/close 升序。"""
    if not pair or not str(pair).strip():
        raise ValueError("kind=cross 需提供 pair(如 'EUR/USD' 或 'EURUSD')")
    ticker = f"{_normalize_pair(pair)}=X"
    df = _query_yahoo_close(ticker, start_date, end_date)
    df = filter_by_date(df, start_date, end_date)
    df = df.dropna(subset=["close"])  # 与 usdcnh 一致:输出不残留 close 缺失行
    if df.empty:
        raise ValueError(f"cross {ticker} 在 {start_date or '最早'}~{end_date or '最新'} 区间无数据")
    return df.sort_values("date").reset_index(drop=True)


def _check_param_scope(kind: str, currency: str | None, symbol: str | None, pair: str | None) -> None:
    """kind 专属参数传错 kind 时显式报错(不静默忽略,对齐 global_rates 的 tenure 守卫)。"""
    if currency is not None and kind != "mid":
        raise ValueError(f"currency 仅在 kind=mid 时有效, kind={kind} 不支持")
    if symbol is not None and kind != "bochina":
        raise ValueError(f"symbol 仅在 kind=bochina 时有效, kind={kind} 不支持")
    if pair is not None and kind != "cross":
        raise ValueError(f"pair 仅在 kind=cross 时有效, kind={kind} 不支持")


def query_fx(
    kind: FxKind,
    file_path: str,
    currency: str | None = None,
    symbol: str | None = None,
    pair: str | None = None,
    start_date: str | None = None,
    end_date: str | None = None,
) -> tuple[str, str]:
    """查询外汇数据(人民币中间价/中行牌价/离岸人民币/交叉盘)并输出 CSV。

    参数:
        kind: ``mid`` / ``bochina`` / ``usdcnh`` / ``cross``
        currency: 仅 mid,逗号分隔币种代码(如 ``usd,eur``),缺省输出全部 25 币种
        symbol: 仅 bochina,币种中文名(如 ``美元``;注意 ``港币``)
        pair: 仅 cross,货币对(如 ``EUR/USD`` 或 ``EURUSD``)
        start_date/end_date: ``YYYY-MM-DD``(bochina 必填;mid/usdcnh/cross 可选)
    """
    if kind not in ("mid", "bochina", "usdcnh", "cross"):
        raise ValueError(f"Unsupported fx kind: {kind}, use 'mid', 'bochina', 'usdcnh' or 'cross'")
    _check_param_scope(kind, currency, symbol, pair)
    if kind == "mid":
        df = _query_mid(currency, start_date, end_date)
    elif kind == "bochina":
        df = _query_bochina(symbol, start_date, end_date)
    elif kind == "usdcnh":
        df = _query_usdcnh(start_date, end_date)
    else:
        df = _query_cross(pair, start_date, end_date)

    if df.empty:
        raise ValueError(f"No data returned for fx kind={kind}")
    file_path, summary = format_csv_output(df, file_path)
    if kind == "mid":
        # mid 的数值是"100 外币"口径,summary 显式注明单位防止误读为 1 外币
        summary = f"{_MID_UNIT_LINE}\n{summary}"
    return file_path, summary
