# Local Datasource MCP Skill — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a local, no-login-required MCP server that reproduces the core data-query capabilities of Kimi Datasource for A-share/HK/US stocks, Yahoo-like global finance, World Bank macro data, and arXiv papers.

**Architecture:** A Python MCP server exposes 4 tools. Each tool routes to a small provider module that wraps `akshare`/`wbgapi`/`arxiv` (and optionally `yfinance`). Results are normalized to CSV and written to a user-supplied `file_path`. A `SKILL.md` teaches any MCP-capable agent how to call the tools.

**Tech Stack:** Python 3.10+, `mcp` Python SDK, `akshare`, `yfinance` (fallback), `wbgapi`, `arxiv`, `pandas`, `pyyaml`.

---

## File Map

| File | Responsibility |
|---|---|
| `pyproject.toml` | Package metadata, dependencies, console script entry point |
| `config.yaml` | Optional provider configuration (API keys, fallback flags) |
| `src/config.py` | Load `config.yaml`, expose typed settings |
| `src/formatters.py` | Convert provider DataFrames/dicts to CSV preview text |
| `src/providers/stock.py` | A-share/HK/US historical prices via akshare |
| `src/providers/yahoo.py` | US/global tickers; default to akshare, fallback to yfinance |
| `src/providers/worldbank.py` | World Bank indicators via wbgapi |
| `src/providers/arxiv.py` | arXiv search via `arxiv` library |
| `src/server.py` | MCP server, tool definitions, request routing |
| `SKILL.md` | Agent instructions: tool names, params, code rules, examples |
| `README.md` | Install and Agent configuration guide |
| `tests/test_*.py` | Unit + integration tests |

---

### Task 1: Initialize Python project structure

**Files:**
- Create: `pyproject.toml`
- Create: `src/local_datasource/__init__.py`
- Create: `src/local_datasource/providers/__init__.py`
- Create: `tests/__init__.py`

- [ ] **Step 1: Write `pyproject.toml`**

```toml
[project]
name = "local-datasource"
version = "0.1.0"
description = "Local MCP server for financial, macro, and academic data"
requires-python = ">=3.10"
dependencies = [
    "mcp>=1.6.0",
    "akshare>=1.18.0",
    "yfinance>=0.2.54",
    "wbgapi>=1.0.12",
    "arxiv>=2.1.0",
    "pandas>=2.0.0",
    "pyyaml>=6.0",
]

[project.scripts]
local-datasource = "local_datasource.server:main"

[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"
```

- [ ] **Step 2: Create package directories**

Run:

```bash
mkdir -p src/local_datasource/providers tests
```

- [ ] **Step 3: Commit**

```bash
git add pyproject.toml src/local_datasource/__init__.py src/local_datasource/providers/__init__.py tests/__init__.py
git commit -m "chore: initialize local-datasource package"
```

---

### Task 2: Configuration loader

**Files:**
- Create: `src/local_datasource/config.py`
- Test: `tests/test_config.py`

- [ ] **Step 1: Write failing test**

```python
# tests/test_config.py
from local_datasource.config import load_config

def test_load_default_config():
    cfg = load_config(None)
    assert cfg.providers.yahoo.enabled is True
    assert cfg.providers.yahoo.use_yfinance is False
```

- [ ] **Step 2: Run test to verify it fails**

Run:

```bash
python -m pytest tests/test_config.py -v
```

Expected: `ModuleNotFoundError` or `AttributeError`.

- [ ] **Step 3: Implement `config.py`**

```python
# src/local_datasource/config.py
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml


@dataclass
class YahooConfig:
    enabled: bool = True
    use_yfinance: bool = False  # default to akshare; yfinance is fallback


@dataclass
class ProvidersConfig:
    yahoo: YahooConfig = field(default_factory=YahooConfig)


@dataclass
class Config:
    providers: ProvidersConfig = field(default_factory=ProvidersConfig)


def _merge_defaults(data: dict[str, Any]) -> Config:
    yahoo = YahooConfig(**data.get("providers", {}).get("yahoo", {}))
    return Config(providers=ProvidersConfig(yahoo=yahoo))


def load_config(path: str | None = None) -> Config:
    if path is None:
        candidate = Path("config.yaml")
        if candidate.exists():
            path = str(candidate)
        else:
            env_path = os.environ.get("LOCAL_DATASOURCE_CONFIG")
            path = env_path

    if not path or not Path(path).exists():
        return _merge_defaults({})

    with open(path, "r", encoding="utf-8") as f:
        raw = yaml.safe_load(f) or {}

    return _merge_defaults(raw)
```

- [ ] **Step 4: Run test to verify it passes**

Run:

```bash
python -m pytest tests/test_config.py -v
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/local_datasource/config.py tests/test_config.py config.yaml
[ -f config.yaml ] || echo "providers:" > config.yaml
git add config.yaml
git commit -m "feat: add configuration loader"
```

---

### Task 3: Output formatter

**Files:**
- Create: `src/local_datasource/formatters.py`
- Test: `tests/test_formatters.py`

- [ ] **Step 1: Write failing test**

```python
# tests/test_formatters.py
import pandas as pd
from local_datasource.formatters import format_csv_output

def test_format_csv_output():
    df = pd.DataFrame({"a": [1, 2, 3], "b": [4, 5, 6]})
    path, preview = format_csv_output(df, "/tmp/test.csv")
    assert path == "/tmp/test.csv"
    assert "a,b" in preview
```

- [ ] **Step 2: Run test to verify it fails**

Run:

```bash
python -m pytest tests/test_formatters.py -v
```

Expected: `ModuleNotFoundError`.

- [ ] **Step 3: Implement `formatters.py`**

```python
# src/local_datasource/formatters.py
from pathlib import Path

import pandas as pd


def format_csv_output(df: pd.DataFrame, file_path: str, preview_rows: int = 5) -> tuple[str, str]:
    path = Path(file_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(path, index=False, encoding="utf-8-sig")

    preview_df = df.head(preview_rows)
    preview = preview_df.to_csv(index=False, encoding="utf-8-sig").strip()

    summary = f"CSV written to {file_path}\nRows: {len(df)}, Columns: {len(df.columns)}\nPreview:\n{preview}"
    return file_path, summary
```

- [ ] **Step 4: Run test to verify it passes**

Run:

```bash
python -m pytest tests/test_formatters.py -v
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/local_datasource/formatters.py tests/test_formatters.py
git commit -m "feat: add CSV formatter"
```

---

### Task 4: Stock provider (A-share / HK / US)

**Files:**
- Create: `src/local_datasource/providers/stock.py`
- Test: `tests/test_stock.py`

- [ ] **Step 1: Write integration test**

```python
# tests/test_stock.py
import os
import tempfile

import pytest

from local_datasource.providers.stock import query_stock


@pytest.mark.skipif(os.environ.get("SKIP_INTEGRATION"), reason="integration")
def test_query_stock_a_share():
    with tempfile.NamedTemporaryFile(suffix=".csv", delete=False) as f:
        path = f.name
    try:
        file_path, preview = query_stock("600519", market="a", start_date="2025-06-01", end_date="2026-06-24", file_path=path)
        assert os.path.exists(file_path)
        assert "Rows:" in preview
    finally:
        os.unlink(path)


def test_query_stock_normalizes_code():
    from local_datasource.providers import stock
    assert stock._normalize_a_code("600519") == "sh600519"
    assert stock._normalize_hk_code("00700") == "00700"
    assert stock._normalize_us_code("AAPL") == "AAPL"
```

- [ ] **Step 2: Run test to verify it fails**

Run:

```bash
python -m pytest tests/test_stock.py::test_query_stock_normalizes_code -v
```

Expected: `ModuleNotFoundError`.

- [ ] **Step 3: Implement `stock.py`**

```python
# src/local_datasource/providers/stock.py
from __future__ import annotations

import re
from datetime import datetime
from typing import Literal

import akshare as ak
import pandas as pd

from local_datasource.formatters import format_csv_output


Market = Literal["a", "hk", "us"]


def _normalize_a_code(ticker: str) -> str:
    code = re.sub(r"\.(sh|sz|bj)$", "", ticker, flags=re.IGNORECASE)
    if code.startswith(("6", "5", "9")):
        return f"sh{code}"
    if code.startswith(("0", "1", "2", "3")):
        return f"sz{code}"
    if code.startswith(("4", "8", "43")):
        return f"bj{code}"
    return code


def _normalize_hk_code(ticker: str) -> str:
    return re.sub(r"\.hk$", "", ticker, flags=re.IGNORECASE).zfill(5)


def _normalize_us_code(ticker: str) -> str:
    return ticker.upper()


def query_stock(
    ticker: str,
    market: Market,
    start_date: str,
    end_date: str,
    file_path: str,
    adjust: str = "qfq",
) -> tuple[str, str]:
    start_fmt = datetime.strptime(start_date, "%Y-%m-%d").strftime("%Y%m%d")
    end_fmt = datetime.strptime(end_date, "%Y-%m-%d").strftime("%Y%m%d")

    if market == "a":
        symbol = _normalize_a_code(ticker)
        df = ak.stock_zh_a_daily(symbol=symbol, start_date=start_fmt, end_date=end_fmt, adjust=adjust)
    elif market == "hk":
        symbol = _normalize_hk_code(ticker)
        df = ak.stock_hk_daily(symbol=symbol)
        df = df[(df["date"] >= start_date) & (df["date"] <= end_date)].copy()
    elif market == "us":
        symbol = _normalize_us_code(ticker)
        df = ak.stock_us_daily(symbol=symbol)
        df = df[(df["date"] >= start_date) & (df["date"] <= end_date)].copy()
    else:
        raise ValueError(f"Unsupported market: {market}")

    if df.empty:
        raise ValueError(f"No data returned for {ticker} ({market}) between {start_date} and {end_date}")

    return format_csv_output(df, file_path)
```

- [ ] **Step 4: Run tests**

Run:

```bash
python -m pytest tests/test_stock.py::test_query_stock_normalizes_code -v
SKIP_INTEGRATION= python -m pytest tests/test_stock.py::test_query_stock_a_share -v
```

Expected: both PASS.

- [ ] **Step 5: Commit**

```bash
git add src/local_datasource/providers/stock.py tests/test_stock.py
git commit -m "feat: add stock provider for A/HK/US markets"
```

---

### Task 5: Yahoo-like provider

**Files:**
- Create: `src/local_datasource/providers/yahoo.py`
- Test: `tests/test_yahoo.py`

- [ ] **Step 1: Write integration test**

```python
# tests/test_yahoo.py
import os
import tempfile

import pytest

from local_datasource.providers.yahoo import query_yfinance


@pytest.mark.skipif(os.environ.get("SKIP_INTEGRATION"), reason="integration")
def test_query_yfinance_default_akshare():
    with tempfile.NamedTemporaryFile(suffix=".csv", delete=False) as f:
        path = f.name
    try:
        file_path, preview = query_yfinance("AAPL", period="1y", file_path=path, use_yfinance=False)
        assert os.path.exists(file_path)
        assert "Rows:" in preview
    finally:
        os.unlink(path)
```

- [ ] **Step 2: Run test to verify it fails**

Run:

```bash
python -m pytest tests/test_yahoo.py -v
```

Expected: `ModuleNotFoundError`.

- [ ] **Step 3: Implement `yahoo.py`**

```python
# src/local_datasource/providers/yahoo.py
from __future__ import annotations

from datetime import datetime, timedelta
from typing import Literal

import akshare as ak
import pandas as pd
import yfinance as yf

from local_datasource.formatters import format_csv_output


Period = Literal["1d", "5d", "1mo", "3mo", "6mo", "1y", "2y", "5y", "10y", "max"]

_PERIOD_DAYS = {
    "1d": 1,
    "5d": 5,
    "1mo": 30,
    "3mo": 90,
    "6mo": 180,
    "1y": 365,
    "2y": 730,
    "5y": 1825,
    "10y": 3650,
    "max": 36500,
}


def _period_to_dates(period: Period, end_date: datetime | None = None) -> tuple[str, str]:
    end = end_date or datetime.now()
    days = _PERIOD_DAYS.get(period, 365)
    start = end - timedelta(days=days)
    return start.strftime("%Y-%m-%d"), end.strftime("%Y-%m-%d")


def _query_akshare(ticker: str, start_date: str, end_date: str) -> pd.DataFrame:
    df = ak.stock_us_daily(symbol=ticker.upper())
    df = df[(df["date"] >= start_date) & (df["date"] <= end_date)].copy()
    if df.empty:
        raise ValueError(f"No akshare data for {ticker}")
    return df


def _query_yfinance(ticker: str, period: Period, start_date: str | None, end_date: str | None) -> pd.DataFrame:
    kwargs: dict = {"progress": False}
    if start_date and end_date:
        kwargs["start"] = start_date
        kwargs["end"] = end_date
    else:
        kwargs["period"] = period

    df = yf.download(ticker.upper(), **kwargs)
    if df.empty:
        raise ValueError(f"No yfinance data for {ticker}")

    # flatten multi-index columns if present
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = [" ".join(col).strip() for col in df.columns.values]

    df = df.reset_index()
    return df


def query_yfinance(
    ticker: str,
    period: Period = "1y",
    file_path: str = "",
    start_date: str | None = None,
    end_date: str | None = None,
    use_yfinance: bool = False,
) -> tuple[str, str]:
    if start_date and end_date:
        s, e = start_date, end_date
    else:
        s, e = _period_to_dates(period)

    if use_yfinance:
        df = _query_yfinance(ticker, period, start_date, end_date)
    else:
        try:
            df = _query_akshare(ticker, s, e)
        except Exception as ex:
            raise RuntimeError(f"akshare failed for {ticker}: {ex}. Try use_yfinance=True or check the ticker.") from ex

    return format_csv_output(df, file_path)
```

- [ ] **Step 4: Run tests**

Run:

```bash
python -m pytest tests/test_yahoo.py -v
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/local_datasource/providers/yahoo.py tests/test_yahoo.py
git commit -m "feat: add yahoo-finance provider with akshare default"
```

---

### Task 6: World Bank provider

**Files:**
- Create: `src/local_datasource/providers/worldbank.py`
- Test: `tests/test_worldbank.py`

- [ ] **Step 1: Write integration test**

```python
# tests/test_worldbank.py
import os
import tempfile

import pytest

from local_datasource.providers.worldbank import query_worldbank


@pytest.mark.skipif(os.environ.get("SKIP_INTEGRATION"), reason="integration")
def test_query_worldbank_gdp():
    with tempfile.NamedTemporaryFile(suffix=".csv", delete=False) as f:
        path = f.name
    try:
        file_path, preview = query_worldbank("NY.GDP.MKTP.CD", country="CHN", start_year=2020, end_year=2023, file_path=path)
        assert os.path.exists(file_path)
        assert "CHN" in preview or "2020" in preview
    finally:
        os.unlink(path)
```

- [ ] **Step 2: Run test to verify it fails**

Run:

```bash
python -m pytest tests/test_worldbank.py -v
```

Expected: `ModuleNotFoundError`.

- [ ] **Step 3: Implement `worldbank.py`**

```python
# src/local_datasource/providers/worldbank.py
from __future__ import annotations

import wbgapi as wb
from local_datasource.formatters import format_csv_output


def query_worldbank(
    indicator: str,
    country: str,
    start_year: int,
    end_year: int,
    file_path: str,
) -> tuple[str, str]:
    if end_year < start_year:
        raise ValueError("end_year must be >= start_year")

    country_list = [c.strip().upper() for c in country.split(",")]
    if country_list == ["ALL"]:
        country_list = "all"

    df = wb.data.DataFrame(indicator, country_list, time=range(start_year, end_year + 1))
    df = df.reset_index()

    if df.empty:
        raise ValueError(f"No World Bank data for indicator {indicator}")

    return format_csv_output(df, file_path)
```

- [ ] **Step 4: Run tests**

Run:

```bash
python -m pytest tests/test_worldbank.py -v
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/local_datasource/providers/worldbank.py tests/test_worldbank.py
git commit -m "feat: add world bank provider"
```

---

### Task 7: arXiv provider

**Files:**
- Create: `src/local_datasource/providers/arxiv.py`
- Test: `tests/test_arxiv.py`

- [ ] **Step 1: Write integration test**

```python
# tests/test_arxiv.py
import os
import tempfile

import pytest

from local_datasource.providers.arxiv import query_arxiv


@pytest.mark.skipif(os.environ.get("SKIP_INTEGRATION"), reason="integration")
def test_query_arxiv():
    with tempfile.NamedTemporaryFile(suffix=".csv", delete=False) as f:
        path = f.name
    try:
        file_path, preview = query_arxiv("machine learning", max_results=3, file_path=path)
        assert os.path.exists(file_path)
        assert "title" in preview.lower()
    finally:
        os.unlink(path)
```

- [ ] **Step 2: Run test to verify it fails**

Run:

```bash
python -m pytest tests/test_arxiv.py -v
```

Expected: `ModuleNotFoundError`.

- [ ] **Step 3: Implement `arxiv.py`**

```python
# src/local_datasource/providers/arxiv.py
from __future__ import annotations

from typing import Literal

import arxiv
import pandas as pd

from local_datasource.formatters import format_csv_output


SortBy = Literal["relevance", "submitted", "last_updated"]

_SORT_MAP = {
    "relevance": arxiv.SortCriterion.Relevance,
    "submitted": arxiv.SortCriterion.SubmittedDate,
    "last_updated": arxiv.SortCriterion.LastUpdatedDate,
}


def query_arxiv(
    query: str,
    file_path: str,
    max_results: int = 10,
    sort_by: SortBy = "relevance",
) -> tuple[str, str]:
    client = arxiv.Client()
    search = arxiv.Search(
        query=query,
        max_results=max_results,
        sort_by=_SORT_MAP.get(sort_by, arxiv.SortCriterion.Relevance),
    )

    rows = []
    for paper in client.results(search):
        rows.append({
            "title": paper.title,
            "authors": ", ".join(str(a) for a in paper.authors),
            "published": paper.published.isoformat() if paper.published else "",
            "updated": paper.updated.isoformat() if paper.updated else "",
            "summary": paper.summary[:500],
            "pdf_url": paper.pdf_url,
            "entry_id": paper.entry_id,
        })

    if not rows:
        raise ValueError(f"No arXiv papers found for query: {query}")

    df = pd.DataFrame(rows)
    return format_csv_output(df, file_path)
```

- [ ] **Step 4: Run tests**

Run:

```bash
python -m pytest tests/test_arxiv.py -v
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/local_datasource/providers/arxiv.py tests/test_arxiv.py
git commit -m "feat: add arxiv provider"
```

---

### Task 8: MCP Server

**Files:**
- Create: `src/local_datasource/server.py`
- Test: `tests/test_server.py`

- [ ] **Step 1: Write failing test**

```python
# tests/test_server.py
from local_datasource.server import build_tools


def test_build_tools_count():
    tools = build_tools()
    assert len(tools) == 4
    names = {t.name for t in tools}
    assert names == {"query_stock", "query_yfinance", "query_worldbank", "query_arxiv"}
```

- [ ] **Step 2: Run test to verify it fails**

Run:

```bash
python -m pytest tests/test_server.py -v
```

Expected: `ModuleNotFoundError`.

- [ ] **Step 3: Implement `server.py`**

```python
# src/local_datasource/server.py
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


async def main() -> None:
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


if __name__ == "__main__":
    asyncio.run(main())
```

- [ ] **Step 4: Run tests**

Run:

```bash
python -m pytest tests/test_server.py -v
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/local_datasource/server.py tests/test_server.py
git commit -m "feat: add MCP server with four data tools"
```

---

### Task 9: Agent Skill documentation

**Files:**
- Create: `SKILL.md`

- [ ] **Step 1: Write `SKILL.md`**

```markdown
# Local Datasource Skill

Use this skill to query financial market data, macroeconomic indicators, and academic papers from local free APIs — no Kimi login required.

## Available Tools

### `query_stock`

Query historical prices for A-share, Hong Kong, and US stocks.

Parameters:
- `ticker`: stock code (e.g. `600519`, `00700`, `AAPL`)
- `market`: `a` | `hk` | `us`
- `start_date`: `YYYY-MM-DD`
- `end_date`: `YYYY-MM-DD`
- `adjust`: `qfq` (default) | `hfq` | `none`
- `file_path`: output CSV path

Example:
```json
{"ticker": "600519", "market": "a", "start_date": "2025-06-01", "end_date": "2026-06-24", "file_path": "/tmp/moutai.csv"}
```

### `query_yfinance`

Query US/global tickers. By default uses akshare (free, no key). Set `use_yfinance=true` to use Yahoo Finance as a fallback.

Parameters:
- `ticker`: e.g. `AAPL`, `SPY`, `GLD`
- `period`: `1d` | `5d` | `1mo` | `3mo` | `6mo` | `1y` | `2y` | `5y` | `10y` | `max`
- `file_path`: output CSV path
- `use_yfinance`: boolean, default false

### `query_worldbank`

Query World Bank macroeconomic indicators.

Parameters:
- `indicator`: e.g. `NY.GDP.MKTP.CD`
- `country`: country code(s), e.g. `CHN`, `USA`, `CHN,USA`, `all`
- `start_year`: integer
- `end_year`: integer
- `file_path`: output CSV path

### `query_arxiv`

Search arXiv papers.

Parameters:
- `query`: search string
- `max_results`: default 10
- `sort_by`: `relevance` | `submitted` | `last_updated`
- `file_path`: output CSV path

## Rules

1. Always call `get_data_source_desc` equivalent? No — these tools are stable; call them directly.
2. Use `query_stock` for A/HK/US stocks; use `query_yfinance` for US ETFs/global tickers where you need a quick period query.
3. Validate dates are in `YYYY-MM-DD` format before calling.
4. If a query fails due to rate limits, suggest waiting or setting `use_yfinance=true` for `query_yfinance`.
5. Return the CSV preview to the user; do not fabricate data.
```

- [ ] **Step 2: Commit**

```bash
git add SKILL.md
git commit -m "docs: add agent skill instructions"
```

---

### Task 10: User-facing documentation and config file

**Files:**
- Create: `README.md`
- Create: `config.yaml`

- [ ] **Step 1: Write `config.yaml`**

```yaml
providers:
  yahoo:
    # Default uses akshare (free, no key). Set use_yfinance: true to use Yahoo Finance instead.
    use_yfinance: false
```

- [ ] **Step 2: Write `README.md`**

```markdown
# Local Datasource

A local MCP server that replaces Kimi Datasource for basic financial, macro, and academic data queries.

## Install

```bash
pip install -e .
```

## Run as MCP server

```bash
local-datasource
```

## Agent configuration examples

### Claude Code

Add to `claude_mcp_settings.json`:

```json
{
  "mcpServers": {
    "local-datasource": {
      "command": "local-datasource"
    }
  }
}
```

### Codex

Add to `.codex/config.json`:

```json
{
  "mcpServers": {
    "local-datasource": {
      "command": "local-datasource"
    }
  }
}
```

### Kimi Code

Create a plugin with `kimi.plugin.json` declaring this MCP server, or run `local-datasource` directly from `/plugins mcp add`.

## Tools

- `query_stock` — A/HK/US stocks
- `query_yfinance` — US/global tickers (default akshare, optional yfinance)
- `query_worldbank` — World Bank indicators
- `query_arxiv` — arXiv paper search

## Notes

- Yahoo Finance (`yfinance`) may rate-limit your IP. The default uses akshare's US stock data.
- World Bank and arXiv are generally stable without API keys.
```

- [ ] **Step 3: Commit**

```bash
git add README.md config.yaml
git commit -m "docs: add README and default config"
```

---

### Task 11: Run full test suite and integration smoke tests

**Files:**
- None (verification only)

- [ ] **Step 1: Run unit tests**

```bash
python -m pytest tests/ -v --ignore=tests/integration
```

Expected: all unit tests PASS.

- [ ] **Step 2: Run integration smoke tests**

```bash
python -m pytest tests/ -v
```

Expected: all tests PASS (requires network).

- [ ] **Step 3: Verify MCP server starts**

```bash
local-datasource --help || true
```

If `--help` is not implemented, verify stdio behavior with a minimal JSON-RPC call:

```bash
echo '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2024-11-05","capabilities":{},"clientInfo":{"name":"test","version":"1.0"}}}' | local-datasource
```

Expected: server responds with initialization result.

- [ ] **Step 4: Commit or tag**

```bash
git add .
git commit -m "test: add integration smoke tests and verify MCP server"
```

---

## Spec Coverage Check

| Spec Section | Implemented By Task |
|---|---|
| A-share/HK/US stock data | Task 4 |
| Yahoo Finance global data | Task 5 |
| World Bank macro data | Task 6 |
| arXiv papers | Task 7 |
| MCP Server with 4 tools | Task 8 |
| SKILL.md agent instructions | Task 9 |
| Config loader | Task 2 |
| CSV formatter | Task 3 |
| Multi-agent reuse examples | Task 10 |
| Error handling | Tasks 4-8 (try/except + readable messages) |
| Integration testing | Task 11 |

## Placeholder Scan

No TBD, TODO, or vague steps. Every task includes exact file paths, code, and commands.

## Type Consistency

- `query_stock`, `query_yfinance`, `query_worldbank`, `query_arxiv` all return `tuple[str, str]`.
- `format_csv_output` returns `tuple[str, str]`.
- Tool schemas in `server.py` match provider function signatures.
