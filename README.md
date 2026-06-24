# Local Datasource

本地 MCP（Model Context Protocol）数据服务器。通过免费公开接口查询金融市场、宏观经济和学术论文数据，请求直接从本机发出，不需要第三方平台账号，也不依赖任何云服务商的中继。

## 覆盖范围

| 数据类型 | 工具 | 底层接口 | 是否需 API Key |
|---|---|---|---|
| A股 / 港股 / 美股 历史行情 | `query_stock` | `akshare` | 否 |
| 美股 / ETF / 全球资产 | `query_yfinance` | `akshare`（默认）/ `yfinance`（备选） | 否 |
| 世界银行宏观指标 | `query_worldbank` | `wbgapi` | 否 |
| arXiv 学术论文 | `query_arxiv` | `arxiv` | 否 |

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
├── tests/                          # 单元测试 + 集成测试
└── demos/                          # 示例脚本
    └── mcp_query_demo.py           # 多资产查询 + 归一化走势图
```

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

## 安装

```bash
pip install -e .
```

安装完成后，`local-datasource` 命令会被加入 PATH。

## 启动 MCP 服务

```bash
local-datasource
```

服务通过标准输入输出（stdio）与 Agent 通信。可以用以下命令快速验证是否启动成功：

```bash
echo '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2024-11-05","capabilities":{},"clientInfo":{"name":"test","version":"1.0"}}}' | local-datasource
```

若返回初始化结果，说明服务正常。

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

### 多资产归一化对比

参考 `demos/mcp_query_demo.py`：它通过 MCP 调用多个工具，读取生成的 CSV，计算归一化价格，并绘制对比图。

```bash
python demos/mcp_query_demo.py
```

输出：
- `demos/outputs/*.csv`：各资产原始行情
- `demos/outputs/normalized_returns.png`：归一化走势图
- `demos/outputs/summary.csv`：汇总表

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

## 测试

```bash
python -m pytest tests/ -v
```

包含 8 个测试：配置加载、格式化、4 个 provider 的集成测试、MCP server 工具注册。

## 注意事项

- `yfinance` 容易被 Yahoo Finance 限流，因此默认优先使用 `akshare`。
- `akshare` 的接口可能随时间变化，建议定期更新到较新版本。
- World Bank 和 arXiv 通常稳定且无需 API key。

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
