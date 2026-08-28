# 消费契约记录：quant-chart × local-datasource

- 对齐日期：2026-08-28；契约版本：**v1.1**（quant-chart 侧维护原文档）
- 联调基线：commit `98cd3bd`
- 消费方：quant-chart（本机 `E:\LLMproject\Github\quant-chart`），库级直调 provider 函数，**读回返回路径的 CSV**（§1 v1.1，消费方选 B，我方零改动）
- 背景：品种覆盖扩展（issue #1）交付对齐；ETF/期权、主连日线、中证官网源、非 1m 分钟粒度**不在消费范围**

## 消费范围

| 接口 | 消费内容 |
|---|---|
| `query_futures` | 单合约日线（全历史）；分钟（仅 1m）；合约清单 |
| `query_index` | 沪深指数日线 + 分钟（仅 1m） |
| `query_stock(period=min)` | A股个股分钟（仅 1m） |

## 硬依赖（触碰前必读）

1. **`CoverageError`**（`providers.common`）：超覆盖显式失败的专用异常，继承 `ValueError`；message 必须含覆盖区间（`YYYY-MM-DD`）与“补数”二字（消费方按正则识别触发其 Excel 补洞流程）。可加信息，**不可删除这两个要素或改异常类型语义**。
2. **列名契约**（契约 §3）：
   - 分钟表：`datetime, open, high, low, close, volume`（期货多 `hold`；腾讯系多 `amount` 无 `hold`）；时间格式 `YYYY-MM-DD HH:MM:SS` 升序
   - 日线表：`date, open, high, low, close, volume`（期货多 `hold, settle`）；`YYYY-MM-DD` 升序
3. **深度守卫**按返回数据实际最早时间戳动态判定（不写死天数），此语义已被消费方程序依赖。

## 本仓库义务

- 修改 `guard_minute_depth` 报错文案、任何被消费表的列名/日期格式前：先对照上方硬依赖；触碰则**提前一个版本告知 quant-chart 侧**，并在 commit message 与 README 注意事项中注明。
- 消费方锁版本安装于 `98cd3bd`；后续演进各自记录（对方维护其 DEVIATIONS，本文件即我方记录）。
