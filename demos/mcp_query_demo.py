"""通过本地 MCP server 查询多资产历史行情并绘制归一化涨跌幅图。

需要已安装并可用 ``local-datasource`` 命令（``pip install -e .``）。
"""
from __future__ import annotations

import asyncio
import re
from datetime import datetime, timedelta
from pathlib import Path

import pandas as pd
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client


OUTPUT_DIR = Path(__file__).with_suffix("").parent / "outputs"
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

# 查询清单: (显示名称, tool 名称, 参数 dict)
QUERIES = [
    ("黄金 GLD", "query_yfinance", {"ticker": "GLD", "period": "1y", "file_path": str(OUTPUT_DIR / "gold_gld.csv")}),
    ("Apple AAPL", "query_yfinance", {"ticker": "AAPL", "period": "1y", "file_path": str(OUTPUT_DIR / "apple_aapl.csv")}),
    ("腾讯 00700.HK", "query_stock", {"ticker": "00700", "market": "hk", "start_date": "2025-06-24", "end_date": "2026-06-24", "file_path": str(OUTPUT_DIR / "tencent_00700.csv")}),
    ("紫金矿业 601899", "query_stock", {"ticker": "601899", "market": "a", "start_date": "2025-06-24", "end_date": "2026-06-24", "file_path": str(OUTPUT_DIR / "zijin_601899.csv")}),
]


def _extract_csv_path(preview_text: str) -> str | None:
    """从 tool 返回的预览文本里提取 CSV 文件路径。"""
    m = re.search(r"CSV written to (.+)\n", preview_text)
    return m.group(1).strip() if m else None


def _is_success(preview_text: str) -> bool:
    """判断 tool 返回文本是否表示执行成功。"""
    return "CSV written to" in preview_text and not preview_text.startswith("Error calling")


def _read_close_series(csv_path: str, label: str) -> pd.Series:
    """读取 CSV，统一返回 (date, normalized_close) 序列。"""
    df = pd.read_csv(csv_path)

    # 统一列名：识别日期列和收盘价列
    date_col = next((c for c in df.columns if "date" in c.lower()), None)
    close_col = next((c for c in df.columns if c.lower() in ("close", "收盘")), None)
    if date_col is None or close_col is None:
        raise ValueError(f"{label}: 无法识别 date/close 列，列名: {list(df.columns)}")

    df[date_col] = pd.to_datetime(df[date_col])
    df = df.sort_values(date_col).dropna(subset=[close_col])
    df = df.set_index(date_col)[[close_col]]
    df = df[~df.index.duplicated(keep="first")]

    # 归一化：以第一个有效收盘价为 100
    normalized = df[close_col] / df[close_col].iloc[0] * 100
    normalized.name = label
    return normalized


async def run_queries() -> dict[str, str]:
    """连接本地 MCP server，依次执行查询，返回 {label: csv_path}。"""
    server_params = StdioServerParameters(command="local-datasource", args=[], env=None)

    results: dict[str, str] = {}
    async with stdio_client(server_params) as (read_stream, write_stream):
        async with ClientSession(read_stream, write_stream) as session:
            await session.initialize()

            for label, tool_name, args in QUERIES:
                try:
                    resp = await session.call_tool(tool_name, arguments=args)
                    text = "".join(c.text for c in resp.content if hasattr(c, "text"))
                    if not _is_success(text):
                        print(f"[FAIL] {label}: {text}")
                        continue
                    path = _extract_csv_path(text) or args["file_path"]
                    results[label] = path
                    print(f"[OK] {label}: {path}")
                except Exception as e:
                    print(f"[FAIL] {label} 查询失败: {e}")

            # SK 海力士：韩国股票只能通过 yfinance 回退尝试
            sk_label = "SK海力士 000660.KS"
            try:
                sk_args = {
                    "ticker": "000660.KS",
                    "period": "1y",
                    "use_yfinance": True,
                    "file_path": str(OUTPUT_DIR / "skhynix_000660.csv"),
                }
                resp = await session.call_tool("query_yfinance", arguments=sk_args)
                text = "".join(c.text for c in resp.content if hasattr(c, "text"))
                if not _is_success(text):
                    print(f"[FAIL] {sk_label}: {text}")
                else:
                    path = _extract_csv_path(text) or sk_args["file_path"]
                    results[sk_label] = path
                    print(f"[OK] {sk_label}: {path}")
            except Exception as e:
                print(f"[FAIL] {sk_label} 查询失败: {e}")

    return results


def plot_normalized(series_dict: dict[str, pd.Series], output_path: Path) -> None:
    """绘制归一化涨跌幅图。"""
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    # 尽量使用系统常见中文字体，避免中文标签显示为方块
    plt.rcParams["font.sans-serif"] = ["SimHei", "Microsoft YaHei", "Arial Unicode MS"]
    plt.rcParams["axes.unicode_minus"] = False

    plt.figure(figsize=(12, 6))
    for label, s in series_dict.items():
        plt.plot(s.index, s.values, label=label, linewidth=1.5)

    plt.title("过去一年归一化涨跌幅（基期=100）")
    plt.xlabel("日期")
    plt.ylabel("归一化价格")
    plt.legend(loc="upper left")
    plt.grid(True, alpha=0.3)
    plt.tight_layout()
    plt.savefig(output_path, dpi=150)
    plt.close()
    print(f"\n[Plot] 归一化走势图已保存: {output_path}")


async def main() -> None:
    results = await run_queries()
    if not results:
        print("没有获取到任何数据，无法绘图。")
        return

    series_dict: dict[str, pd.Series] = {}
    for label, csv_path in results.items():
        try:
            series_dict[label] = _read_close_series(csv_path, label)
        except Exception as e:
            print(f"[WARN] 读取 {label} 数据失败: {e}")

    if not series_dict:
        print("没有可绘制的数据。")
        return

    # 汇总统计
    summary_rows = []
    for label, s in series_dict.items():
        summary_rows.append({
            "资产": label,
            "起始日期": s.index.min().strftime("%Y-%m-%d"),
            "结束日期": s.index.max().strftime("%Y-%m-%d"),
            "交易日数": len(s),
            "基期=100": 100.0,
            "最新归一化": round(s.iloc[-1], 2),
            "区间涨跌幅%": round((s.iloc[-1] - 100), 2),
        })
    summary_df = pd.DataFrame(summary_rows)
    summary_path = OUTPUT_DIR / "summary.csv"
    summary_df.to_csv(summary_path, index=False, encoding="utf-8-sig")
    print("\n汇总表:")
    print(summary_df.to_string(index=False))

    plot_path = OUTPUT_DIR / "normalized_returns.png"
    plot_normalized(series_dict, plot_path)


if __name__ == "__main__":
    asyncio.run(main())
