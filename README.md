# Local Datasource

一个**本地运行的 MCP（Model Context Protocol）数据服务器**。它让任何支持 MCP 的 Agent（Claude Code、Codex、Cursor、OpenCode 等）都能直接查询金融市场、宏观经济和学术论文数据，而无需第三方账号、不消耗云额度、不经过外部中继。

---

## 一句话介绍

`local-datasource` 把 `akshare`、`yfinance`、`wbgapi`、`arxiv` 等免费公开接口封装成 4 个标准 MCP tool，Agent 只需要像调用本地函数一样请求数据，即可获得结构化 CSV 输出。

---

## 为什么需要这个项目

在日常投研、尽调、学术检索或自动化报告生成中，Agent 经常需要实时数据：

- 查一只股票过去一年的走势
- 对比黄金、美股、A股等多资产表现
- 拉取某个国家的 GDP/CPI 数据
- 检索某个领域的 arXiv 论文

这些需求本身并不复杂，但常见方案要么需要登录某个平台并消耗额度，要么把查询请求发到云端。`local-datasource` 希望提供一种**透明、可控、低成本**的替代方案：

- **数据请求不出本机**：适合对合规、隐私敏感的场景。
- **无需账号和额度**：基于公开接口，安装完就能用。
- **标准 MCP 协议**：不绑定任何特定 Agent，可被多家产品复用。
- **源码可见、可扩展**：增加新数据源或调整输出格式都很直接。

---

## 核心特点

- ✅ **A股 / 港股 / 美股**：日线行情，支持前复权/后复权。
- ✅ **美股 / ETF / 全球资产**：默认 `akshare` 美股接口，可回退 `yfinance`。
- ✅ **世界银行宏观指标**：GDP、CPI、人口等。
- ✅ **arXiv 论文搜索**：标题、作者、摘要、PDF 链接结构化输出。
- ✅ **统一 CSV 输出**：每个 tool 都把结果写到 `file_path`，并返回前 5 行预览。
- ✅ **零 API Key**：所有默认数据源均免费使用。
- ✅ **跨 Agent 复用**：标准 MCP Server，配置一条 `command` 即可接入。

---

## 适用人群

- 需要在 Agent 工作流里频繁查数据的投研、分析师、开发者。
- 不希望把查询请求发送到云端的本地优先用户。
- 想学习/定制 MCP 数据服务器实现的开发者。

---

## 快速开始

```bash
# 1. 克隆并安装
pip install -e .

# 2. 启动 MCP 服务
local-datasource

# 3. 在 Agent 的 MCP 配置中添加
{
  "mcpServers": {
    "local-datasource": {
      "command": "local-datasource"
    }
  }
}
```

---

## 覆盖范围

| 数据类型 | 工具 | 底层接口 | 是否需 API Key |
|---|---|---|---|
| A股 / 港股 / 美股 历史行情 | `query_stock` | `akshare` | 否 |
| 美股 / ETF / 全球资产 | `query_yfinance` | `akshare`（默认）/ `yfinance`（备选） | 否 |
| 世界银行宏观指标 | `query_worldbank` | `wbgapi` | 否 |
| arXiv 学术论文 | `query_arxiv` | `arxiv` | 否 |

---

## 架构

```
Agent（Claude Code / Codex / Cursor / OpenCode 等）
        ↓ MCP stdio
local-datasource（本仓库）
        ↓ 直接调用
akshare / yfinance / wbgapi / arxiv
        ↓ 原始数据源
同花顺 / Yahoo Finance / World Bank / arxiv.org
```

---

## 文件结构

```
.
├── SKILL.md                        # Agent 执行手册
├── README.md                       # 项目介绍（本文档）
├── pyproject.toml                  # Python 包配置与依赖
├── config.yaml                     # 可选配置文件
├── src/local_datasource/           # MCP server 源码
│   ├── server.py                   # 服务入口：注册 tools、处理调用
│   ├── config.py                   # 加载 config.yaml / 环境变量
│   ├── formatters.py               # 统一 CSV 输出与预览
│   └── providers/                  # 各数据源适配器
│       ├── stock.py                # A/HK/US 股票
│       ├── yahoo.py                # 美股/全球资产
│       ├── worldbank.py            # 世界银行
│       └── arxiv.py                # arXiv 论文
└── demos/                          # 示例脚本
    └── mcp_query_demo.py           # 多资产查询 + 归一化走势图
```

---

## 依赖

- Python >= 3.10
- `mcp`：MCP 服务器框架
- `akshare`：A股/港股/美股/ETF 行情
- `yfinance`：Yahoo Finance 备选接口
- `wbgapi`：世界银行数据
- `arxiv`：arXiv 论文搜索
- `pandas`：数据处理
- `pyyaml`：配置文件解析

可选：
- `matplotlib`：运行 `demos/mcp_query_demo.py` 绘图

---

## 安装

```bash
pip install -e .
```

安装完成后，`local-datasource` 命令会被加入 PATH。

---

## 启动 MCP 服务

```bash
local-datasource
```

服务通过标准输入输出（stdio）与 Agent 通信。可以用以下命令快速验证是否启动成功：

```bash
echo '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2024-11-05","capabilities":{},"clientInfo":{"name":"test","version":"1.0"}}}' | local-datasource
```

若返回初始化结果，说明服务正常。

---

## Agent 配置示例

任何支持 MCP 的 Agent 都可以通过 `command` 方式调用本服务。

### Claude Code

`claude_mcp_settings.json`：

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

`.codex/config.json`：

```json
{
  "mcpServers": {
    "local-datasource": {
      "command": "local-datasource"
    }
  }
}
```

### Cursor / Windsurf / OpenCode

在对应 MCP 配置中添加：

```json
{
  "mcpServers": {
    "local-datasource": {
      "command": "local-datasource"
    }
  }
}
```

---

## 调用数据案例

### 查询 A 股：贵州茅台

```json
{
  "ticker": "600519",
  "market": "a",
  "start_date": "2025-06-01",
  "end_date": "2026-06-24",
  "file_path": "/tmp/moutai.csv"
}
```

Tool：`query_stock`

### 查询港股：腾讯

```json
{
  "ticker": "00700",
  "market": "hk",
  "start_date": "2025-06-01",
  "end_date": "2026-06-24",
  "file_path": "/tmp/tencent.csv"
}
```

Tool：`query_stock`

### 查询美股/ETF：黄金 GLD

```json
{
  "ticker": "GLD",
  "period": "1y",
  "file_path": "/tmp/gld.csv"
}
```

Tool：`query_yfinance`

默认使用 `akshare` 的美股日线接口；若需要 Yahoo Finance 数据，添加 `"use_yfinance": true`：

```json
{
  "ticker": "AAPL",
  "period": "1y",
  "use_yfinance": true,
  "file_path": "/tmp/aapl_yahoo.csv"
}
```

### 查询世界银行：中国 GDP 现价

```json
{
  "indicator": "NY.GDP.MKTP.CD",
  "country": "CHN",
  "start_year": 2020,
  "end_year": 2023,
  "file_path": "/tmp/china_gdp.csv"
}
```

Tool：`query_worldbank`

### 搜索 arXiv 论文

```json
{
  "query": "large language model retrieval augmented generation",
  "max_results": 10,
  "sort_by": "relevance",
  "file_path": "/tmp/llm_rag.csv"
}
```

Tool：`query_arxiv`

---

## 多资产归一化对比

参考 `demos/mcp_query_demo.py`：它通过 MCP 调用多个工具，读取生成的 CSV，计算归一化价格，并绘制对比图。

```bash
python demos/mcp_query_demo.py
```

输出：
- `demos/outputs/*.csv`：各资产原始行情
- `demos/outputs/normalized_returns.png`：归一化走势图
- `demos/outputs/summary.csv`：汇总表

---

## 配置

项目根目录的 `config.yaml`：

```yaml
providers:
  yahoo:
    # 默认使用 akshare。设为 true 则默认使用 yfinance。
    use_yfinance: false
```

也可通过环境变量指定配置文件：

```bash
LOCAL_DATASOURCE_CONFIG=/path/to/config.yaml local-datasource
```

---

## 扩展新数据源

`src/local_datasource/providers/` 下的每个文件都是一个独立适配器，新增数据源的步骤：

1. 在 `providers/` 新增一个 Python 文件，实现 `query_xxx(...)` 函数，返回 `tuple[str, str]`（文件路径 + 预览文本）。
2. 在 `server.py` 的 `build_tools()` 中注册新 tool。
3. 在 `handle_call_tool()` 中增加路由。
4. 更新 `SKILL.md` 和 `README.md` 的 tool 说明。

---

## 测试

测试文件位于本地 `tests/` 目录（未提交到 GitHub）：

```bash
python -m pytest tests/ -v
```

包含配置加载、格式化、4 个 provider 的集成测试、MCP server 工具注册。

---

## 注意事项

- `yfinance` 容易被 Yahoo Finance 限流，因此默认优先使用 `akshare`。
- `akshare` 的接口可能随时间变化，建议定期更新到较新版本。
- World Bank 和 arXiv 通常稳定且无需 API key。

---

## 与 kimi-datasource 的异同

| 维度 | local-datasource | kimi-datasource |
|---|---|---|
| 运行位置 | 本机 | Kimi Code 云端 |
| 登录/账号 | 不需要 | 需要 Kimi Code 账号 |
| 费用 | 免费（受公开接口限额影响） | 消耗 Kimi Code 额度 |
| 数据源 | A/HK/US 股票、美股/ETF、World Bank、arXiv | 更多，包括天眼查、Google Scholar、元典法律等 |
| 数据链路 | Agent → 本地 Server → 公开接口 | Agent → Kimi 云服务 → 后端数据源 |
| 可定制性 | 源码本地可见，可修改/扩展 | 黑盒，只能使用官方暴露的 tool |
| 跨 Agent 复用 | 标准 MCP Server，可被多家 Agent 复用 | 仅限 Kimi Code 内部 |

本项目的设计思路是：把常见的免费/公开数据查询能力做成一个本地、透明、可扩展的 MCP 服务。它并不复制 kimi-datasource 的具体实现（其接口实现并不公开），而是基于公开库重新组合出一套可用的本地替代方案。
