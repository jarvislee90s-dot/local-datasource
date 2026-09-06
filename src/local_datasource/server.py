"""MCP Server 入口（mcp 2.x ``MCPServer``，stdio 传输）。

注册 16 个 tool（清单与 1.x build_tools() 一致）：
- ``query_stock``：A 股 / 港股 / 美股
- ``query_yfinance``：美股/全球资产（默认 akshare，可选 yfinance）
- ``query_worldbank``：世界银行宏观指标
- ``query_arxiv``：arXiv 学术论文
- ``query_bond``：中国境内债券（国债收益率曲线/信用债发行信息/交易所行情）
- ``query_convertible_bond``：可转债（一览/条款/历史K线/发行人财务）
- ``resolve_stock_code``：股票名称（简称/全称）→ 代码候选
- ``query_futures``：国内期货(单合约/主连行情、合约清单)
- ``query_index``：国内指数(沪深/中证系列,日线/分钟)
- ``query_etf``：A股场内 ETF(日线/分钟)
- ``query_options``：期权(ETF期权/股指期权:月份/清单/日线)
- ``query_global_rates``：全球利率(美债收益率曲线/美联储 EFFR/美元指数/VIX)
- ``query_fx``：外汇(人民币中间价/中行牌价/离岸 USDCNH/交叉盘)
- ``query_spot``：现货(上金所贵金属/生意社大宗含基差)
- ``align_series``：多序列对齐合并(宽表/并集交集/前向填充/周月重采样,纯本地)
- ``query_trading_rules``：交易规则参数表(税费/涨跌幅/T+1/保证金等,带生效区间,纯本地)

通过标准 MCP stdio 协议与 Agent 通信。

参数注解（Annotated/Literal/Field）即客户端可见 schema；工具 docstring 即工具描述
（逐字取自基线 build_tools() 的对应 description）。错误经 _safe_summary 统一包装：
业务异常以 `Error calling <name>: ...` 文本回传，不被 2.x 吞成裸 `Error executing tool`。
"""
from __future__ import annotations

import sys
from typing import Annotated, Any, Literal

from pydantic import Field

from mcp.server.mcpserver import MCPServer

from local_datasource.config import load_config

# provider 函数带 ``_`` 前缀别名导入:下方同名薄工具函数会在模块级遮蔽原名,
# _summary_for 必须路由到原始 provider 而非薄函数自身(否则自引用解包报错)。
from local_datasource.providers.align import align_series as _align_series
from local_datasource.providers.arxiv import query_arxiv as _query_arxiv
from local_datasource.providers.bond import query_bond as _query_bond
from local_datasource.providers.convertible_bond import (
    query_convertible_bond as _query_convertible_bond,
)
from local_datasource.providers.etf import query_etf as _query_etf
from local_datasource.providers.futures import query_futures as _query_futures
from local_datasource.providers.fx import query_fx as _query_fx
from local_datasource.providers.global_rates import (
    query_global_rates as _query_global_rates,
)
from local_datasource.providers.index import query_index as _query_index
from local_datasource.providers.options import query_options as _query_options
from local_datasource.providers.rules import (
    query_trading_rules as _query_trading_rules,
)
from local_datasource.providers.spot import query_spot as _query_spot
from local_datasource.providers.stock import (
    query_stock as _query_stock,
    resolve_stock_code as _resolve_stock_code,
)
from local_datasource.providers.worldbank import query_worldbank as _query_worldbank
from local_datasource.providers.yahoo import query_yfinance as _query_yfinance

APP_NAME = "local-datasource"

mcp = MCPServer(APP_NAME)


def _summary_for(name: str, arguments: dict[str, Any]) -> str:
    """按 tool 名路由到 provider（与基线 handle_call_tool 分支一一对应）。"""
    if name == "query_stock":
        _, summary = _query_stock(**arguments)
    elif name == "query_yfinance":
        # 缺省(None)回退 config——客户端显式传 false 时不回退
        if arguments.get("use_yfinance") is None:
            arguments["use_yfinance"] = load_config().providers.yahoo.use_yfinance
        _, summary = _query_yfinance(**arguments)
    elif name == "query_worldbank":
        _, summary = _query_worldbank(**arguments)
    elif name == "query_arxiv":
        _, summary = _query_arxiv(**arguments)
    elif name == "query_bond":
        _, summary = _query_bond(**arguments)
    elif name == "query_convertible_bond":
        _, summary = _query_convertible_bond(**arguments)
    elif name == "resolve_stock_code":
        _, summary = _resolve_stock_code(**arguments)
    elif name == "query_futures":
        _, summary = _query_futures(**arguments)
    elif name == "query_index":
        _, summary = _query_index(**arguments)
    elif name == "query_etf":
        _, summary = _query_etf(**arguments)
    elif name == "query_options":
        _, summary = _query_options(**arguments)
    elif name == "query_global_rates":
        _, summary = _query_global_rates(**arguments)
    elif name == "query_fx":
        _, summary = _query_fx(**arguments)
    elif name == "query_spot":
        _, summary = _query_spot(**arguments)
    elif name == "align_series":
        _, summary = _align_series(**arguments)
    elif name == "query_trading_rules":
        _, summary = _query_trading_rules(**arguments)
    else:
        raise ValueError(f"Unknown tool: {name}")
    return summary


def _safe_summary(name: str, arguments: dict[str, Any]) -> str:
    """统一错误捕获：业务异常以 `Error calling <name>: ...` 文本回传（fe9ed77 教训：
    mcp 2.x 会把未捕获异常吞成只有 `Error executing tool <name>`，补数指引到不了客户端）。"""
    try:
        return _summary_for(name, dict(arguments))
    except Exception as e:  # noqa: BLE001
        return f"Error calling {name}: {e}"


# ---- 16 个薄工具函数:统一模式=参数注解(Annotated/Literal/Field)即 schema,
# docstring 即工具描述(逐字取自 1.x 基线 build_tools()),函数体一行转发 _safe_summary ----


@mcp.tool(structured_output=False)
def query_futures(
    symbol: Annotated[str, Field(description="Contract e.g. IM2612, main IM0, or variety IM (contracts)")],
    file_path: Annotated[str, Field(description="Output CSV file path")],
    kind: Annotated[Literal["hist", "contracts"], Field(description="Query type")] = "hist",
    period: Annotated[Literal["daily", "min"], Field(description="K-line period (hist)")] = "daily",
    freq: Annotated[Literal["1", "5", "15", "30", "60"], Field(description="Minute granularity (period=min)")] = "1",
    start_date: Annotated[str | None, Field(description="Start date YYYY-MM-DD")] = None,
    end_date: Annotated[str | None, Field(description="End date YYYY-MM-DD")] = None,
    trade_date: Annotated[str | None, Field(description="Trade date YYYY-MM-DD (contracts, default today; DCE/GFEX 品种忽略此参数,返回当前挂牌)")] = None,
) -> str:
    """Query China futures. Output is written to file_path as CSV. kind=hist: 单合约/主连日线全历史(主连自品种上市日或2005-01-04起,IF0特例仅2017-01-17起; period=min 约4交易日需起止日期). kind=contracts: 品种挂牌合约清单(如 IM/RB). 分钟超覆盖时明确报错并给补数指引,不静默降级."""
    return _safe_summary("query_futures", {
        "symbol": symbol, "file_path": file_path, "kind": kind, "period": period,
        "freq": freq, "start_date": start_date, "end_date": end_date, "trade_date": trade_date,
    })


@mcp.tool(structured_output=False)
def query_yfinance(
    ticker: Annotated[str, Field(description="Ticker, e.g. AAPL, SPY, GLD")],
    file_path: Annotated[str, Field(description="Output CSV file path")],
    period: Literal["1d", "5d", "1mo", "3mo", "6mo", "1y", "2y", "5y", "10y", "max"] = "1y",
    start_date: Annotated[str | None, Field(description="Optional start date YYYY-MM-DD")] = None,
    end_date: Annotated[str | None, Field(description="Optional end date YYYY-MM-DD")] = None,
    use_yfinance: Annotated[bool | None, Field(description="Use yfinance instead of akshare")] = None,
) -> str:
    """Query historical prices for US/global tickers. Defaults to akshare (free, no key); set use_yfinance=true to fall back to Yahoo Finance."""
    return _safe_summary("query_yfinance", {
        "ticker": ticker, "file_path": file_path, "period": period,
        "start_date": start_date, "end_date": end_date, "use_yfinance": use_yfinance,
    })


@mcp.tool(structured_output=False)
def align_series(
    file_paths: Annotated[list[str], Field(description="Input CSV paths (>= 2) produced by this library; first column must be date/datetime/日期")],
    file_path: Annotated[str, Field(description="Output CSV file path")],
    columns: Annotated[list[str] | None, Field(description="Value column per input file, aligned with file_paths; default close for each")] = None,
    names: Annotated[list[str] | None, Field(description="Output column name per input file, aligned with file_paths; default file name stem")] = None,
    align: Annotated[Literal["outer", "inner"], Field(description="Join on date: outer (union, missing = NaN) or inner (intersection)")] = "outer",
    fill: Annotated[Literal["none", "ffill"], Field(description="Forward-fill value columns after join (leading NaN stays NaN)")] = "none",
    resample: Annotated[Literal["none", "week", "month"], Field(description="Per-series resample before join: week (W-FRI) or month; keeps each period's last actual trading day")] = "none",
) -> str:
    """把本库产出的多份 CSV 按日期对齐合并成一张宽表(默认各取 close 列),支持并集/交集、前向填充、重采样到周(周五)/月(取期末交易日);纯本地计算,不联网。输出写入 file_path 为 CSV。"""
    return _safe_summary("align_series", {
        "file_paths": file_paths, "file_path": file_path, "columns": columns,
        "names": names, "align": align, "fill": fill, "resample": resample,
    })


@mcp.tool(structured_output=False)
def query_trading_rules(
    market: Annotated[Literal["a", "etf", "cffex", "treasury_futures", "margin", "option", "hk_connect", "commodity_futures"], Field(description="Rule market: a (A股), etf, cffex (股指期货/期权品种), treasury_futures, margin (两融), option, hk_connect (港股通), commodity_futures (引导行)")],
    file_path: Annotated[str, Field(description="Output CSV file path")],
    as_of: Annotated[str | None, Field(description="生效日判定日期 YYYY-MM-DD; default today")] = None,
    parameter: Annotated[str | None, Field(description="Optional substring filter on parameter column (case-insensitive), e.g. 印花税/涨跌幅/融资保证金")] = None,
) -> str:
    """查询当时生效的中国交易规则参数(印花税/过户费/涨跌幅/T+1/股指期货与国债期货保证金及平今费/融资保证金/期权与港股通费率),按 as_of 命中生效区间,缺省取今天;每行含生效区间/来源/置信度(official/media/to_verify/market_estimate);market=commodity_futures 返回查交易所当日结算参数的引导行。输出写入 file_path 为 CSV。"""
    return _safe_summary("query_trading_rules", {
        "market": market, "file_path": file_path, "as_of": as_of, "parameter": parameter,
    })


@mcp.tool(structured_output=False)
def query_stock(
    ticker: Annotated[str, Field(description="Stock ticker, e.g. 600519, 00700, AAPL")],
    market: Annotated[Literal["a", "hk", "us"], Field(description="Market: a (A-share), hk (Hong Kong), us (US)")],
    start_date: Annotated[str, Field(description="Start date YYYY-MM-DD")],
    end_date: Annotated[str, Field(description="End date YYYY-MM-DD")],
    file_path: Annotated[str, Field(description="Output CSV file path")],
    adjust: Annotated[Literal["qfq", "hfq", "none"], Field(description="Adjustment type")] = "qfq",
    period: Annotated[Literal["daily", "min"], Field(description="K-line period (min: A-share only)")] = "daily",
    freq: Annotated[Literal["1", "5", "15", "30", "60"], Field(description="Minute granularity (period=min)")] = "1",
) -> str:
    """Query historical stock prices for A-share, Hong Kong, or US markets. Output is written to file_path as CSV."""
    return _safe_summary("query_stock", {
        "ticker": ticker, "market": market, "start_date": start_date, "end_date": end_date,
        "file_path": file_path, "adjust": adjust, "period": period, "freq": freq,
    })


@mcp.tool(structured_output=False)
def query_worldbank(
    indicator: Annotated[str, Field(description="World Bank indicator code, e.g. NY.GDP.MKTP.CD")],
    country: Annotated[str, Field(description="Country code(s) comma-separated, e.g. CHN,USA or all")],
    start_year: Annotated[int, Field(description="Start year")],
    end_year: Annotated[int, Field(description="End year")],
    file_path: Annotated[str, Field(description="Output CSV file path")],
) -> str:
    """Query World Bank macroeconomic indicators. Output is written to file_path as CSV."""
    return _safe_summary("query_worldbank", {
        "indicator": indicator, "country": country, "start_year": start_year,
        "end_year": end_year, "file_path": file_path,
    })


@mcp.tool(structured_output=False)
def query_arxiv(
    query: Annotated[str, Field(description="Search query")],
    file_path: Annotated[str, Field(description="Output CSV file path")],
    max_results: Annotated[int, Field(description="Max number of results")] = 10,
    sort_by: Literal["relevance", "submitted", "last_updated"] = "relevance",
) -> str:
    """Search arXiv papers. Output is written to file_path as CSV."""
    return _safe_summary("query_arxiv", {
        "query": query, "file_path": file_path, "max_results": max_results, "sort_by": sort_by,
    })


@mcp.tool(structured_output=False)
def query_bond(
    kind: Annotated[Literal["yield_curve", "issue_info", "credit_daily"], Field(description="Query type")],
    file_path: Annotated[str, Field(description="Output CSV file path")],
    start_date: Annotated[str | None, Field(description="Start date YYYY-MM-DD (yield_curve/credit_daily)")] = None,
    end_date: Annotated[str | None, Field(description="End date YYYY-MM-DD (yield_curve/credit_daily)")] = None,
    bond_code: Annotated[str | None, Field(description="Bond code e.g. 2180495.IB or 2180495 (issue_info, mutually exclusive with bond_issue)")] = None,
    bond_issue: Annotated[str | None, Field(description="Issuer name e.g. 成都东方广益 (issue_info, returns latest bond by issue date, mutually exclusive with bond_code)")] = None,
    symbol: Annotated[str | None, Field(description="Exchange bond symbol e.g. sh019623 (credit_daily)")] = None,
) -> str:
    """Query China onshore bonds. Output is written to file_path as CSV. kind=yield_curve: 国债到期收益率曲线 (bond_china_yield). kind=issue_info: 信用债发行信息含评级 (bond_info_cm). kind=credit_daily: 信用债交易所日行情 (bond_zh_hs_daily). 已知限制(akshare免费层无): 中债估值YTM/全价、赎回回售条款详情、剩余期限、城投发行人财务。"""
    return _safe_summary("query_bond", {
        "kind": kind, "file_path": file_path, "start_date": start_date, "end_date": end_date,
        "bond_code": bond_code, "bond_issue": bond_issue, "symbol": symbol,
    })


@mcp.tool(structured_output=False)
def query_convertible_bond(
    kind: Annotated[Literal["overview", "terms", "history", "issuer_finance"], Field(description="Query type")],
    file_path: Annotated[str, Field(description="Output CSV file path")],
    symbol: Annotated[str | None, Field(description="CB symbol e.g. sz128039 (history)")] = None,
    start_date: Annotated[str | None, Field(description="Start date YYYY-MM-DD (history)")] = None,
    end_date: Annotated[str | None, Field(description="End date YYYY-MM-DD (history)")] = None,
    period: Annotated[Literal["daily", "min"], Field(description="K-line period (history)")] = "daily",
    bond_code: Annotated[str | None, Field(description="CB code (issuer_finance, mutually exclusive with stock_code)")] = None,
    stock_code: Annotated[str | None, Field(description="Underlying stock code (issuer_finance, mutually exclusive with bond_code)")] = None,
    report_type: Annotated[Literal["资产负债表", "利润表", "现金流量表"], Field(description="Financial report type (issuer_finance)")] = "资产负债表",
    keyword: Annotated[str | None, Field(description="Keyword filter (overview, optional)")] = None,
) -> str:
    """Query China convertible bonds. Output is written to file_path as CSV. kind=overview: 全市场一览含转股溢价率/评级/规模 (bond_zh_cov). kind=terms: 强赎/回售/下修条款+剩余期限 (集思录). kind=history: 单只转债历史K线 daily/min (bond_zh_hs_cov_daily/min). kind=issuer_finance: 发行人正股三大报表;城投/非上市发行人返回引导性提示。"""
    return _safe_summary("query_convertible_bond", {
        "kind": kind, "file_path": file_path, "symbol": symbol, "start_date": start_date,
        "end_date": end_date, "period": period, "bond_code": bond_code,
        "stock_code": stock_code, "report_type": report_type, "keyword": keyword,
    })


@mcp.tool(structured_output=False)
def resolve_stock_code(
    keyword: Annotated[str, Field(description="Stock name or keyword, e.g. 茅台 / 贵州茅台酒股份有限公司")],
    file_path: Annotated[str, Field(description="Output CSV file path")],
) -> str:
    """Resolve A-share stock code by company name (abbreviation or full name). Output is written to file_path as CSV with candidate rows (代码+名称). 简称精确命中;全称能命中简称子串则返回;城投/非上市发行人返回空候选。多候选时 Agent/用户从中选,再调 query_stock 查行情。"""
    return _safe_summary("resolve_stock_code", {
        "keyword": keyword, "file_path": file_path,
    })


@mcp.tool(structured_output=False)
def query_index(
    symbol: Annotated[str, Field(description="Index code e.g. 000852, sh000300, 930050")],
    file_path: Annotated[str, Field(description="Output CSV file path")],
    period: Annotated[Literal["daily", "min"], Field(description="K-line period")] = "daily",
    freq: Annotated[Literal["1", "5", "15", "30", "60"], Field(description="Minute granularity (period=min)")] = "1",
    start_date: Annotated[str | None, Field(description="Start date YYYY-MM-DD")] = None,
    end_date: Annotated[str | None, Field(description="End date YYYY-MM-DD")] = None,
) -> str:
    """Query China indices. Output is written to file_path as CSV. 000xxx/399xxx 走新浪(日线自2014起); 930xxx/950xxx 中证系列走官网(慢约10秒). period=min 仅沪深指数(腾讯源约8交易日). 分钟超覆盖时明确报错并给补数指引."""
    return _safe_summary("query_index", {
        "symbol": symbol, "file_path": file_path, "period": period, "freq": freq,
        "start_date": start_date, "end_date": end_date,
    })


@mcp.tool(structured_output=False)
def query_etf(
    symbol: Annotated[str, Field(description="ETF code e.g. 510300 or sh510300")],
    file_path: Annotated[str, Field(description="Output CSV file path")],
    period: Annotated[Literal["daily", "min"], Field(description="K-line period")] = "daily",
    freq: Annotated[Literal["1", "5", "15", "30", "60"], Field(description="Minute granularity (period=min)")] = "1",
    start_date: Annotated[str | None, Field(description="Start date YYYY-MM-DD")] = None,
    end_date: Annotated[str | None, Field(description="End date YYYY-MM-DD")] = None,
) -> str:
    """Query China onshore-listed ETF. Output is written to file_path as CSV. daily 自约2012年起(新浪,无复权返回原始价); min 腾讯源约8交易日. 分钟超覆盖时明确报错并给补数指引."""
    return _safe_summary("query_etf", {
        "symbol": symbol, "file_path": file_path, "period": period, "freq": freq,
        "start_date": start_date, "end_date": end_date,
    })


@mcp.tool(structured_output=False)
def query_options(
    kind: Annotated[Literal["months", "contracts", "hist"], Field(description="Query type")],
    file_path: Annotated[str, Field(description="Output CSV file path")],
    underlying: Annotated[str | None, Field(description="Underlying: 50ETF/300ETF/500ETF/科创50ETF/IO/HO/MO (months/contracts)")] = None,
    symbol: Annotated[str | None, Field(description="Option contract code e.g. 10003889 or IO2706-P-5600 (hist)")] = None,
    start_date: Annotated[str | None, Field(description="Start date YYYY-MM-DD (hist)")] = None,
    end_date: Annotated[str | None, Field(description="End date YYYY-MM-DD (hist)")] = None,
    trade_date: Annotated[str | None, Field(description="Trade date YYYY-MM-DD (contracts/CFFEX, default today)")] = None,
) -> str:
    """Query China options (SSE ETF options + CFFEX index options IO/HO/MO). Output is written to file_path as CSV. kind=months: 标的到期月份. kind=contracts: 当月合约清单. kind=hist: 单合约日线. 本轮仅日线; 找合约代码先用 months/contracts."""
    return _safe_summary("query_options", {
        "kind": kind, "file_path": file_path, "underlying": underlying, "symbol": symbol,
        "start_date": start_date, "end_date": end_date, "trade_date": trade_date,
    })


@mcp.tool(structured_output=False)
def query_global_rates(
    kind: Annotated[Literal["us_treasury", "fed_rate", "dxy", "vix"], Field(description="Query type")],
    file_path: Annotated[str, Field(description="Output CSV file path")],
    start_date: Annotated[str | None, Field(description="Start date YYYY-MM-DD")] = None,
    end_date: Annotated[str | None, Field(description="End date YYYY-MM-DD")] = None,
    tenure: Annotated[Literal["all", "2y", "5y", "10y", "30y", "1m", "3m", "4m", "6m", "1y", "7y", "20y"] | None, Field(description="Treasury tenure (us_treasury only, default all)")] = None,
) -> str:
    """Query global rates for backtesting. Output is written to file_path as CSV. kind=us_treasury: 美债收益率(2/5/10/30Y 及 10Y-2Y 利差,1990 起;tenure 选期限,短端期限仅近 1000 交易日). kind=fed_rate: 美联储 EFFR 日频有效联邦基金利率(纽约联储 API,2000-07 起). kind=dxy: 美元指数(东财失败自动回退 Yahoo). kind=vix: VIX 波动率指数(CBOE 直连,1990 起)."""
    return _safe_summary("query_global_rates", {
        "kind": kind, "file_path": file_path, "start_date": start_date,
        "end_date": end_date, "tenure": tenure,
    })


@mcp.tool(structured_output=False)
def query_fx(
    kind: Annotated[Literal["mid", "bochina", "usdcnh", "cross"], Field(description="Query type")],
    file_path: Annotated[str, Field(description="Output CSV file path")],
    currency: Annotated[str | None, Field(description="Comma-separated currency codes (mid only), e.g. usd,eur; default all 25")] = None,
    symbol: Annotated[str | None, Field(description="Currency Chinese name (bochina only), e.g. 美元; note 港币 not 港元")] = None,
    pair: Annotated[str | None, Field(description="FX pair (cross only), e.g. EUR/USD or EURUSD")] = None,
    start_date: Annotated[str | None, Field(description="Start date YYYY-MM-DD (required for bochina)")] = None,
    end_date: Annotated[str | None, Field(description="End date YYYY-MM-DD (required for bochina)")] = None,
) -> str:
    """Query FX rates. Output is written to file_path as CSV. kind=mid: 央行人民币中间价(单位为 100 外币,自 1994 起;currency 过滤币种如 usd,eur). kind=bochina: 中行牌价(约 2012 起,symbol 用币种中文名如 美元;起止日期必填,长区间分页拉取较慢). kind=usdcnh: 离岸人民币 USDCNH 日线(Yahoo). kind=cross: 交叉盘日线,pair 如 EUR/USD(Yahoo,不可达时明确报错)."""
    return _safe_summary("query_fx", {
        "kind": kind, "file_path": file_path, "currency": currency, "symbol": symbol,
        "pair": pair, "start_date": start_date, "end_date": end_date,
    })


@mcp.tool(structured_output=False)
def query_spot(
    kind: Annotated[Literal["sge", "sy"], Field(description="Query type")],
    file_path: Annotated[str, Field(description="Output CSV file path")],
    symbol: Annotated[str | None, Field(description="SGE variety, e.g. Au99.99, Ag99.99, Au(T+D) (sge only, required)")] = None,
    symbols: Annotated[list[str] | None, Field(description='100ppi variety codes, e.g. ["CU", "RB"] (sy only, required)')] = None,
    start_date: Annotated[str | None, Field(description="Start date YYYY-MM-DD (required for sy; optional filter for sge)")] = None,
    end_date: Annotated[str | None, Field(description="End date YYYY-MM-DD (required for sy; optional filter for sge)")] = None,
) -> str:
    """Query spot prices. Output is written to file_path as CSV. kind=sge: 上金所贵金属现货日线 date,open,high,low,close(2016-12 起约 10 年深度,symbol 必填如 Au99.99/Ag99.99/Au(T+D)). kind=sy: 生意社大宗现货含主力合约价与基差(symbols 如 ['CU','RB'];起止日期必填,逐日抓取较慢,单次区间最长 1 年)."""
    return _safe_summary("query_spot", {
        "kind": kind, "file_path": file_path, "symbol": symbol, "symbols": symbols,
        "start_date": start_date, "end_date": end_date,
    })


def main() -> None:
    """同步入口：console script 直接调用。``download`` 子命令转交批量下载 CLI；
    无参数或首个参数不是 download 时启动 MCP stdio 服务。"""
    if len(sys.argv) > 1 and sys.argv[1] == "download":
        from local_datasource.cli import run_download

        raise SystemExit(run_download(sys.argv[2:]))
    mcp.run()


if __name__ == "__main__":
    main()
