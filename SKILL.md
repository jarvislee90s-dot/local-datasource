---
name: local-datasource
description: |
  当用户需要查询 A股/港股/美股行情、美股/ETF/全球资产价格、世界银行宏观经济指标、arXiv 学术论文、中国境内债券（国债收益率/信用债发行/交易所行情）、可转债（一览/条款/历史K线/发行人财务）、国内期货、指数、A股ETF、期权（月份/清单/日线）、个股分钟、全球利率与波动率（美债收益率/美联储利率/美元指数/VIX）、汇率（中间价/中行牌价/离岸/交叉盘）、商品现货（上金所贵金属/生意社大宗含基差），或把多份行情 CSV 按日期对齐合并，或把股票/债券的名称/简称/全称/发行人归一化为代码，并且希望数据从本地直接获取、不经过第三方云中转、不消耗外部平台额度时，必须优先使用本 skill。
  即使未明确提到 local-datasource 或 MCP，只要对话中出现「查股价」、「金价走势」、「GDP 数据」、「arXiv 论文」、「国债收益率」、「可转债条款」、「IM主连走势」、「中证1000点位」、「510300分钟线」、「IO期权合约」、「茅台的股票代码」、「成都东方广益的债」、「美债收益率」、「美联储利率」、「美元指数」、「VIX」、「汇率中间价」、「黄金现货」、「基差」、「对齐合并多份行情CSV」等需求，都应先尝试通过本 skill 完成。
compatibility: |
  需要本地安装 local-datasource 包（pip install -e .）并保证 `local-datasource` 命令可用。
  依赖 Python 3.10+、akshare、wbgapi、arxiv、mcp、requests。绘图类任务还需 matplotlib。
---

# Local Datasource — Agent 操作手册

本 skill 通过本地 MCP server 提供 15 个数据查询 tool。Agent 的核心职责是：
**理解用户意图 → 选择合适工具 → 构造参数 → 解释返回结果**。
数据的实际获取与 CSV 落盘由 MCP server 完成。项目介绍、架构、安装、配置、调用示例见 `README.md`。

## 一、何时使用

- 用户要查股票/ETF/商品/债券/可转债的历史价格或走势。
- 用户要查宏观经济指标（GDP、CPI、利率、人口）。
- 用户要查 arXiv 论文。
- 用户给了**公司名称/发行人名称**（非代码），要查对应股票或债券。
- 用户要求「本地调用」、「免费 API」、「不登录」。
- 用户要查期货、指数、ETF、期权的行情/合约清单,或个股/指数/ETF 分钟线。

不触发：分析本地已有文件（CSV/Excel/PDF）；明确要求付费 API（Wind/Bloomberg）且未授权本地替代。

## 二、工具速查

| 用户需求 | 选用工具 | 说明 |
|---|---|---|
| A 股 / 港股 / 美股 行情 | `query_stock` | 日线（A/HK/US）+ A股分钟；支持前/后复权 |
| 美股 / ETF / 海外指数 快速查 | `query_yfinance` | 默认 akshare；可回退 yfinance |
| 世界银行宏观指标 | `query_worldbank` | 指标代码 + 国家代码 |
| arXiv 论文 | `query_arxiv` | 关键词、排序、max_results |
| 国债收益率曲线 / 信用债发行信息 / 交易所行情 | `query_bond` | kind 分流；issue_info 支持 bond_code 或 bond_issue |
| 可转债一览 / 条款 / 历史K线 / 发行人财务 | `query_convertible_bond` | kind 分流；issuer_finance 支持正股代码直查 |
| 股票名称（简称/全称）→ 代码候选 | `resolve_stock_code` | 新浪 suggest API（支持全称），降级 akshare 全表简称；多候选择一再调 query_stock |
| 多资产归一化对比 | 组合调用上述工具 → Agent 用 pandas/matplotlib | 见工作流 5 |
| 国内期货（单合约/主连，日线/分钟，合约清单） | `query_futures` | kind 分流；主连日线全历史（自上市日或 2005-01-04 起）；分钟约 4 交易日 |
| 国内指数（沪深/中证系列，日线/分钟） | `query_index` | 000/399 走新浪；930xxx 走中证官网（慢约 10 秒，无分钟） |
| A股场内 ETF（日线/分钟） | `query_etf` | 日线自约 2012 年，无复权；分钟约 8 交易日 |
| 期权（ETF/股指期权：月份/清单/日线） | `query_options` | 先 months/contracts 找代码再 hist 查日线；仅日线 |
| 全球利率与波动率（美债收益率/美联储 EFFR/美元指数/VIX） | `query_global_rates` | kind 分流；us_treasury 选 tenure，短端仅近 1000 交易日 |
| 汇率（中间价/中行牌价/离岸 USDCNH/交叉盘） | `query_fx` | kind 分流；mid 单位 100 外币；bochina 起止日期必填且较慢 |
| 商品现货（上金所贵金属/生意社大宗含基差） | `query_spot` | kind 分流；sge 品种必填；sy 起止必填且单次最长 1 年 |
| 多份行情 CSV 对齐合并成宽表 | `align_series` | 纯本地不联网；outer/inner、前向填充、周月重采样 |

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
| 期货 | 合约/主连（如 IM2612/IM0/IM主连） | 直接 `query_futures`，大小写与"主连"自动归一 |
| 期货 | 品种名（如 IM、螺纹钢） | 品种代码 `query_futures(kind=contracts, symbol=IM)` 查挂牌合约 |
| 指数 | 代码（如 000852/930050/sh000300） | 直接 `query_index`；930/95 开头自动走中证官网源 |
| ETF | 代码（如 510300/159915） | 直接 `query_etf`，前缀自动补 |
| 期权 | 标的名（如 IO、50ETF 期权） | `query_options(kind=months/contracts, underlying=...)` → 合约代码 → `kind=hist` |

**关键边界:**
- 股票全称反查靠新浪 suggest API（从关联字段提取 sh/sz+6 位代码）；城投/非上市发行人无上市股票，返回空候选（正常），应提示用户。
- 标债按发行人查只返回**最新一只**（按发行日期），非全部列表；需全部时让用户明确要求。
- 银行间债（.IB）/交易所信用债的发行人若为城投/非上市，`issuer_finance` 返回引导性提示（免费层无财务）。
- 分钟数据深度受免费源限制（期货约 4 交易日、腾讯系约 8 交易日），请求超出覆盖会**报错并提示补数**（从 Wind/终端导出 Excel），不要把残缺数据当完整历史用；中证官网源慢约 10 秒且无分钟；ETF 日线无复权；期权仅日线。期货主连日线是全历史（自品种上市日或 2005-01-04 取较早，共 83 个主连品种；IF0 特例仅自 2017-01-17 起），可放心拉长区间。

## 三、各工具要点

> 调用示例（JSON）见 `README.md` § 调用数据案例。

### `query_stock` — A/HK/US 股票
- **必填**：`ticker`（A 股 `600519` / 港股 `00700` / 美股 `AAPL`）、`market`（`a`/`hk`/`us`）、`start_date`、`end_date`（`YYYY-MM-DD`）、`file_path`
- **可选**：`adjust`（`qfq` 默认 / `hfq` / `none`，仅日线）、`period`（`daily` 默认 / `min`，min 仅 A 股）、`freq`（分钟粒度 `1/5/15/30/60`，默认 1）
- **注意**：A 股/港股代码不带 `.SH`/`.SZ`/`.HK` 后缀，程序自动补齐。A 股日线含 `turnover`（换手率，小数，0.0036 即 0.36%）、`outstanding_share`（流通股本）、`amount`（成交额），筹码分布等衍生计算可直接使用。分钟约 8 个交易日深度，请求更早区间会明确报错并提示从 Wind/终端导出补数。

### `query_futures` — 国内期货
- **必填**：`symbol`（合约 `IM2612` / 主连 `IM0` / 品种 `IM`（kind=contracts））、`file_path`
- **可选**：`kind`（`hist` 默认 / `contracts`）、`period`（`daily` 默认 / `min`）、`freq`、`start_date`/`end_date`（min 必填）、`trade_date`（contracts，默认今天）
- **注意**：单合约与主连日线均为全历史（主连自品种上市日或 2005-01-04 取较早，共 83 个主连品种；IF0 特例仅自 2017-01-17 起），输出同一组 8 列（date..settle）；主连接口新浪源；分钟约 4 个交易日，超覆盖报错并给补数指引。contracts 走交易所官方挂牌表。

### `query_index` — 国内指数
- **必填**：`symbol`（`000852`/`sh000300`/`930050`）、`file_path`
- **可选**：`period`（`daily` 默认 / `min`）、`freq`、`start_date`/`end_date`（min 必填）
- **注意**：000/399 走新浪（日线自 2014 起）；`93xxxx/95xxxx` 中证系列走中证官网（慢约 10 秒，**无分钟数据**）。分钟约 8 个交易日，超覆盖报错。

### `query_etf` — A股场内 ETF
- **必填**：`symbol`（`510300`/`sh510300`）、`file_path`
- **可选**：`period`（`daily` 默认 / `min`）、`freq`、`start_date`/`end_date`（min 必填）
- **注意**：日线自约 2012 年，**无复权**（原始价）；分钟约 8 个交易日，超覆盖报错。

### `query_options` — 期权
- **必填**：`kind`（`months`/`contracts`/`hist`）、`file_path`；months/contracts 需 `underlying`（`50ETF`/`300ETF`/`500ETF`/`科创50ETF`/`IO`/`HO`/`MO`）；hist 需 `symbol`（如 `10003889`/`IO2706-P-5600`）
- **可选**：`start_date`/`end_date`（hist）、`trade_date`（contracts/CFFEX）
- **注意**：**仅日线**。先用 months/contracts 找合约代码，再 hist 查走势。合约代码宽容格式（`IO2706-P-5600` = `io2706p5600`）。

### `query_yfinance` — 美股/全球资产
- **必填**：`ticker`（`AAPL`/`SPY`/`GLD`）、`file_path`
- **可选**：`period`（`1d`/`1mo`/`1y`/`max` 等）、`start_date`/`end_date`（与 period 二选一）、`use_yfinance`（默认 false 用 akshare）
- **注意**：默认 akshare（免 key 更稳）；akshare 拿不到或用户要求时才 `use_yfinance=true`。

### `query_worldbank` — 世界银行宏观指标
- **必填**：`indicator`（如 `NY.GDP.MKTP.CD`）、`country`（`CHN`/`CHN,USA`/`all`）、`start_year`、`end_year`、`file_path`
- **注意**：不确定指标代码时先向用户确认，或用 GDP 试探。

### `query_arxiv` — 学术论文
- **必填**：`query`、`file_path`
- **可选**：`max_results`（默认 10）、`sort_by`（`relevance` 默认 / `submitted` / `last_updated`）

### `query_bond` — 中国境内债券
- **必填**：`kind`（`yield_curve`/`issue_info`/`credit_daily`）、`file_path`
- **可选**：`start_date`/`end_date`（yield_curve/credit_daily 必填）、`bond_code`（issue_info 必填之一，如 `2180495.IB`/`2180495`，精确匹配单只）、`bond_issue`（issue_info 必填之一，发行人名如 `成都东方广益`，与 `bond_code` 互斥，返回最新一只债）、`symbol`（credit_daily 必填，如 `sh019623`）
- **注意**：`issue_info` 的 `bond_code` 与 `bond_issue` 互斥；给发行人名时按发行日期降序返回最新一只债代码。`2180495.IB` 已做精确过滤，不误命中同号段存单。
- **已知限制**：akshare 免费层无 中债估值 YTM/全价、赎回回售条款详情、剩余期限、城投发行人财务。

### `query_convertible_bond` — 可转债
- **必填**：`kind`（`overview`/`terms`/`history`/`issuer_finance`）、`file_path`
- **可选**：`symbol`（history 必填，如 `sz128039`，支持纯数字补前缀）、`start_date`/`end_date`（history 必填）、`period`（`daily`/`min`，默认 daily）、`bond_code`/`stock_code`（issuer_finance 二选一）、`report_type`（`资产负债表`/`利润表`/`现金流量表`，默认资产负债表）、`keyword`（overview 可选，字面过滤非正则）
- **注意**：`terms` 合并集思录强赎与剩余期限。城投/非上市发行人 `issuer_finance` 返回引导性提示而非报错。
- **issuer_finance 输入判定**：给银行间债(.IB)/交易所信用债(非转债) → 走 `bond_code`，返回非上市提示；给转债代码 → 走 `bond_code`，自动解析正股返回报表；给正股代码（如 `sh603938`）→ 走 `stock_code` 直查（最快）；给发行人名 → 先 `query_bond(bond_issue=...)` 归一化到债代码再判定。

### `resolve_stock_code` — 股票名称→代码
- **必填**：`keyword`（股票简称或全称，如 `茅台`/`贵州茅台酒股份有限公司`）、`file_path`
- **注意**：首选新浪 suggest API（简称精确命中、全称从关联字段提取代码）；新浪失败降级 akshare `stock_zh_a_spot_em()` 全表简称 contains（仅简称有效）。城投/非上市发行人返回空候选（正常），提示用户改用简称或直接给代码。多候选时择一再调 `query_stock`。

### `query_global_rates` — 全球利率与波动率
- **必填**：`kind`（`us_treasury`/`fed_rate`/`dxy`/`vix`）、`file_path`
- **可选**：`start_date`/`end_date`（`YYYY-MM-DD`）、`tenure`（仅 us_treasury：`all` 默认 / 长端 `2y/5y/10y/30y` / 短端 `1m/3m/4m/6m/1y/7y/20y`）
- **注意**：us_treasury 长端及利差 1990 起（东财），短端源仅近 1000 交易日；fed_rate 为纽约联储 EFFR 日频（2000-07 起，免 key）；dxy 东财失败自动回退 Yahoo；vix 走 CBOE 官方直连（1990 起）。

### `query_fx` — 汇率
- **必填**：`kind`（`mid`/`bochina`/`usdcnh`/`cross`）、`file_path`；bochina 另需 `symbol`（币种中文名如 `美元`，注意是"港币"非"港元"）与起止日期；cross 需 `pair`（如 `EUR/USD`）
- **可选**：`currency`（mid 过滤币种，如 `usd,eur`，缺省全部 25 币种）、`start_date`/`end_date`
- **注意**：mid 为央行官方中间价（1994 起），单位是 **100 外币 = X 人民币**，原样不换算；bochina 长区间分页拉取较慢；usdcnh/cross 走 Yahoo，不可达时明确报错（不编造数据）。

### `query_spot` — 商品现货
- **必填**：`kind`（`sge`/`sy`）、`file_path`；sge 另需 `symbol`（如 `Au99.99`/`Ag99.99`/`Au(T+D)`）；sy 另需 `symbols`（如 `["CU","RB"]`）与起止日期
- **注意**：sge 上金所日线约 2016-12 起（约 10 年深度），输出 date/open/high/low/close；sy 生意社逐日抓取较慢，单次区间最长 1 年，输出含现货价/主力合约价/基差（`dom_basis`/`dom_basis_rate`）。

### `align_series` — 多序列对齐合并
- **必填**：`file_paths`（≥2 份本库产出的 CSV，首列为 date/datetime/日期）、`file_path`（输出路径）
- **可选**：`columns`（逐文件取值列，与 file_paths 等长，默认各取 `close`）、`names`（输出列名，默认文件名）、`align`（`outer` 默认并集 / `inner` 交集）、`fill`（`none`/`ffill` 前向填充）、`resample`（`none`/`week`/`month`）
- **注意**：纯本地计算不联网；`resample` 每期保留最后一个实际交易日（非合成的期末标签），回测日期真实可成交；`inner` 交集为空时报错并列出各序列日期范围。

## 四、标准工作流

1. **单只股票走势**：识别 market+ticker → `query_stock` 给日期范围 → 读 CSV 预览展示统计 → 按需绘图。
2. **商品/ETF 价格**：判断是否有美股代码（`GLD`/`SPY`）→ `query_yfinance` 选 period → 返回预览。
3. **宏观指标**：确认指标代码（GDP `NY.GDP.MKTP.CD` / CPI `FP.CPI.TOTL`）→ `query_worldbank` → 返回表格。
4. **arXiv 检索**：`query_arxiv` → 整理标题/作者/PDF 链接展示。
5. **多资产归一化对比**：依次调 `query_stock`/`query_yfinance` 落盘各 CSV → Agent 用 pandas 对齐日期、以首日收盘价为 100 计算归一化 → matplotlib 绘图保存 → 展示汇总表+图。可复用 `demos/mcp_query_demo.py`。

## 五、错误处理

当 tool 返回错误（`Error calling ...` 开头）时：
1. **检查参数**：日期 `YYYY-MM-DD`？`market` 对？代码是否带多余后缀？
2. **确认数据源**：`query_yfinance` 限流/空 → 缩短 period 或 `use_yfinance=true`；`query_stock` 无数据 → 核对代码或换市场。
3. **重试**：网络错误等几秒重试一次，不无限重试（避免触发频率限制）。
4. **上报**：重试仍失败 → 告知用户失败工具/原因/已试修复/建议下一步。**严禁编造数据**。
