"""MCP Server 入口。

注册 15 个 tool：
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

通过标准 MCP stdio 协议与 Agent 通信。
"""
from __future__ import annotations

import asyncio
import sys
from typing import Any

from mcp.server.stdio import stdio_server
from mcp.types import (
    TextContent,
    Tool,
)
from mcp.server import Server

from local_datasource.config import load_config
from local_datasource.providers.align import align_series
from local_datasource.providers.arxiv import query_arxiv
from local_datasource.providers.bond import query_bond
from local_datasource.providers.convertible_bond import query_convertible_bond
from local_datasource.providers.etf import query_etf
from local_datasource.providers.futures import query_futures
from local_datasource.providers.fx import query_fx
from local_datasource.providers.global_rates import query_global_rates
from local_datasource.providers.index import query_index
from local_datasource.providers.options import query_options
from local_datasource.providers.spot import query_spot
from local_datasource.providers.stock import query_stock, resolve_stock_code
from local_datasource.providers.worldbank import query_worldbank
from local_datasource.providers.yahoo import query_yfinance


APP_NAME = "local-datasource"


def build_tools() -> list[Tool]:
    """构建并返回 MCP 工具列表。"""
    return [
        Tool(
            name="query_stock",
            description="Query historical stock prices for A-share, Hong Kong, or US markets. Output is written to file_path as CSV.",
            inputSchema={
                "type": "object",
                "properties": {
                    "ticker": {"type": "string", "description": "Stock ticker, e.g. 600519, 00700, AAPL"},
                    "market": {"type": "string", "enum": ["a", "hk", "us"], "description": "Market: a (A-share), hk (Hong Kong), us (US)"},
                    "start_date": {"type": "string", "description": "Start date YYYY-MM-DD"},
                    "end_date": {"type": "string", "description": "End date YYYY-MM-DD"},
                    "adjust": {"type": "string", "enum": ["qfq", "hfq", "none"], "default": "qfq", "description": "Adjustment type"},
                    "period": {"type": "string", "enum": ["daily", "min"], "default": "daily", "description": "K-line period (min: A-share only)"},
                    "freq": {"type": "string", "enum": ["1", "5", "15", "30", "60"], "default": "1", "description": "Minute granularity (period=min)"},
                    "file_path": {"type": "string", "description": "Output CSV file path"},
                },
                "required": ["ticker", "market", "start_date", "end_date", "file_path"],
            },
        ),
        Tool(
            name="query_yfinance",
            description="Query historical prices for US/global tickers. Defaults to akshare (free, no key); set use_yfinance=true to fall back to Yahoo Finance.",
            inputSchema={
                "type": "object",
                "properties": {
                    "ticker": {"type": "string", "description": "Ticker, e.g. AAPL, SPY, GLD"},
                    "period": {"type": "string", "enum": ["1d", "5d", "1mo", "3mo", "6mo", "1y", "2y", "5y", "10y", "max"], "default": "1y"},
                    "start_date": {"type": "string", "description": "Optional start date YYYY-MM-DD"},
                    "end_date": {"type": "string", "description": "Optional end date YYYY-MM-DD"},
                    "file_path": {"type": "string", "description": "Output CSV file path"},
                    "use_yfinance": {"type": "boolean", "default": False, "description": "Use yfinance instead of akshare"},
                },
                "required": ["ticker", "file_path"],
            },
        ),
        Tool(
            name="query_worldbank",
            description="Query World Bank macroeconomic indicators. Output is written to file_path as CSV.",
            inputSchema={
                "type": "object",
                "properties": {
                    "indicator": {"type": "string", "description": "World Bank indicator code, e.g. NY.GDP.MKTP.CD"},
                    "country": {"type": "string", "description": "Country code(s) comma-separated, e.g. CHN,USA or all"},
                    "start_year": {"type": "integer", "description": "Start year"},
                    "end_year": {"type": "integer", "description": "End year"},
                    "file_path": {"type": "string", "description": "Output CSV file path"},
                },
                "required": ["indicator", "country", "start_year", "end_year", "file_path"],
            },
        ),
        Tool(
            name="query_arxiv",
            description="Search arXiv papers. Output is written to file_path as CSV.",
            inputSchema={
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "Search query"},
                    "max_results": {"type": "integer", "default": 10, "description": "Max number of results"},
                    "sort_by": {"type": "string", "enum": ["relevance", "submitted", "last_updated"], "default": "relevance"},
                    "file_path": {"type": "string", "description": "Output CSV file path"},
                },
                "required": ["query", "file_path"],
            },
        ),
        Tool(
            name="query_bond",
            description=(
                "Query China onshore bonds. Output is written to file_path as CSV. "
                "kind=yield_curve: 国债到期收益率曲线 (bond_china_yield). "
                "kind=issue_info: 信用债发行信息含评级 (bond_info_cm). "
                "kind=credit_daily: 信用债交易所日行情 (bond_zh_hs_daily). "
                "已知限制(akshare免费层无): 中债估值YTM/全价、赎回回售条款详情、剩余期限、城投发行人财务。"
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "kind": {"type": "string", "enum": ["yield_curve", "issue_info", "credit_daily"], "description": "Query type"},
                    "file_path": {"type": "string", "description": "Output CSV file path"},
                    "start_date": {"type": "string", "description": "Start date YYYY-MM-DD (yield_curve/credit_daily)"},
                    "end_date": {"type": "string", "description": "End date YYYY-MM-DD (yield_curve/credit_daily)"},
                    "bond_code": {"type": "string", "description": "Bond code e.g. 2180495.IB or 2180495 (issue_info, mutually exclusive with bond_issue)"},
                    "bond_issue": {"type": "string", "description": "Issuer name e.g. 成都东方广益 (issue_info, returns latest bond by issue date, mutually exclusive with bond_code)"},
                    "symbol": {"type": "string", "description": "Exchange bond symbol e.g. sh019623 (credit_daily)"},
                },
                "required": ["kind", "file_path"],
            },
        ),
        Tool(
            name="query_convertible_bond",
            description=(
                "Query China convertible bonds. Output is written to file_path as CSV. "
                "kind=overview: 全市场一览含转股溢价率/评级/规模 (bond_zh_cov). "
                "kind=terms: 强赎/回售/下修条款+剩余期限 (集思录). "
                "kind=history: 单只转债历史K线 daily/min (bond_zh_hs_cov_daily/min). "
                "kind=issuer_finance: 发行人正股三大报表;城投/非上市发行人返回引导性提示。"
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "kind": {"type": "string", "enum": ["overview", "terms", "history", "issuer_finance"], "description": "Query type"},
                    "file_path": {"type": "string", "description": "Output CSV file path"},
                    "symbol": {"type": "string", "description": "CB symbol e.g. sz128039 (history)"},
                    "start_date": {"type": "string", "description": "Start date YYYY-MM-DD (history)"},
                    "end_date": {"type": "string", "description": "End date YYYY-MM-DD (history)"},
                    "period": {"type": "string", "enum": ["daily", "min"], "default": "daily", "description": "K-line period (history)"},
                    "bond_code": {"type": "string", "description": "CB code (issuer_finance, mutually exclusive with stock_code)"},
                    "stock_code": {"type": "string", "description": "Underlying stock code (issuer_finance, mutually exclusive with bond_code)"},
                    "report_type": {"type": "string", "enum": ["资产负债表", "利润表", "现金流量表"], "default": "资产负债表", "description": "Financial report type (issuer_finance)"},
                    "keyword": {"type": "string", "description": "Keyword filter (overview, optional)"},
                },
                "required": ["kind", "file_path"],
            },
        ),
        Tool(
            name="resolve_stock_code",
            description=(
                "Resolve A-share stock code by company name (abbreviation or full name). "
                "Output is written to file_path as CSV with candidate rows (代码+名称). "
                "简称精确命中;全称能命中简称子串则返回;城投/非上市发行人返回空候选。"
                "多候选时 Agent/用户从中选,再调 query_stock 查行情。"
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "keyword": {"type": "string", "description": "Stock name or keyword, e.g. 茅台 / 贵州茅台酒股份有限公司"},
                    "file_path": {"type": "string", "description": "Output CSV file path"},
                },
                "required": ["keyword", "file_path"],
            },
        ),
        Tool(
            name="query_futures",
            description=(
                "Query China futures. Output is written to file_path as CSV. "
                "kind=hist: 单合约/主连日线全历史(主连自品种上市日或2005-01-04起,IF0特例仅2017-01-17起; period=min 约4交易日需起止日期). "
                "kind=contracts: 品种挂牌合约清单(如 IM/RB). "
                "分钟超覆盖时明确报错并给补数指引,不静默降级."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "symbol": {"type": "string", "description": "Contract e.g. IM2612, main IM0, or variety IM (contracts)"},
                    "file_path": {"type": "string", "description": "Output CSV file path"},
                    "kind": {"type": "string", "enum": ["hist", "contracts"], "default": "hist", "description": "Query type"},
                    "period": {"type": "string", "enum": ["daily", "min"], "default": "daily", "description": "K-line period (hist)"},
                    "freq": {"type": "string", "enum": ["1", "5", "15", "30", "60"], "default": "1", "description": "Minute granularity (period=min)"},
                    "start_date": {"type": "string", "description": "Start date YYYY-MM-DD"},
                    "end_date": {"type": "string", "description": "End date YYYY-MM-DD"},
                    "trade_date": {"type": "string", "description": "Trade date YYYY-MM-DD (contracts, default today; DCE/GFEX 品种忽略此参数,返回当前挂牌)"},
                },
                "required": ["symbol", "file_path"],
            },
        ),
        Tool(
            name="query_index",
            description=(
                "Query China indices. Output is written to file_path as CSV. "
                "000xxx/399xxx 走新浪(日线自2014起); 930xxx/950xxx 中证系列走官网(慢约10秒). "
                "period=min 仅沪深指数(腾讯源约8交易日). 分钟超覆盖时明确报错并给补数指引."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "symbol": {"type": "string", "description": "Index code e.g. 000852, sh000300, 930050"},
                    "file_path": {"type": "string", "description": "Output CSV file path"},
                    "period": {"type": "string", "enum": ["daily", "min"], "default": "daily", "description": "K-line period"},
                    "freq": {"type": "string", "enum": ["1", "5", "15", "30", "60"], "default": "1", "description": "Minute granularity (period=min)"},
                    "start_date": {"type": "string", "description": "Start date YYYY-MM-DD"},
                    "end_date": {"type": "string", "description": "End date YYYY-MM-DD"},
                },
                "required": ["symbol", "file_path"],
            },
        ),
        Tool(
            name="query_etf",
            description=(
                "Query China onshore-listed ETF. Output is written to file_path as CSV. "
                "daily 自约2012年起(新浪,无复权返回原始价); min 腾讯源约8交易日. "
                "分钟超覆盖时明确报错并给补数指引."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "symbol": {"type": "string", "description": "ETF code e.g. 510300 or sh510300"},
                    "file_path": {"type": "string", "description": "Output CSV file path"},
                    "period": {"type": "string", "enum": ["daily", "min"], "default": "daily", "description": "K-line period"},
                    "freq": {"type": "string", "enum": ["1", "5", "15", "30", "60"], "default": "1", "description": "Minute granularity (period=min)"},
                    "start_date": {"type": "string", "description": "Start date YYYY-MM-DD"},
                    "end_date": {"type": "string", "description": "End date YYYY-MM-DD"},
                },
                "required": ["symbol", "file_path"],
            },
        ),
        Tool(
            name="query_options",
            description=(
                "Query China options (SSE ETF options + CFFEX index options IO/HO/MO). Output is written to file_path as CSV. "
                "kind=months: 标的到期月份. kind=contracts: 当月合约清单. kind=hist: 单合约日线. "
                "本轮仅日线; 找合约代码先用 months/contracts."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "kind": {"type": "string", "enum": ["months", "contracts", "hist"], "description": "Query type"},
                    "file_path": {"type": "string", "description": "Output CSV file path"},
                    "underlying": {"type": "string", "description": "Underlying: 50ETF/300ETF/500ETF/科创50ETF/IO/HO/MO (months/contracts)"},
                    "symbol": {"type": "string", "description": "Option contract code e.g. 10003889 or IO2706-P-5600 (hist)"},
                    "start_date": {"type": "string", "description": "Start date YYYY-MM-DD (hist)"},
                    "end_date": {"type": "string", "description": "End date YYYY-MM-DD (hist)"},
                    "trade_date": {"type": "string", "description": "Trade date YYYY-MM-DD (contracts/CFFEX, default today)"},
                },
                "required": ["kind", "file_path"],
            },
        ),
        Tool(
            name="query_global_rates",
            description=(
                "Query global rates for backtesting. Output is written to file_path as CSV. "
                "kind=us_treasury: 美债收益率(2/5/10/30Y 及 10Y-2Y 利差,1990 起;tenure 选期限,短端期限仅近 1000 交易日). "
                "kind=fed_rate: 美联储 EFFR 日频有效联邦基金利率(纽约联储 API,2000-07 起). "
                "kind=dxy: 美元指数(东财失败自动回退 Yahoo). "
                "kind=vix: VIX 波动率指数(CBOE 直连,1990 起)."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "kind": {"type": "string", "enum": ["us_treasury", "fed_rate", "dxy", "vix"], "description": "Query type"},
                    "file_path": {"type": "string", "description": "Output CSV file path"},
                    "start_date": {"type": "string", "description": "Start date YYYY-MM-DD"},
                    "end_date": {"type": "string", "description": "End date YYYY-MM-DD"},
                    "tenure": {"type": "string", "enum": ["all", "2y", "5y", "10y", "30y", "1m", "3m", "4m", "6m", "1y", "7y", "20y"], "description": "Treasury tenure (us_treasury only, default all)"},
                },
                "required": ["kind", "file_path"],
            },
        ),
        Tool(
            name="query_fx",
            description=(
                "Query FX rates. Output is written to file_path as CSV. "
                "kind=mid: 央行人民币中间价(单位为 100 外币,自 1994 起;currency 过滤币种如 usd,eur). "
                "kind=bochina: 中行牌价(约 2012 起,symbol 用币种中文名如 美元;起止日期必填,长区间分页拉取较慢). "
                "kind=usdcnh: 离岸人民币 USDCNH 日线(Yahoo). "
                "kind=cross: 交叉盘日线,pair 如 EUR/USD(Yahoo,不可达时明确报错)."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "kind": {"type": "string", "enum": ["mid", "bochina", "usdcnh", "cross"], "description": "Query type"},
                    "file_path": {"type": "string", "description": "Output CSV file path"},
                    "currency": {"type": "string", "description": "Comma-separated currency codes (mid only), e.g. usd,eur; default all 25"},
                    "symbol": {"type": "string", "description": "Currency Chinese name (bochina only), e.g. 美元; note 港币 not 港元"},
                    "pair": {"type": "string", "description": "FX pair (cross only), e.g. EUR/USD or EURUSD"},
                    "start_date": {"type": "string", "description": "Start date YYYY-MM-DD (required for bochina)"},
                    "end_date": {"type": "string", "description": "End date YYYY-MM-DD (required for bochina)"},
                },
                "required": ["kind", "file_path"],
            },
        ),
        Tool(
            name="query_spot",
            description=(
                "Query spot prices. Output is written to file_path as CSV. "
                "kind=sge: 上金所贵金属现货日线 date,open,high,low,close(2016-12 起约 10 年深度,"
                "symbol 必填如 Au99.99/Ag99.99/Au(T+D)). "
                "kind=sy: 生意社大宗现货含主力合约价与基差(symbols 如 ['CU','RB'];"
                "起止日期必填,逐日抓取较慢,单次区间最长 1 年)."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "kind": {"type": "string", "enum": ["sge", "sy"], "description": "Query type"},
                    "file_path": {"type": "string", "description": "Output CSV file path"},
                    "symbol": {"type": "string", "description": "SGE variety, e.g. Au99.99, Ag99.99, Au(T+D) (sge only, required)"},
                    "symbols": {"type": "array", "items": {"type": "string"}, "description": "100ppi variety codes, e.g. [\"CU\", \"RB\"] (sy only, required)"},
                    "start_date": {"type": "string", "description": "Start date YYYY-MM-DD (required for sy; optional filter for sge)"},
                    "end_date": {"type": "string", "description": "End date YYYY-MM-DD (required for sy; optional filter for sge)"},
                },
                "required": ["kind", "file_path"],
            },
        ),
        Tool(
            name="align_series",
            description=(
                "把本库产出的多份 CSV 按日期对齐合并成一张宽表(默认各取 close 列),"
                "支持并集/交集、前向填充、重采样到周(周五)/月(取期末交易日);"
                "纯本地计算,不联网。输出写入 file_path 为 CSV。"
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "file_paths": {"type": "array", "items": {"type": "string"}, "description": "Input CSV paths (>= 2) produced by this library; first column must be date/datetime/日期"},
                    "file_path": {"type": "string", "description": "Output CSV file path"},
                    "columns": {"type": "array", "items": {"type": "string"}, "description": "Value column per input file, aligned with file_paths; default close for each"},
                    "names": {"type": "array", "items": {"type": "string"}, "description": "Output column name per input file, aligned with file_paths; default file name stem"},
                    "align": {"type": "string", "enum": ["outer", "inner"], "default": "outer", "description": "Join on date: outer (union, missing = NaN) or inner (intersection)"},
                    "fill": {"type": "string", "enum": ["none", "ffill"], "default": "none", "description": "Forward-fill value columns after join (leading NaN stays NaN)"},
                    "resample": {"type": "string", "enum": ["none", "week", "month"], "default": "none", "description": "Per-series resample before join: week (W-FRI) or month; keeps each period's last actual trading day"},
                },
                "required": ["file_paths", "file_path"],
            },
        ),
    ]


async def handle_call_tool(name: str, arguments: dict[str, Any]) -> list[TextContent]:
    """根据 tool 名称路由到对应 provider 并返回结果。"""
    try:
        if name == "query_stock":
            _, summary = query_stock(**arguments)
        elif name == "query_yfinance":
            config = load_config()
            use_yfinance = arguments.pop("use_yfinance", config.providers.yahoo.use_yfinance)
            _, summary = query_yfinance(use_yfinance=use_yfinance, **arguments)
        elif name == "query_worldbank":
            _, summary = query_worldbank(**arguments)
        elif name == "query_arxiv":
            _, summary = query_arxiv(**arguments)
        elif name == "query_bond":
            _, summary = query_bond(**arguments)
        elif name == "query_convertible_bond":
            _, summary = query_convertible_bond(**arguments)
        elif name == "resolve_stock_code":
            _, summary = resolve_stock_code(**arguments)
        elif name == "query_futures":
            _, summary = query_futures(**arguments)
        elif name == "query_index":
            _, summary = query_index(**arguments)
        elif name == "query_etf":
            _, summary = query_etf(**arguments)
        elif name == "query_options":
            _, summary = query_options(**arguments)
        elif name == "query_global_rates":
            _, summary = query_global_rates(**arguments)
        elif name == "query_fx":
            _, summary = query_fx(**arguments)
        elif name == "query_spot":
            _, summary = query_spot(**arguments)
        elif name == "align_series":
            _, summary = align_series(**arguments)
        else:
            raise ValueError(f"Unknown tool: {name}")
        return [TextContent(type="text", text=summary)]
    except Exception as e:
        return [TextContent(type="text", text=f"Error calling {name}: {e}")]


async def _main() -> None:
    """异步主函数：初始化 MCP 服务器并运行 stdio 服务。"""
    server = Server(APP_NAME)

    @server.list_tools()
    async def list_tools() -> list[Tool]:
        return build_tools()

    @server.call_tool()
    async def call_tool(name: str, arguments: dict[str, Any]) -> list[TextContent]:
        return await handle_call_tool(name, arguments)

    async with stdio_server() as (read_stream, write_stream):
        await server.run(
            read_stream,
            write_stream,
            server.create_initialization_options(),
        )


def main() -> None:
    """同步入口：console script 直接调用此函数。

    ``local-datasource download ...`` 转交 download 批量下载 CLI;
    无参数(或其它参数)时保持原行为:启动 MCP stdio server。
    """
    if len(sys.argv) > 1 and sys.argv[1] == "download":
        from local_datasource.cli import run_download

        raise SystemExit(run_download(sys.argv[2:]))
    asyncio.run(_main())


if __name__ == "__main__":
    main()
