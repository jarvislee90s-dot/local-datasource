# Local Datasource Skill — 设计文档

## 1. 目标

复现 Kimi Datasource 插件的核心数据查询能力，但：
- **不需要登录 Kimi Code**
- **不需要消耗 Kimi 账号额度**
- **数据从本地直接调用公开/免费 API 获取**
- **任何支持 MCP 的 Agent 都能复用**（Codex、Claude Code、OpenCode、Kimi Code 等）

## 2. 覆盖范围（第一阶段）

| 数据源 | 对应 Kimi Datasource | 本地实现方式 | 是否免 API Key |
|---|---|---|---|
| A股/港股/美股 行情财务 | `stock_finance_data` | `akshare` | ✅ 免 Key（限额） |
| Yahoo Finance 全球金融 | `yahoo_finance` | `akshare`（美股/ETF）+ `yfinance`（备选） | ✅ 免 Key（akshare 默认）；yfinance 易限流 |
| World Bank 宏观经济 | `world_bank_open_data` | `wbgapi` | ✅ 免 Key |
| arXiv 学术论文 | `arxiv` | `arxiv` Python 库 | ✅ 免 Key |

> **连通性验证结果**：当前网络环境下 `akshare` 的 `stock_zh_a_daily`、`stock_hk_daily`、`stock_us_daily` 均可稳定获取数据；`yfinance` 因 Yahoo 限流不可用。因此默认用 `akshare` 覆盖股票/Yahoo 类查询，`yfinance` 仅作为可选备选。

> 天眼查、元典法律、Google Scholar 暂不纳入第一阶段（商业数据或需要特殊处理）。

## 3. 连通性验证摘要

已执行实际 API 连通性测试（见 `demos/connectivity_report.md`）：

- ✅ A股（akshare）
- ✅ 港股（akshare）
- ✅ 美股/ETF（akshare）
- ❌ Yahoo Finance（yfinance 限流）
- ✅ World Bank（wbgapi）
- ✅ arXiv（arxiv）

设计据此调整：股票/Yahoo 类查询默认用 `akshare`，`yfinance` 作为可选备选。

## 4. 形态

采用 **Python MCP Server + Agent Skill 包装**：

```
Agent（Claude Code / Codex / OpenCode / Kimi Code）
    ↓ MCP stdio
local-datasource-mcp （Python MCP Server）
    ↓ 直接调用
akshare / yfinance / wbgapi / arxiv
    ↓ 原始数据源
同花顺 / Yahoo Finance / World Bank / arxiv.org
```

## 5. 架构设计

### 5.1 核心组件

| 组件 | 作用 | 文件 |
|---|---|---|
| MCP Server | 暴露数据查询 tools，处理请求/响应 | `src/server.py` |
| 数据源适配器 | 封装每个数据源的调用逻辑 | `src/providers/*.py` |
| 统一输出 | 把不同数据源结果转成 CSV / Markdown | `src/formatters.py` |
| Skill 说明 | 教 Agent 如何使用这些 tools | `SKILL.md` |
| 配置 | API key / 限额 / 缓存配置 | `config.yaml` |

### 5.2 目录结构

```
local-datasource/
├── src/
│   ├── server.py              # MCP Server 入口
│   ├── providers/
│   │   ├── __init__.py
│   │   ├── stock.py           # A股/港股/美股
│   │   ├── yahoo.py           # Yahoo Finance
│   │   ├── worldbank.py       # World Bank
│   │   └── arxiv.py           # arXiv
│   ├── formatters.py          # 统一输出格式
│   └── config.py              # 配置加载
├── SKILL.md                   # Agent 使用说明
├── config.yaml                # 用户配置（可选 API key）
├── pyproject.toml             # Python 包配置
├── README.md
└── tests/
    └── test_providers.py
```

## 6. Tool 设计

### 6.1 股票数据：`query_stock`

参数：
- `ticker` (str): 股票代码，如 `600519`、`00700`、`AAPL`
- `market` (str): `a` / `hk` / `us`
- `start_date` (str): 开始日期 `YYYY-MM-DD`
- `end_date` (str): 结束日期 `YYYY-MM-DD`
- `adjust` (str): 复权方式，`qfq` / `hfq` / `none`，默认 `qfq`
- `file_path` (str): 输出 CSV 路径

返回：CSV 文件路径 + 前 5 行预览

### 6.2 Yahoo Finance：`query_yfinance`

参数：
- `ticker` (str): 如 `AAPL`、`SPY`、`GLD`
- `period` (str): `1d` / `5d` / `1mo` / `3mo` / `6mo` / `1y` / `5y` / `max`
- `start_date` / `end_date` (str, optional)
- `file_path` (str): 输出 CSV 路径

实现说明：默认优先用 `akshare.stock_us_daily`（免 key、当前网络可用），`yfinance` 作为可选备选（当前网络下易被 Yahoo 限流）。

返回：CSV 文件路径 + 前 5 行预览

### 6.3 世界银行：`query_worldbank`

参数：
- `indicator` (str): 指标代码，如 `NY.GDP.MKTP.CD`
- `country` (str): 国家代码，如 `CHN`、`USA`、`all`
- `start_year` (int)
- `end_year` (int)
- `file_path` (str): 输出 CSV 路径

返回：CSV 文件路径 + 前 5 行预览

### 6.4 arXiv：`query_arxiv`

参数：
- `query` (str): 搜索关键词
- `max_results` (int): 默认 10
- `sort_by` (str): `relevance` / `submitted` / `last_updated`
- `file_path` (str): 输出 CSV / Markdown 路径

返回：文件路径 + 标题列表预览

## 7. 数据流

1. Agent 根据 SKILL.md 选择 tool
2. MCP Server 接收调用
3. 根据 tool name 路由到对应 provider
4. Provider 调用底层库（akshare / yfinance / wbgapi / arxiv）
5. Formatter 把结果转为统一 CSV 格式
6. 文件写入 `file_path`
7. 返回 preview + file_path

## 8. 错误处理

| 错误类型 | 处理方式 |
|---|---|
| 网络超时 | 重试 1 次，返回友好错误 |
| 免 Key 限额 | 提示用户配置 API key（预留配置入口） |
| 股票代码错误 | 返回明确错误，建议核对代码 |
| 数据为空 | 返回空结果提示，不抛异常 |
| 底层库报错 | 捕获后包装成可读错误 |

## 9. 配置

`config.yaml`：

```yaml
# 可选：当免费渠道限额时配置
providers:
  tushare:
    token: ""  # A股备选：Tushare token
  worldbank:
    # 世界银行通常不需要 key
  yahoo:
    # Yahoo Finance 通常不需要 key
```

> 第一阶段以免 Key 为主，配置项仅作预留。

## 10. 技术栈

- Python 3.10+
- `mcp`（Python SDK for Model Context Protocol）
- `akshare`（A股/港股/美股/ETF，默认）
- `yfinance`（美股/全球/Yahoo，备选，当前网络易限流）
- `wbgapi`（世界银行）
- `arxiv`（arXiv 官方库）
- `pandas`（数据处理）
- `pyyaml`（配置）

## 11. Skill 包装

`SKILL.md` 核心内容：

- 告诉 Agent 这个 skill 提供 4 个数据源
- 每个 tool 的参数说明
- 股票代码规则：A股用数字代码（如 `600519`）、港股用数字代码（如 `00700`）、美股用字母代码（如 `AAPL`）
- 优先使用本地免费 API，限额时可提示配置 key
- 输出默认写到 `file_path`

## 12. 复用性

由于采用标准 MCP Server，本 skill 可被以下 Agent 复用：

- Claude Code（通过 `claude_mcp_settings.json`）
- Codex（通过 `.codex/config.json`）
- OpenCode（通过 MCP 配置）
- Kimi Code（通过 `kimi.plugin.json` 声明 MCP server）
- Cursor / Windsurf（通过 MCP settings）

## 13. 测试策略

- 单元测试：mock 各 provider 的底层调用
- 集成测试：每个 provider 至少跑一个真实查询
- 回归测试：CSV 输出格式稳定

## 14. 第一阶段交付物

1. 可运行的 Python MCP Server
2. 4 个数据 provider
3. SKILL.md
4. pyproject.toml 安装配置
5. README（安装 + Agent 接入说明）
6. 基础测试

## 15. 风险

| 风险 | 缓解措施 |
|---|---|
| akshare / yfinance 接口变化 | 锁定版本 + 单元测试 |
| 免费源频率限制 | 缓存 + 错误提示 + 预留 API key 配置 |
| Yahoo Finance 限流 | 默认用 akshare 美股接口，yfinance 仅作备选 |
| 输出 CSV 路径跨平台 | 使用 Python `pathlib` |
| 不同 Agent MCP 配置差异 | README 提供多平台配置示例 |
