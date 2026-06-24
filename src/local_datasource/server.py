"""MCP Server 入口。

注册 4 个数据查询 tool：
- ``query_stock``：A 股 / 港股 / 美股
- ``query_yfinance``：美股/全球资产（默认 akshare，可选 yfinance）
- ``query_worldbank``：世界银行宏观指标
- ``query_arxiv``：arXiv 学术论文

通过标准 MCP stdio 协议与 Agent 通信。
"""
from __future__ import annotations

import asyncio
from typing import Any

from mcp.server.stdio import stdio_server
from mcp.types import (
    TextContent,
    Tool,
)
from mcp.server import Server

from local_datasource.config import load_config
from local_datasource.providers.arxiv import query_arxiv
from local_datasource.providers.stock import query_stock
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
    """同步入口：console script 直接调用此函数。"""
    asyncio.run(_main())


if __name__ == "__main__":
    main()
