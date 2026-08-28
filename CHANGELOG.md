# Changelog

本项目的显著变更记录于此。格式参考 [Keep a Changelog](https://keepachangelog.com/zh-CN/)，条目按功能里程碑组织。

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
