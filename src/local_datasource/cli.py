"""``local-datasource download`` 批量下载 CLI(M3)。

唯一的缓存写入入口:读取清单 YAML,逐条调用 provider 落盘 CSV 到本地缓存,
并写入 manifest 供后续判断"今天已拉过则跳过"。MCP 查询路径(server.py)
绝不读写缓存,查询永远直连数据源。

用法::

    local-datasource download --config FILE [--data-dir DIR] [--force]

清单 YAML 格式::

    data_dir: ./datasource-cache   # 顶层可选;CLI --data-dir 优先
    assets:
      - tool: query_global_rates   # 必填,白名单见 DOWNLOAD_TOOLS
        args: {kind: us_treasury, tenure: all}
        start_date: "2020-01-01"   # 可选,合并进 args(args 内同名值被覆盖)
        end_date: "2026-09-05"
      - tool: query_stock
        args: {ticker: "600519", market: a, start_date: "2025-01-01", end_date: "2025-12-31"}

每条目输出一行 ``SKIP <tool>/<key>``(当天已拉且未 --force)、
``FETCH <tool>/<key> <rows> rows`` 或 ``FAIL <tool>/<key> <error>``;
单条失败不中断整批,任一失败时退出码为 1。
"""
from __future__ import annotations

import argparse
import sys
from typing import Any, Callable

import yaml

from local_datasource.cache import (
    cache_paths,
    is_fresh,
    load_manifest,
    make_key,
    write_manifest,
)
from local_datasource.config import load_config
from local_datasource.providers.arxiv import query_arxiv
from local_datasource.providers.bond import query_bond
from local_datasource.providers.convertible_bond import query_convertible_bond
from local_datasource.providers.etf import query_etf
from local_datasource.providers.futures import query_futures
from local_datasource.providers.fx import query_fx
from local_datasource.providers.global_rates import query_global_rates
from local_datasource.providers.index import query_index
from local_datasource.providers.options import query_options
from local_datasource.providers.spot import query_spot
from local_datasource.providers.stock import query_stock
from local_datasource.providers.worldbank import query_worldbank
from local_datasource.providers.yahoo import query_yfinance

# download 支持的 13 个查询工具:名字 → provider 函数。
# 模块级 dict 便于测试 monkeypatch 替换为离线 mock。
TOOL_FUNCS: dict[str, Callable[..., tuple[str, str]]] = {
    "query_stock": query_stock,
    "query_yfinance": query_yfinance,
    "query_worldbank": query_worldbank,
    "query_arxiv": query_arxiv,
    "query_bond": query_bond,
    "query_convertible_bond": query_convertible_bond,
    "query_futures": query_futures,
    "query_index": query_index,
    "query_etf": query_etf,
    "query_options": query_options,
    "query_global_rates": query_global_rates,
    "query_fx": query_fx,
    "query_spot": query_spot,
}

# 存在于/计划中的非下载工具:出现在清单里时明确报"不支持"并给原因,
# 而不是当作未知工具混在合法名单里让用户困惑。
UNSUPPORTED_TOOLS: dict[str, str] = {
    "resolve_stock_code": "名称反查工具,输出代码候选而非行情序列,随查随用即可",
    "align_series": "本地对齐合并工具,不联网取数,请对 download 产出的 CSV 直接调用 MCP align_series",
    "query_trading_rules": "交易规则参数表(M4),静态数据无需缓存下载",
}


class ManifestError(Exception):
    """清单加载/校验失败(启动期,未发生任何下载)。"""


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="local-datasource download",
        description="按清单 YAML 批量下载数据到本地缓存(唯一写缓存的入口)。",
    )
    parser.add_argument(
        "--config",
        required=True,
        help="清单 YAML 路径(必填),含 data_dir 与 assets 列表",
    )
    parser.add_argument(
        "--data-dir",
        default=None,
        help="缓存根目录;优先级高于清单顶层 data_dir,再高于 config.yaml 的 cache.data_dir",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="忽略当天已拉取的缓存,强制重新下载",
    )
    return parser


def _validate_assets(raw: Any) -> list[dict]:
    """校验清单 assets:结构、白名单、缺 args;所有问题一次性报出。"""
    if not isinstance(raw, dict):
        raise ManifestError("清单格式错误:顶层必须是 YAML 映射,且包含 assets 列表")
    assets = raw.get("assets")
    if assets is None:
        raise ManifestError("清单格式错误:缺少 assets 列表")
    if not isinstance(assets, list):
        raise ManifestError("清单格式错误:assets 必须是列表")

    problems: list[str] = []
    valid_names = ", ".join(sorted(TOOL_FUNCS))
    for i, entry in enumerate(assets, start=1):
        label = f"第 {i} 条"
        if not isinstance(entry, dict):
            problems.append(f"{label}: 必须是映射,实际为 {type(entry).__name__}")
            continue
        tool = entry.get("tool")
        if not tool or not isinstance(tool, str):
            problems.append(f"{label}: 缺少 tool 字段")
            continue
        label = f"第 {i} 条 (tool={tool})"
        if tool in UNSUPPORTED_TOOLS:
            problems.append(
                f"{label}: 不支持的 tool「{tool}」——{UNSUPPORTED_TOOLS[tool]}"
            )
            continue
        if tool not in TOOL_FUNCS:
            problems.append(f"{label}: 未知 tool「{tool}」,合法取值: {valid_names}")
            continue
        args = entry.get("args")
        if args is None:
            problems.append(f"{label}: 缺少 args 映射(该工具的查询参数)")
        elif not isinstance(args, dict):
            problems.append(f"{label}: args 必须是映射,实际为 {type(args).__name__}")

    if problems:
        raise ManifestError(
            f"清单校验失败,共 {len(problems)} 处问题(未执行任何下载):\n"
            + "\n".join(f"  - {p}" for p in problems)
        )
    return assets


def _resolve_data_dir(cli_value: str | None, raw: dict) -> str:
    """--data-dir > 清单顶层 data_dir > config.yaml 的 cache.data_dir。"""
    if cli_value:
        return cli_value
    manifest_dir = raw.get("data_dir")
    if manifest_dir:
        return str(manifest_dir)
    return load_config().cache.data_dir


def _effective_args(entry: dict) -> dict:
    """合并条目的 start_date/end_date 进 args;条目级字段优先于 args 内同名值。"""
    merged = dict(entry.get("args") or {})
    for field in ("start_date", "end_date"):
        value = entry.get(field)
        if value is not None:
            merged[field] = value
    return merged


def run_download(argv: list[str] | None = None) -> int:
    """执行 download 子命令,返回进程退出码(0 成功 / 1 有条目失败 / 2 用法或清单错误)。"""
    parser = _build_parser()
    ns = parser.parse_args(argv)

    config_path = ns.config
    try:
        with open(config_path, "r", encoding="utf-8") as f:
            raw = yaml.safe_load(f)
    except OSError as e:
        print(f"错误: 无法读取清单文件 {config_path}: {e}", file=sys.stderr)
        return 2
    except yaml.YAMLError as e:
        print(f"错误: 清单文件 {config_path} 不是合法 YAML: {e}", file=sys.stderr)
        return 2

    try:
        assets = _validate_assets(raw)
    except ManifestError as e:
        print(f"错误: {e}", file=sys.stderr)
        return 2

    # 校验通过后 raw 必为 dict
    data_dir = _resolve_data_dir(ns.data_dir, raw)
    failed = False
    for entry in assets:
        tool = entry["tool"]
        effective = _effective_args(entry)
        key = make_key(tool, effective)
        csv_path, manifest_path = cache_paths(data_dir, tool, key)

        # CSV 被手动删除时视为失效(manifest 说新鲜但没有数据可读),避免空缓存的 SKIP
        if not ns.force and is_fresh(load_manifest(manifest_path)) and csv_path.is_file():
            print(f"SKIP {tool}/{key}")
            continue

        call_args: dict[str, Any] = dict(effective)
        call_args["file_path"] = str(csv_path)
        if tool == "query_yfinance" and "use_yfinance" not in call_args:
            # 与 server.py 行为一致:清单未显式指定时注入 config.yaml 的默认开关
            call_args["use_yfinance"] = load_config().providers.yahoo.use_yfinance

        try:
            TOOL_FUNCS[tool](**call_args)
            manifest_path = write_manifest(data_dir, tool, key, effective, csv_path)
            manifest = load_manifest(manifest_path)
            rows = manifest["rows"] if manifest else 0
            print(f"FETCH {tool}/{key} {rows} rows")
        except Exception as e:  # 单条失败不中断整批
            failed = True
            detail = str(e) or type(e).__name__
            print(f"FAIL {tool}/{key} {detail}")

    return 1 if failed else 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(run_download(sys.argv[1:]))
