# tests/test_cache.py
"""cache 模块单测(M3,全离线,tmp_path)。

契约:make_key / cache_paths / is_fresh / load_manifest / write_manifest。
"""
import json
from datetime import datetime, timedelta
from pathlib import Path

import pandas as pd
import pytest

from local_datasource.cache import (
    cache_paths,
    is_fresh,
    load_manifest,
    make_key,
    write_manifest,
)


# ---------- make_key ----------

def test_key_stable_and_readable():
    """同参数(不同字典顺序)同 key;含 / 等字符时文件系统安全且可读。"""
    args = {"ticker": "600519.SH", "market": "cn", "start_date": "2024-01-01",
            "end_date": "2024-06-30", "adjust": "qfq"}
    key1 = make_key("query_stock", args)
    key2 = make_key("query_stock", dict(reversed(list(args.items()))))
    assert key1 == key2

    weird = make_key("query_stock", {"ticker": "a/b\\c:d*e?f\"g<h>i|j k", "empty": None})
    # 无路径分隔符,仅安全字符
    for ch in '/\\:*?"<>| ':
        assert ch not in weird
    assert set(weird) <= set("abcdefghijklmnopqrstuvwxyz0123456789._-")
    # 可读:工具名与关键参数段可辨认
    normal = make_key("query_stock", {"adjust": "qfq"})
    assert "query_stock" in normal
    assert "adjust-qfq" in normal


def test_key_always_appends_digest():
    """key 末尾总是追加 8 位 md5:即使无有损清洗/截断,唯一性也是绝对的。"""
    key = make_key("query_stock", {"adjust": "qfq"})
    digest = key.rsplit("-", 1)[-1]
    assert len(digest) == 8
    int(digest, 16)  # 是合法十六进制
    # 同参数同 digest;不同参数 digest 不同(即使清洗后可读部分相同)
    assert make_key("query_stock", {"adjust": "qfq"}) == key
    clean_a = make_key("t", {"x": "a b"})
    clean_b = make_key("t", {"x": "a*b"})
    assert clean_a != clean_b  # 清洗碰撞场景下靠 digest 区分
    assert clean_a.rsplit("-", 1)[-1] != clean_b.rsplit("-", 1)[-1]


def test_key_distinguishes_args():
    """adjust=qfq 与 hfq 不同值必须得到不同 key。"""
    qfq = make_key("query_stock", {"ticker": "600519", "adjust": "qfq"})
    hfq = make_key("query_stock", {"ticker": "600519", "adjust": "hfq"})
    assert qfq != hfq
    # 日期不同也不同
    d1 = make_key("query_index", {"symbol": "000300", "start_date": "2024-01-01"})
    d2 = make_key("query_index", {"symbol": "000300", "start_date": "2024-01-02"})
    assert d1 != d2


def test_key_caps_length_and_stays_unique():
    """超长参数:可读部分截断 + 短哈希,长度有界且不同参数仍唯一。"""
    long_a = make_key("query_stock", {"ticker": "x" * 300})
    long_b = make_key("query_stock", {"ticker": "y" * 300})
    assert len(long_a) <= 130
    assert long_a != long_b
    # 确定性:同参数再算一遍不变
    assert long_a == make_key("query_stock", {"ticker": "x" * 300})


# ---------- cache_paths ----------

def test_cache_paths_layout():
    """布局锁定 <data_dir>/<tool>/<key>.csv 与同名 .manifest.json;纯路径无副作用。"""
    csv_path, manifest_path = cache_paths("./ds-cache", "query_futures", "IM0-qfq")
    expected = Path("./ds-cache") / "query_futures"
    assert csv_path == expected / "IM0-qfq.csv"
    assert manifest_path == expected / "IM0-qfq.manifest.json"


# ---------- is_fresh ----------

def test_fresh_today_stale_yesterday():
    """last_fetched == 今天 → 新鲜;昨天 → 不新鲜;None/缺字段 → 不新鲜。"""
    now = datetime.now()  # 单一取样,午夜边界不会抖动
    today = now.strftime("%Y-%m-%d")
    yesterday = (now - timedelta(days=1)).strftime("%Y-%m-%d")
    assert is_fresh({"last_fetched": today}) is True
    assert is_fresh({"last_fetched": yesterday}) is False
    assert is_fresh(None) is False
    assert is_fresh({}) is False


def test_is_fresh_rejects_non_dict():
    """非 dict 真值(如误传日期字符串/列表)一律视为不新鲜,不抛异常。"""
    assert is_fresh("2026-09-06") is False
    assert is_fresh(["last_fetched"]) is False
    assert is_fresh(12345) is False


# ---------- write_manifest ----------

def test_write_manifest_reads_csv_fields(tmp_path):
    """写 3 行 CSV → rows=3、first/last_date 取首末行、last_fetched 为今天。"""
    data_dir = str(tmp_path / "cache")
    key = make_key("query_stock", {"ticker": "600519", "adjust": "qfq"})
    csv_path, manifest_path = cache_paths(data_dir, "query_stock", key)
    csv_path.parent.mkdir(parents=True, exist_ok=True)  # 实际由 format_csv_output 创建
    pd.DataFrame({
        "date": ["2024-01-01", "2024-01-02", "2024-01-03"],
        "close": [1.0, 2.0, 3.0],
    }).to_csv(csv_path, index=False, encoding="utf-8-sig")  # 模拟本库落盘

    args = {"ticker": "600519", "adjust": "qfq"}
    result = write_manifest(data_dir, "query_stock", key, args, csv_path)

    assert result == manifest_path
    assert manifest_path.is_file()
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert manifest["tool"] == "query_stock"
    assert manifest["key"] == key
    assert manifest["args"] == args  # 原样存储
    assert manifest["rows"] == 3
    assert manifest["first_date"] == "2024-01-01"
    assert manifest["last_date"] == "2024-01-03"
    assert manifest["last_fetched"] == datetime.now().strftime("%Y-%m-%d")
    assert is_fresh(load_manifest(manifest_path)) is True


def test_write_manifest_empty_csv(tmp_path):
    """仅表头的空 CSV:rows=0、first/last_date 为 None,不崩溃。"""
    data_dir = str(tmp_path / "cache")
    csv_path, _ = cache_paths(data_dir, "query_index", "k1")
    csv_path.parent.mkdir(parents=True, exist_ok=True)
    pd.DataFrame({"date": [], "close": []}).to_csv(csv_path, index=False, encoding="utf-8-sig")

    write_manifest(data_dir, "query_index", "k1", {}, csv_path)
    manifest = load_manifest(cache_paths(data_dir, "query_index", "k1")[1])
    assert manifest["rows"] == 0
    assert manifest["first_date"] is None
    assert manifest["last_date"] is None


def test_write_manifest_unserializable_args_leaves_no_file(tmp_path):
    """args 不可 JSON 序列化 → 先整体序列化再落盘,抛错时不产生截断 manifest。"""
    data_dir = str(tmp_path / "cache")
    csv_path = _seed_csv(tmp_path)

    with pytest.raises(TypeError):
        write_manifest(data_dir, "query_stock", "k9", {"bad": object()}, csv_path)

    _, manifest_path = cache_paths(data_dir, "query_stock", "k9")
    assert not manifest_path.exists()


# ---------- load_manifest ----------

def test_load_manifest_roundtrip(tmp_path):
    """写后读回字段一致;缺失文件与损坏 JSON 均返回 None。"""
    data_dir = str(tmp_path / "cache")
    args = {"symbol": "IM0", "period": "daily"}
    manifest_path = write_manifest(data_dir, "query_futures", "k2", args, _seed_csv(tmp_path))

    loaded = load_manifest(manifest_path)
    assert loaded is not None
    assert loaded["tool"] == "query_futures"
    assert loaded["key"] == "k2"
    assert loaded["args"] == args
    assert loaded["rows"] == 2
    assert loaded["first_date"] == "2024-01-01"
    assert loaded["last_date"] == "2024-01-02"

    assert load_manifest(tmp_path / "missing.manifest.json") is None

    corrupt = tmp_path / "corrupt.manifest.json"
    corrupt.write_text("{not valid json!!", encoding="utf-8")
    assert load_manifest(corrupt) is None


def _seed_csv(tmp_path: Path) -> Path:
    """造一份 2 行 CSV,模拟 provider 已落盘的输出。"""
    csv_path = tmp_path / "seed.csv"
    pd.DataFrame({
        "date": ["2024-01-01", "2024-01-02"],
        "close": [1.0, 2.0],
    }).to_csv(csv_path, index=False, encoding="utf-8-sig")
    return csv_path
