"""CSV 下载缓存模块(M3,纯函数)。

仅为显式执行的 ``download`` CLI 服务(Task 10);MCP 查询工具绝不读写本模块,
缓存只产生于用户主动下载,查询路径永远直连数据源。

CLI 侧调用顺序::

    csv_path, manifest_path = cache_paths(data_dir, tool, key)
    provider(..., file_path=str(csv_path))   # provider 负责落盘 CSV
    write_manifest(data_dir, tool, key, args, csv_path)

目录布局锁定为 ``<data_dir>/<tool>/<key>.csv`` 与同名 ``<key>.manifest.json``。
"""
from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime
from pathlib import Path
from typing import Any

import pandas as pd

# key 段允许的字符(字母/数字/点/下划线/连字符),其余一律替换为 '-'
_SAFE_RE = re.compile(r"[^A-Za-z0-9._-]")
# 可读部分长度上限;超长时截断并追加确定性短哈希,保证唯一且可读
_KEY_MAX_LEN = 120
_HASH_LEN = 8


def _sanitize(segment: str) -> str:
    """把一段文本清洗为文件系统安全字符;连续 '-' 折叠,空段回落为 '-'。"""
    cleaned = _SAFE_RE.sub("-", segment)
    cleaned = re.sub(r"-{2,}", "-", cleaned).strip("-")
    return cleaned or "-"


def _normalize_value(value: Any) -> str:
    """把参数值确定性地转为字符串(列表按序拼接,字典按键排序序列化)。"""
    if isinstance(value, (list, tuple)):
        return "-".join(_normalize_value(v) for v in value)
    if isinstance(value, dict):
        return json.dumps(value, sort_keys=True, ensure_ascii=False)
    if isinstance(value, bool):
        return "true" if value else "false"
    return str(value)


def make_key(tool: str, args: dict) -> str:
    """由工具名与参数生成稳定、可读、文件系统安全的缓存 key。

    规则:
    - 跳过值为 ``None`` 的参数;键按排序拼接,与传入顺序无关(同参数同 key)。
    - 每段清洗为 ``[A-Za-z0-9._-]`` 以外字符替换为 ``-``,不含路径分隔符。
    - 可读部分超过 120 字符时截断;另外只要清洗发生(或截断),
      就追加规范化串的 md5 前 8 位,防止清洗碰撞破坏唯一性。
    """
    canonical = "&".join(
        f"{k}={_normalize_value(args[k])}"
        for k in sorted(args)
        if args[k] is not None
    )
    segments = [_sanitize(tool)]
    for k in sorted(args):
        if args[k] is None:
            continue
        raw = f"{k}-{_normalize_value(args[k])}"
        cleaned = _sanitize(raw)
        segments.append(cleaned)
        if cleaned != raw:
            segments.append("")  # 标记发生了有损清洗
    key = "-".join(s for s in segments if s != "")
    lossy = "" in segments
    digest = hashlib.md5(canonical.encode("utf-8")).hexdigest()[:_HASH_LEN]
    if lossy or len(key) > _KEY_MAX_LEN:
        key = f"{key[:_KEY_MAX_LEN].rstrip('-')}-{digest}"
    return key or digest


def cache_paths(data_dir: str, tool: str, key: str) -> tuple[Path, Path]:
    """返回 ``(csv 路径, manifest.json 路径)``,纯路径计算,不做任何 I/O。"""
    base = Path(data_dir) / tool
    return base / f"{key}.csv", base / f"{key}.manifest.json"


def is_fresh(manifest: dict | None) -> bool:
    """manifest 的 ``last_fetched`` 日期(ISO 字符串)等于今天才视为新鲜。

    ``None``(未缓存)与缺失/异常字段一律视为不新鲜。
    """
    if not manifest:
        return False
    today = datetime.now().strftime("%Y-%m-%d")
    return manifest.get("last_fetched") == today


def load_manifest(manifest_path: Path) -> dict | None:
    """读取 manifest;文件缺失或 JSON 损坏一律返回 ``None``。

    返回 ``None`` 时 CLI 视为不新鲜 → 重新下载。
    """
    path = Path(manifest_path)
    if not path.is_file():
        return None
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) else None


def write_manifest(
    data_dir: str,
    tool: str,
    key: str,
    args: dict,
    csv_path: Path,
) -> Path:
    """读回 provider 已落盘的 CSV,写 manifest 并返回其路径。

    manifest 字段: ``tool``/``key``/``args``(原样存储)/``rows``/
    ``first_date``/``last_date``/``last_fetched``(今天, ISO)。
    首列为日期列,按文件顺序取首末值(本库输出的日期升序),不排序。
    空 CSV(仅表头)时 ``rows=0``、``first_date``/``last_date`` 为 ``None``。
    """
    df = pd.read_csv(csv_path, encoding="utf-8-sig")
    if df.empty:
        rows, first_date, last_date = 0, None, None
    else:
        rows = len(df)
        first_date = str(df.iloc[0, 0])
        last_date = str(df.iloc[-1, 0])

    manifest = {
        "tool": tool,
        "key": key,
        "args": args,
        "rows": rows,
        "first_date": first_date,
        "last_date": last_date,
        "last_fetched": datetime.now().strftime("%Y-%m-%d"),
    }
    _, manifest_path = cache_paths(data_dir, tool, key)
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    with open(manifest_path, "w", encoding="utf-8") as f:
        json.dump(manifest, f, ensure_ascii=False, indent=2)
    return manifest_path
