# 数据源连通性测试报告

测试时间：2026-06-24
测试环境：Windows, Python 3.14, 国内网络

## 测试结论

| 数据源 | 目标 | 结果 | 可用接口 | 备注 |
|---|---|---|---|---|
| A股 | 贵州茅台 600519 | ✅ 可用 | `akshare.stock_zh_a_daily` | 稳定 |
| 港股 | 腾讯 00700 | ✅ 可用 | `akshare.stock_hk_daily` | 稳定 |
| 美股 | 苹果 AAPL | ✅ 可用 | `akshare.stock_us_daily` | 来自新浪财经，免key |
| 美股 ETF | 黄金 ETF GLD | ✅ 可用 | `akshare.stock_us_daily` | 来自新浪财经，免key |
| Yahoo Finance | 苹果 AAPL | ❌ 不可用 | `yfinance` | 当前 IP 被限流（Too Many Requests） |
| 世界银行 | 中/美 GDP | ✅ 可用 | `wbgapi` | 稳定，免key |
| arXiv | 论文搜索 | ✅ 可用 | `arxiv` Python 库 | 稳定，免key |

## 关键发现

1. **akshare 可以覆盖 A股/港股/美股/ETF**，全部来自新浪财经接口，免 API key。
2. **yfinance 在当前网络环境下被 Yahoo 限流**，无法稳定使用。等一段时间或换 IP 可能恢复，但不适合作为默认依赖。
3. **世界银行 API 和 arXiv API 完全稳定**。
4. akshare 的 `*_hist` 接口比 `*_daily` 接口更容易触发连接关闭，应优先使用 `*_daily`。

## 对设计的影响

原 spec 中 "Yahoo Finance 全球金融" 的默认实现需要从 `yfinance` 改为 `akshare.stock_us_daily`。

建议调整：
- `query_stock`：覆盖 A股/港股/美股，默认走 akshare
- `query_yfinance`：保留作为可选/高级功能，底层优先尝试 akshare（美股/ETF），yfinance 作为备选并处理限流
- `query_worldbank`：保持 wbgapi
- `query_arxiv`：保持 arxiv

这样既满足"优先免费免key"，又避免 Yahoo 限流导致整个功能不可用。
