---
name: local-datasource
description: |
  当用户需要查询 A股/港股/美股行情、美股/ETF/全球资产价格、世界银行宏观经济指标或 arXiv 学术论文，
  并且希望数据从本地直接获取、不经过第三方云中转、不消耗外部平台额度时，必须优先使用本 skill。
  即使未明确提到 local-datasource 或 MCP，只要对话中出现“查股价”、“金价走势”、“GDP 数据”、
  “arXiv 论文”、“归一化对比图”等需求，都应先尝试通过本 skill 完成。
compatibility: |
  需要本地安装 local-datasource 包（pip install -e .）并保证 `local-datasource` 命令可用。
  依赖 Python 3.10+、akshare、wbgapi、arxiv、mcp。绘图类任务还需 matplotlib。
---

# Local Datasource — Agent 执行手册

本 skill 通过本地 MCP server 提供 7 个数据查询工具。Agent 的核心职责是：
**理解用户意图 → 选择合适工具 → 构造参数 → 解释返回结果**。
数据的实际获取与 CSV 落盘由 MCP server 完成。

## 一、适用场景与触发条件

### 必须触发本 skill 的场景

- 用户要查股票、ETF、商品（如黄金）的历史价格或走势。
- 用户要查宏观经济指标（GDP、CPI、利率、人口等）。
- 用户要查 arXiv 论文，并按标题、作者、日期结构化返回。
- 用户要查中国境内债券（国债收益率曲线、信用债发行信息与评级、交易所行情）。
- 用户要查可转债（一览与转股溢价率、强赎/回售条款与剩余期限、历史K线、发行人正股财务报表）。
- 用户要求绘制多只资产/指数的归一化对比图。
- 用户提到“不用登录”、“本地调用”、“免费 API”等偏好。

### 不触发本 skill 的场景

- 用户要求分析本地已有文件（CSV/Excel/PDF 等），直接用文件工具即可。
- 用户要求撰写创意文案、翻译、摘要等，与数据查询无关。
- 用户明确要求使用某个特定付费 API（如 Wind、Bloomberg）且未授权本地替代方案。

## 二、工具选择速查

| 用户需求 | 选用工具 | 说明 |
|---|---|---|
| A 股 / 港股 / 美股 行情 | `query_stock` | 日线数据，支持前复权/后复权 |
| 美股 / ETF / 海外指数 快速查 | `query_yfinance` | 默认 akshare；可回退 yfinance |
| 世界银行宏观指标 | `query_worldbank` | 按指标代码 + 国家代码查询 |
| arXiv 论文 | `query_arxiv` | 关键词、排序、max_results |
| 国债收益率曲线 / 信用债发行信息 / 交易所行情 | `query_bond` | kind 分流，无需 key |
| 可转债一览 / 条款 / 历史K线 / 发行人财务 | `query_convertible_bond` | kind 分流，发行人财务支持正股代码直查 |
| 股票名称（简称/全称）→ 代码候选 | `resolve_stock_code` | 新浪 suggest API（支持全称反查），降级 akshare 全表简称；多候选择一再调 query_stock |
| 多资产归一化对比 | 组合调用上述工具 → Agent 用 pandas/matplotlib 处理 | 见工作流 5 |

## 输入归一化总则（重要）

用户给金融标的时，可能贴代码、简称、全称或发行人名。Agent **调用 tool 前先按下表归一化输入**，不要把原始输入直接塞参数。

| 品种 | 用户输入 | Agent 动作 |
|---|---|---|
| 股票 | 公司简称（如茅台） | `resolve_stock_code(keyword=简称)` → 候选 → 选代码 → `query_stock` |
| 股票 | 公司全称（如贵州茅台酒股份有限公司） | `resolve_stock_code(keyword=全称)` → 新浪从关联字段提取代码；空则提示用户提供简称 |
| 股票 | 已是代码（如 600519） | 直接 `query_stock` |
| 可转债 | 某公司转债 | `query_convertible_bond(kind=overview, keyword=正股简称)` → 该公司转债 |
| 可转债 | 转债代码 | 直接 `query_convertible_bond(kind=history, symbol=...)` |
| 标债 | 发行人名（如成都东方广益） | `query_bond(kind=issue_info, bond_issue=发行人)` → 最新一只债代码 → 继续查 |
| 标债 | 具体债代码/简称（如 2180495.IB） | `query_bond(kind=issue_info, bond_code=...)` |
| 发行人财务 | 任意债代码/发行人名 | 先归一化到代码 → `query_convertible_bond(kind=issuer_finance, ...)` |

**关键边界:**
- 股票全称反查靠新浪 suggest API（从关联字段提取 sh/sz+6 位代码）；城投/非上市发行人无上市股票，返回空候选（正常），应提示用户。
- 标债按发行人查只返回**最新一只**（按发行日期），非全部列表；需全部时让用户明确要求。
- 银行间债（.IB）/交易所信用债的发行人若为城投/非上市，`issuer_finance` 返回引导性提示（免费层无财务）。

## 三、各工具详细规范

### `query_stock` — A/HK/US 股票

**何时使用**：A 股、港股、美股的历史日线查询。

**必填参数**：
- `ticker`：股票代码。A 股用数字（`600519`），港股用数字（`00700`），美股用字母（`AAPL`）。
- `market`：`a` / `hk` / `us`
- `start_date`、`end_date`：`YYYY-MM-DD`
- `file_path`：输出 CSV 路径

**可选参数**：
- `adjust`：复权方式，`qfq`（默认，前复权） / `hfq` / `none`

**示例**：
```json
{"ticker": "600519", "market": "a", "start_date": "2025-06-01", "end_date": "2026-06-24", "file_path": "/tmp/moutai.csv"}
```

**Agent 注意事项**：
- A 股代码不带 `.SH` / `.SZ` 后缀，程序会自动补齐。
- 港股代码不带 `.HK` 后缀。

### `query_yfinance` — 美股/全球资产

**何时使用**：美股、ETF、海外指数；需要按 `period` 快速查询而不是指定起止日期。

**必填参数**：
- `ticker`：代码，例如 `AAPL`、`SPY`、`GLD`
- `file_path`：输出 CSV 路径

**常用可选参数**：
- `period`：`1d` / `5d` / `1mo` / `3mo` / `6mo` / `1y` / `2y` / `5y` / `10y` / `max`
- `start_date` / `end_date`：显式日期范围，与 `period` 二选一
- `use_yfinance`：`false`（默认，akshare） / `true`（回退 Yahoo Finance）

**示例**：
```json
{"ticker": "GLD", "period": "1y", "file_path": "/tmp/gld.csv"}
```

**Agent 注意事项**：
- 默认优先使用 akshare，因为它在当前网络下更稳定且免 key。
- 只有 akshare 拿不到数据或用户明确要求 Yahoo Finance 时，才设置 `use_yfinance=true`。

### `query_worldbank` — 世界银行宏观指标

**何时使用**：需要 GDP、CPI、人口、贸易等宏观数据。

**必填参数**：
- `indicator`：指标代码，例如 `NY.GDP.MKTP.CD`
- `country`：国家代码，支持逗号分隔（`CHN,USA`）或 `all`
- `start_year`、`end_year`：整数
- `file_path`：输出 CSV 路径

**示例**：
```json
{"indicator": "NY.GDP.MKTP.CD", "country": "CHN", "start_year": 2020, "end_year": 2023, "file_path": "/tmp/china_gdp.csv"}
```

**Agent 注意事项**：
- 若不确定指标代码，可先向用户确认，或用最常见的 GDP 指标试探。

### `query_arxiv` — 学术论文

**何时使用**：用户需要查找某领域的 arXiv 论文列表。

**必填参数**：
- `query`：检索关键词
- `file_path`：输出 CSV 路径

**可选参数**：
- `max_results`：默认 10
- `sort_by`：`relevance`（默认） / `submitted` / `last_updated`

**示例**：
```json
{"query": "retrieval augmented generation", "max_results": 10, "file_path": "/tmp/rag_papers.csv"}
```

## 四、标准工作流

### 工作流 1：单只股票走势

1. 识别 market 和 ticker。
2. 调用 `query_stock`，给定日期范围和 `file_path`。
3. 读取返回的 CSV 预览，向用户展示关键统计（最新价、区间涨跌幅等）。
4. 如用户要求，读取完整 CSV 绘制走势图。

### 工作流 2：商品/ETF 价格

1. 判断资产是否有美股代码（如 `GLD`、`SLV`、`SPY`）。
2. 调用 `query_yfinance`，`period` 按需选择。
3. 返回预览与路径。

### 工作流 3：宏观指标查询

1. 向用户确认指标名称或代码。常见代码：
   - GDP 现价：`NY.GDP.MKTP.CD`
   - 人均 GDP：`NY.GDP.PCAP.CD`
   - CPI：`FP.CPI.TOTL`
2. 调用 `query_worldbank`。
3. 返回预览表格。

### 工作流 4：arXiv 文献检索

1. 调用 `query_arxiv`。
2. 将返回的标题、作者、PDF 链接整理成表格或列表展示给用户。

### 工作流 5：多资产归一化对比图

**分工**：
- **Agent**：
  - 拆出每个资产对应的工具与参数。
  - 依次调用工具，确认每个 CSV 成功落盘。
  - 读取 CSV，用 pandas 对齐日期、计算归一化价格。
  - 使用 matplotlib 绘制走势图并保存。
- **MCP server / 脚本**：
  - MCP server 负责单个工具调用与原始数据落盘。
  - 可复用 `demos/mcp_query_demo.py` 作为批量查询+绘图的脚本模板。

**步骤**：
1. 分别调用 `query_stock` / `query_yfinance` 获取各资产 CSV。
2. 读取每个 CSV 的收盘价列（列名通常为 `close` 或 `Close`）。
3. 以第一天收盘价为 100，计算后续相对涨跌幅。
4. 绘制所有资产的归一化曲线，保存为图片。
5. 向用户展示汇总表（区间涨跌幅、最新归一化值）和图片。

## 五、Agent 与脚本/服务的职责边界

| 任务 | 由谁完成 | 说明 |
|---|---|---|
| 理解自然语言需求 | Agent | 判断需要哪个 tool、日期范围、代码等 |
| 参数校验与格式化 | Agent | 确保日期为 `YYYY-MM-DD`，代码符合 market 规则 |
| 实际 API 调用与 CSV 落盘 | MCP server（`local-datasource`） | Agent 只负责调用 tool |
| 批量查询与绘图脚本 | 可选脚本（`demos/mcp_query_demo.py`） | 复杂可视化任务可让 Agent 参考或直接运行 |
| 结果解读与呈现 | Agent | 把 CSV 预览/汇总表/图表展示给用户 |

## 六、错误处理流程

当 tool 返回错误提示（通常以 `Error calling ...` 开头）时，按以下顺序处理：

1. **检查参数格式**
   - 日期是否为 `YYYY-MM-DD`？
   - `market` 是否写对？
   - A 股/港股代码是否带了多余后缀（如 `.SH` / `.HK`）？

2. **确认数据源可用性**
   - 若 `query_yfinance` 提示限流或空数据，尝试：
     - 缩短 `period` 或日期范围。
     - 设置 `"use_yfinance": true` 回退到 Yahoo Finance。
   - 若 `query_stock` 对某代码无数据，建议用户核对代码是否正确，或换一个市场重试。

3. **重试**
   - 网络类错误可等待几秒后重试一次。
   - 不要无限重试，避免触发免费源频率限制。

4. **上报并请求用户决策**
   - 如果重试仍失败，向用户说明：
     - 失败的工具
     - 失败原因
     - 已尝试的修复
     - 建议的下一步（如换代码、换数据源、等待后重试）

5. **严禁编造数据**
   - 任何时候都不要把错误提示隐藏或伪造数据返回给用户。

## query_bond — 中国境内债券

### 必填参数

- `kind`：`yield_curve` / `issue_info` / `credit_daily`
- `file_path`：输出 CSV 路径

### 可选参数

- `start_date` / `end_date`（`YYYY-MM-DD`，yield_curve / credit_daily 必填）
- `bond_code`（issue_info 必填之一，如 `2180495.IB` / `2180495`，精确匹配单只）
- `bond_issue`（issue_info 必填之一，发行人名如 `成都东方广益`，与 `bond_code` 互斥；返回最新一只债）
- `symbol`（credit_daily 必填，如 `sh019623`）

### Agent 注意事项

- `issue_info` 已做精确过滤，`2180495.IB` 只返回 1 条对应债券，不会误命中同号段存单（如 `112180495`）。
- `issue_info` 的 `bond_code` 与 `bond_issue` 互斥；给发行人名时按发行日期降序返回最新一只债代码。
- 国债收益率曲线返回各期限（1/3/5/7/10 年等）到期收益率。

### 已知限制

akshare 免费层无法获取：中债估值 YTM / 全价、赎回回售条款详情、剩余期限、城投/非上市发行人财务。需要这些数据时建议提示用户查 Wind / 企业预警通。

## query_convertible_bond — 可转债

### 必填参数

- `kind`：`overview` / `terms` / `history` / `issuer_finance`
- `file_path`：输出 CSV 路径

### 可选参数

- `symbol`（history 必填，如 `sz128039`，支持纯数字 `128039` 自动补前缀）
- `start_date` / `end_date`（history 必填）
- `period`：`daily` / `min`（history，默认 daily）
- `bond_code` / `stock_code`（issuer_finance 二选一，见下方「issuer_finance 输入判定」）
- `report_type`：`资产负债表` / `利润表` / `现金流量表`（issuer_finance，默认资产负债表）
- `keyword`（overview 可选，按债券简称/正股简称字面过滤）

### Agent 注意事项

- `terms` 合并集思录强赎与剩余期限数据。

### issuer_finance 输入判定（重要）

用户给「发行人财务」时，可能贴三种不同形式的输入。Agent **调用前必须先按下表识别**，映射到 `bond_code` 或 `stock_code` 参数，**不要直接把原始输入塞进参数**。

| 用户输入形式 | 识别特征 | 映射到参数 | 预期行为 |
|---|---|---|---|
| **银行间债代码** | 含 `.IB` 或纯数字银行间码（如 `2180495.IB` / `2180495`） | `bond_code` | 代码非转债 → 解析为非上市，返回引导性提示（城投/非上市发行人财务免费层无） |
| **交易所债代码** | `sh`/`sz` 前缀，或 `.SH`/`.SZ` 后缀（如 `sh019623` / `019623.SH`） | `bond_code` | 交易所信用债通常无正股 → 同样返回引导性提示 |
| **可转债代码** | 6 位数字且 `11`/`12` 开头（如 `113682` / `sz128039`） | `bond_code` | 转债有正股 → 自动解析正股并返回三大报表 |
| **发行人名称** | 中文，非代码（如「成都东方广益投资有限公司」或简称「东方广益」） | 先查 `query_bond(kind=issue_info)` 反查该发行人债券 → 若其中有转债/上市正股则取 `stock_code`；否则提示非上市 | 多一步查询，但能拿到真实发行人名 |
| **正股代码** | `sh`/`sz` + 6 位（如 `sh603938`） | `stock_code` | 直接查该上市公司报表（最快路径） |

**判定要点：**
1. 先看是否含 `.IB` → 银行间债，走 `bond_code`，预期非上市提示。
2. 再看是否 `sh/sz` 开头或 `.SH/.SZ` 结尾 → 交易所债，走 `bond_code`。
3. 再看是否 6 位纯数字且 `11`/`12` 开头 → 可转债，走 `bond_code`（能取到正股）。
4. 若是中文 → 发行人名，先 `query_bond(issue_info)` 反查其债券，再决定。
5. 若是 `sh/sz`+6 位且明显是股票（如 `sh603938`）→ `stock_code` 直查。

**给用户的反馈原则**：当返回引导性提示（非上市发行人）时，说明该发行人财务在 akshare 免费层不可得，建议查 Wind / 企业预警通，并把已查到的发行人名称与债券基本信息一并告诉用户（可来自 `query_bond(issue_info)`）。

### 已知限制

- 集思录接口（`bond_cb_redeem_jsl` / `bond_cb_summary`）偶发不可用，失败时 terms 仅返回强赎表。
- `keyword` 按字面匹配（非正则），含 `+`/`(` 等元字符的关键字不会报错。
- **城投/非上市发行人财务免费层无**：银行间债（`.IB`）、交易所信用债的发行人若为城投/非上市主体，`issuer_finance` 会返回引导性提示而非报表数据。

### 典型场景：用户贴一个银行间债代码要「基本信息 + 发行人财务」

示例：用户说「查一下 `2180495.IB` 的债券基本信息和发行人财务简介」。

Agent 工作流：
1. **识别输入**：`2180495.IB` 含 `.IB` → 银行间债代码。
2. **第一步 — 基本信息**：调 `query_bond(kind="issue_info", bond_code="2180495.IB")`，拿到发行人名称（如「成都东方广益投资有限公司」）、类型、评级、发行日等，告知用户。
3. **第二步 — 发行人财务**：调 `query_convertible_bond(kind="issuer_finance", bond_code="2180495.IB")`。银行间债非转债 → 接口返回「非上市主体，免费层无财务数据，建议查 Wind/企业预警通」。
4. **给用户完整反馈**：把基本信息 + 财务提示一起呈现，附上发行人真实名称，引导用户去 Wind 查财务。

> 若用户贴的是发行人名称（如「成都东方广益投资有限公司」）而非债代码：直接调 `query_bond(kind="issue_info", bond_issue="成都东方广益")`，按发行日期降序返回最新一只债代码，再继续链路查基本信息/财务。

## resolve_stock_code — 股票名称→代码

### 必填参数
- `keyword`：股票简称或全称（如 `茅台` / `贵州茅台酒股份有限公司`）
- `file_path`：输出 CSV 路径

### Agent 注意事项
- 返回候选列表（代码+名称），多候选时择一再调 `query_stock`。
- 首选新浪 suggest API：简称精确命中；全称从关联字段提取代码。
- 城投/非上市发行人返回空候选（正常，因其无上市股票），应提示用户改用简称或直接给代码。
- 新浪失败时降级 akshare `stock_zh_a_spot_em()` 全表按简称 contains（仅简称有效）。
