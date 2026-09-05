"""全球利率 provider:美债收益率曲线 + 美联储 EFFR + 美元指数 + VIX。

- us_treasury:东财 ``bond_zh_us_rate`` 全表(1990-12-19 起)选美国列,
  输出 2/5/10/30Y 与 10Y-2Y 利差;短端(1m/3m/4m/6m/1y/7y/20y)走新浪
  ``bond_gb_us_sina``,仅近 1000 交易日
- fed_rate:纽约联储官方 EFFR API(markets.newyorkfed.org,免 key)。
  API 数据自 2000-07-03 起;单次请求跨度按 10 年分段(实测 2026-09:
  全量一次请求会读超时),失败重试一次,仍失败报网络指引
- dxy:美元指数。首选东财 ``index_global_hist_em(symbol="美元指数")``,
  失败回退 yfinance ``DX-Y.NYB``;两源均失败报网络指引(检查代理/网络)
- vix:CBOE 官方 VIX 指数日线直连(cdn.cboe.com ``VIX_History.csv``,
  1990-01-02 起),30 秒超时失败重试一次,仍失败报网络指引
"""
from __future__ import annotations

import io
from collections.abc import Callable, Sequence
from datetime import datetime
from typing import Literal

import akshare as ak
import pandas as pd
import requests
import yfinance as yf

from local_datasource.formatters import format_csv_output
from local_datasource.providers.common import filter_by_date


GlobalRatesKind = Literal["us_treasury", "fed_rate", "dxy", "vix"]

# 东财全表美国列 → 输出列(短端期限不在此表,走新浪源)
_LONG_TENURES = ("2y", "5y", "10y", "30y")
_EM_US_COLUMNS = {
    "美国国债收益率2年": "us_2y",
    "美国国债收益率5年": "us_5y",
    "美国国债收益率10年": "us_10y",
    "美国国债收益率30年": "us_30y",
    "美国国债收益率10年-2年": "us_10y_2y",
}

# 短端期限 → 新浪 bond_gb_us_sina symbol(仅近 1000 交易日)
_SHORT_TENURE_SYMBOLS = {
    "1m": "美国1月期国债",
    "3m": "美国3月期国债",
    "4m": "美国4月期国债",
    "6m": "美国6月期国债",
    "1y": "美国1年期国债",
    "7y": "美国7年期国债",
    "20y": "美国20年期国债",
}

_VALID_TENURES = ("all",) + _LONG_TENURES + tuple(_SHORT_TENURE_SYMBOLS)

_EFFR_API = "https://markets.newyorkfed.org/api/rates/unsecured/effr/search.json"
_EFFR_FLOOR = "2000-01-01"  # API 数据自 2000-07-03 起,更早无 EFFR
_EFFR_CHUNK_YEARS = 10  # 单次请求跨度上限,防止全量一次请求超时

# dxy:东财全球指数中文列 → 输出列;Yahoo 回退代码
_EM_DXY_COLUMNS = {"日期": "date", "今开": "open", "最高": "high", "最低": "low", "最新价": "close"}
_DXY_COLUMNS = ["date", "open", "high", "low", "close"]
_DXY_YAHOO_TICKER = "DX-Y.NYB"

# vix:CBOE 官方日线 CSV(US 风格日期 M/D/YYYY,1990-01-02 起)
_CBOE_VIX_URL = "https://cdn.cboe.com/api/global/us_indices/daily_prices/VIX_History.csv"
_CBOE_VIX_COLUMNS = {"DATE": "date", "OPEN": "open", "HIGH": "high", "LOW": "low", "CLOSE": "close"}


def _check_tenure_scope(kind: str, tenure: str | None) -> None:
    """tenure 仅对 us_treasury 有效,其他 kind 传入直接报错(不静默忽略)。"""
    if tenure is not None and kind != "us_treasury":
        raise ValueError(f"tenure 仅在 kind=us_treasury 时有效, kind={kind} 不支持")


def _require_columns(df: pd.DataFrame, required: list[str], source: str,
                     hint: str = "请检查 akshare 版本") -> None:
    """上游列漂移守卫:缺列时报可读错误(对齐 futures.py 的版本指引文案)。"""
    missing = [c for c in required if c not in df.columns]
    if missing:
        raise ValueError(f"{source} 列名不受支持(缺 {missing}),{hint}")


def _query_us_treasury(tenure: str | None, start_date: str | None, end_date: str | None) -> pd.DataFrame:
    """美债收益率:all/长端走东财全表,短端走新浪(仅近 1000 交易日)。"""
    tenure = tenure or "all"
    if tenure in _SHORT_TENURE_SYMBOLS:
        df = ak.bond_gb_us_sina(symbol=_SHORT_TENURE_SYMBOLS[tenure])
        if df.empty:
            raise ValueError(f"No US treasury data for tenure={tenure}(新浪短端源仅近 1000 交易日)")
        _require_columns(df, ["date", "close"], "新浪 bond_gb_us_sina")
        df = filter_by_date(df, start_date, end_date)
        if df.empty:
            raise ValueError(
                f"tenure={tenure} 在 {start_date}~{end_date} 无数据(新浪短端源仅近 1000 交易日)"
            )
        return (
            df[["date", "close"]]
            .rename(columns={"close": f"us_{tenure}"})
            .sort_values("date")
            .reset_index(drop=True)
        )
    if tenure != "all" and tenure not in _LONG_TENURES:
        raise ValueError(f"Unsupported tenure: {tenure}, use one of {list(_VALID_TENURES)}")
    df = ak.bond_zh_us_rate(start_date="19901219")
    if df.empty:
        raise ValueError("No US treasury data returned by bond_zh_us_rate")
    keep = ["date"] + ([f"us_{tenure}"] if tenure != "all" else list(_EM_US_COLUMNS.values()))
    cn_names = {"date": "日期", **{v: k for k, v in _EM_US_COLUMNS.items()}}
    _require_columns(df, [cn_names[c] for c in keep], "东财 bond_zh_us_rate")
    df = df.rename(columns={"日期": "date", **_EM_US_COLUMNS})
    df = filter_by_date(df[keep], start_date, end_date)
    return df.sort_values("date").reset_index(drop=True)


def _http_get(url: str, source: str) -> requests.Response:
    """GET 请求,30 秒超时,失败重试一次;仍失败报含"不可达"的网络指引并保留异常链。"""
    last_exc: Exception | None = None
    for _ in range(2):
        try:
            resp = requests.get(url, timeout=30)
            resp.raise_for_status()
            return resp
        except requests.RequestException as e:  # 重试一次
            last_exc = e
    raise ValueError(
        f"{source} 请求失败(已重试一次): {last_exc}。该源在当前网络不可达,请检查网络/代理后重试"
    ) from last_exc


def _http_get_json(url: str) -> dict:
    """GET JSON(纽约联储 EFFR API)。"""
    return _http_get(url, "纽约联储 API").json()


def _http_get_text(url: str) -> str:
    """GET 响应文本(CBOE 返回原始 CSV 而非 JSON)。"""
    return _http_get(url, "CBOE").text


def _query_fed_rate(start_date: str | None, end_date: str | None) -> pd.DataFrame:
    """纽约联储 EFFR:按 10 年分段请求合并,输出 date, effr 升序。"""
    start = max(start_date or _EFFR_FLOOR, _EFFR_FLOOR)
    end = end_date or datetime.now().strftime("%Y-%m-%d")
    frames: list[pd.DataFrame] = []
    cursor = pd.Timestamp(start)
    stop = pd.Timestamp(end)
    while cursor <= stop:
        chunk_end = min(cursor + pd.DateOffset(years=_EFFR_CHUNK_YEARS) - pd.Timedelta(days=1), stop)
        payload = _http_get_json(
            f"{_EFFR_API}?startDate={cursor:%Y-%m-%d}&endDate={chunk_end:%Y-%m-%d}")
        rows = payload.get("refRates") or []
        if rows:
            frames.append(pd.DataFrame(rows))
        cursor = chunk_end + pd.Timedelta(days=1)
    if not frames:
        raise ValueError(f"No EFFR data between {start} and {end}")
    df = (
        pd.concat(frames, ignore_index=True)
        .rename(columns={"effectiveDate": "date", "percentRate": "effr"})[["date", "effr"]]
        .dropna(subset=["effr"])
        .drop_duplicates(subset="date")
    )
    df = filter_by_date(df, start_date, end_date)
    if df.empty:
        raise ValueError(f"No EFFR data between {start} and {end}")
    return df.sort_values("date").reset_index(drop=True)


def _query_dxy_eastmoney() -> pd.DataFrame:
    """东财全球指数-美元指数:全量历史,输出 date/open/high/low/close。"""
    df = ak.index_global_hist_em(symbol="美元指数")
    if df is None or df.empty:
        raise ValueError("东财美元指数(index_global_hist_em)返回空数据")
    _require_columns(df, list(_EM_DXY_COLUMNS), "东财 index_global_hist_em(美元指数)")
    return df.rename(columns=_EM_DXY_COLUMNS)[_DXY_COLUMNS]


def _query_dxy_yfinance(start_date: str | None, end_date: str | None) -> pd.DataFrame:
    """yfinance 美元指数回退源:DX-Y.NYB 日线,输出 date/open/high/low/close。"""
    kwargs: dict = {"progress": False}
    if start_date and end_date:
        kwargs["start"] = start_date
        # yfinance 的 end 为排他区间,repo 契约是闭区间 → 补一天,再由 filter_by_date 截齐
        kwargs["end"] = (pd.Timestamp(end_date) + pd.Timedelta(days=1)).strftime("%Y-%m-%d")
    else:
        kwargs["period"] = "max"
    df = yf.download(_DXY_YAHOO_TICKER, **kwargs)
    if df is None or df.empty:
        raise ValueError(f"yfinance {_DXY_YAHOO_TICKER} 返回空数据")
    if isinstance(df.columns, pd.MultiIndex):  # 单标的下载也会带 ticker 层,取价格层
        df.columns = df.columns.get_level_values(0)
    df = df.reset_index()
    df.columns = [str(c).lower() for c in df.columns]
    _require_columns(df, _DXY_COLUMNS, f"yfinance {_DXY_YAHOO_TICKER}", hint="请检查 yfinance 版本")
    return df[_DXY_COLUMNS]


def _first_available(
    sources: Sequence[tuple[str, Callable[[], pd.DataFrame]]],
    what: str,
    hint: str = "请检查代理/网络后重试",
) -> pd.DataFrame:
    """依次尝试多个数据源,返回首个成功结果;全部失败时报含"不可达"的聚合错误并保留异常链。"""
    failures: list[str] = []
    last_exc: Exception | None = None
    for name, fetch in sources:
        try:
            return fetch()
        except Exception as e:  # noqa: BLE001 - 回退链需吞掉任意源异常
            failures.append(f"{name}({type(e).__name__}: {e})")
            last_exc = e
    raise ValueError(f"{what}均失败(依次尝试: {'; '.join(failures)}),该源在当前网络不可达。{hint}") from last_exc


def _query_dxy(start_date: str | None, end_date: str | None) -> pd.DataFrame:
    """美元指数:东财首选,Yahoo 回退;两源均失败报网络指引并保留原始异常链。"""
    df = _first_available(
        (
            ("东财 index_global_hist_em", lambda: _query_dxy_eastmoney()),
            (f"yfinance {_DXY_YAHOO_TICKER}", lambda: _query_dxy_yfinance(start_date, end_date)),
        ),
        what="dxy 两数据源",
        hint="请检查代理/网络后重试(需可达: push2his.eastmoney.com 与 query1.finance.yahoo.com)",
    )
    df = filter_by_date(df, start_date, end_date)
    df = df.dropna(subset=["close"])  # 与 fed_rate 一致:输出不残留 close 缺失行
    if df.empty:
        raise ValueError(f"dxy 在 {start_date or '最早'}~{end_date or '最新'} 区间无数据")
    return df.sort_values("date").reset_index(drop=True)


def _query_vix(start_date: str | None, end_date: str | None) -> pd.DataFrame:
    """CBOE 官方 VIX 指数日线(1990-01 起):CSV 直连,输出 date/open/high/low/close 升序。"""
    text = _http_get_text(_CBOE_VIX_URL)
    df = pd.read_csv(io.StringIO(text))
    if df.empty:
        raise ValueError("CBOE VIX_History.csv 返回空数据")
    _require_columns(df, list(_CBOE_VIX_COLUMNS), "CBOE VIX_History.csv",
                     hint="请到 cdn.cboe.com 确认 VIX_History.csv 表头")
    df = df.rename(columns=_CBOE_VIX_COLUMNS)[list(_CBOE_VIX_COLUMNS.values())]
    # CBOE 日期为 US 风格 M/D/YYYY:显式按月前置解析,格式漂移时立即报错而非静默错位
    df["date"] = pd.to_datetime(df["date"], format="%m/%d/%Y").dt.strftime("%Y-%m-%d")
    df = filter_by_date(df, start_date, end_date)
    df = df.dropna(subset=["close"])  # 与 fed_rate/dxy 一致:输出不残留 close 缺失行
    if df.empty:
        raise ValueError(f"vix 在 {start_date or '最早'}~{end_date or '最新'} 区间无数据")
    return df.sort_values("date").reset_index(drop=True)


def query_global_rates(
    kind: GlobalRatesKind,
    file_path: str,
    start_date: str | None = None,
    end_date: str | None = None,
    tenure: str | None = None,
) -> tuple[str, str]:
    """查询全球利率数据(美债收益率/EFFR/美元指数/VIX)并输出 CSV。

    参数:
        kind: ``us_treasury`` / ``fed_rate`` / ``dxy`` / ``vix``
        tenure: 仅 us_treasury,``all`` 默认 / 长端 2y/5y/10y/30y / 短端 1m/3m/4m/6m/1y/7y/20y
        start_date/end_date: ``YYYY-MM-DD``
    """
    if kind not in ("us_treasury", "fed_rate", "dxy", "vix"):
        raise ValueError(f"Unsupported global_rates kind: {kind}, use 'us_treasury', 'fed_rate', 'dxy' or 'vix'")
    _check_tenure_scope(kind, tenure)
    if kind == "us_treasury":
        df = _query_us_treasury(tenure, start_date, end_date)
    elif kind == "fed_rate":
        df = _query_fed_rate(start_date, end_date)
    elif kind == "dxy":
        df = _query_dxy(start_date, end_date)
    else:
        df = _query_vix(start_date, end_date)

    if df.empty:
        raise ValueError(f"No data returned for global_rates kind={kind}")
    return format_csv_output(df, file_path)
