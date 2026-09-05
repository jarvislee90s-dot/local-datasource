# Changelog

本项目的显著变更记录于此。格式参考 [Keep a Changelog](https://keepachangelog.com/zh-CN/)，条目按功能里程碑组织。

## [进行中] 回测数据源扩展（三期）

### 新增

- `query_global_rates`：全球利率与波动率——`kind=us_treasury` 美债收益率（2/5/10/30Y 及 10Y-2Y 利差，1990 起；`tenure` 可选期限，短端仅近 1000 交易日）、`kind=fed_rate` 美联储 EFFR 日频（纽约联储官方 API，免 key，2000-07 起）、`kind=dxy` 美元指数（东财失败自动回退 Yahoo）、`kind=vix` VIX 波动率指数（CBOE 官方直连，1990 起）
- `query_fx`：汇率——`kind=mid` 央行官方中间价（1994 起，25 币种，单位为 100 外币）、`kind=bochina` 中行牌价（起止日期必填：akshare 缺省是任取的示例区间，静默透传会拿到错数据）、`kind=usdcnh` 离岸人民币与 `kind=cross` 交叉盘（Yahoo）
- `query_spot`：商品现货——`kind=sge` 上金所贵金属现货日线（2016-12 起约 10 年深度）、`kind=sy` 生意社大宗现货（含现货价/主力合约价/基差；起止日期必填，单次区间最长 1 年）
- `align_series`：多份本库产出的 CSV 按日期对齐合并成宽表（纯本地计算不联网）——并集/交集、前向填充、周/月重采样（每期保留最后一个实际交易日，回测日期真实可成交）

### 变更

- 期货主连日线输出列名归一：中文列（日期/开盘价/…/动态结算价）→ 与单合约一致的 8 列 `date,open,high,low,close,volume,hold,settle`（含上游列漂移守卫）；单合约路径列名不变。主连为全历史（自品种上市日或 2005-01-04 取较早，共 83 个主连品种；IF0 特例仅自 2017-01-17 起），quant-chart 消费契约明确排除主连日线，列名变更无存量消费方风险
- 存量文档实测口径修正：删除过时的"主连约 158 日"说法（README/SKILL.md/server.py/futures.py，实测主连日线为全历史）；标注 A 股日线含 `turnover`/`outstanding_share`/`amount`（筹码分布等衍生计算依赖已满足）；新增"网络环境已知风险"小节（东财非 A 股端点部分网络被拒、金十美联储决议源 2025-09 起停更已改用纽约联储 EFFR、FRED/treasury.gov/stooq 本机实测不可达——本轮海外源选 CBOE/纽约联储直连可达即基于此）；README/SKILL.md 工具数与数据源列表同步至 15 tools

## [2026-08-28] 品种覆盖扩展（二期，7 → 11 tools）

关联：[issue #1](https://github.com/jarvislee90s-dot/local-datasource/issues/1)；spec：`docs/superpowers/specs/2026-08-28-品种覆盖扩展-design.md`

### 新增

- `query_futures`：国内期货——单合约日线（全历史，含持仓量/结算价）、主连日线（约 158 日）、分钟（约 4 个交易日）、品种挂牌合约清单（六大交易所官方表）
- `query_index`：国内指数——沪深指数日线（新浪，2014 起）与中证系列日线（中证官网源，慢约 10 秒、无分钟）、沪深指数分钟（约 8 个交易日）
- `query_etf`：A股场内 ETF——日线（新浪，约 2012 起全历史，无复权）与分钟
- `query_options`：期权——ETF 期权（50/300/500/科创50ETF）与股指期权（IO/HO/MO）的到期月份、当月合约清单、单合约日线
- `query_stock` 新增 `period=min`（A 股分钟，腾讯源）与 `freq` 粒度（1/5/15/30/60）
- 共享层 `providers/common.py`：日期过滤、腾讯分钟通用路径、**分钟深度守卫**——请求超出源覆盖显式抛 `CoverageError`（继承 `ValueError`），message 含覆盖区间与补数指引，绝不静默返回残缺数据

### 变更

- 非法 `kind`/`period`/`freq` 枚举一律显式报错，不静默按默认处理
- ETF 带前缀代码与纯数字走同一套校验（股票/转债代码立即拒绝）
- SKILL.md / README 覆盖表、归一化总则、调用案例全面同步

### 外部契约

- quant-chart 消费契约 v1.1 对齐（CSV 读回、`CoverageError`），联调基线 `98cd3bd`，记录于 `docs/消费契约-quant-chart.md`

## [2026-07-03] 金融输入归一化 + 操作手册

- `resolve_stock_code`：股票名称（简称/全称）→ 代码候选（新浪 suggest API，全称反查；城投/非上市返回空候选）
- `query_bond(kind=issue_info)` 新增 `bond_issue`：按发行人名查最新一只债
- SKILL.md 重构为精简操作手册（速查表/工具要点/归一化总则/五步错误规范）

## [2026-07-02] 债券与可转债（5 → 7 tools）

- `query_bond`：国债收益率曲线、信用债发行信息（代码精确匹配/发行人查最新）、交易所行情
- `query_convertible_bond`：全市场一览（溢价率/评级/规模）、强赎回售下修条款、日/分钟 K 线、发行人正股三大报表（非上市发行人返回引导性提示）

## [2026-06-24] 初始版本（5 tools）

- MCP stdio server：`query_stock`（A/港/美）、`query_yfinance`（美股/全球，akshare 默认 + yfinance 备选）、`query_worldbank`、`query_arxiv`
- 统一 CSV 输出（utf-8-sig + 前 5 行预览）、零 API Key、本地直连公开接口
