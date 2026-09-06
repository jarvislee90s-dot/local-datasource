# tests/test_index.py
import os
import tempfile

import pandas as pd
import pytest

from local_datasource.providers.index import query_index


# ---------- 归一化 ----------

def test_normalize_index_code():
    from local_datasource.providers import index
    assert index._normalize_index_code("000852") == ("sh000852", "sina")
    assert index._normalize_index_code("sh000852") == ("sh000852", "sina")
    assert index._normalize_index_code("399001") == ("sz399001", "sina")
    assert index._normalize_index_code("sz399001") == ("sz399001", "sina")
    assert index._normalize_index_code("930050") == ("930050", "csindex")
    assert index._normalize_index_code("sh930050") == ("930050", "csindex")  # 93 系列无视前缀走官网
    with pytest.raises(ValueError):
        index._normalize_index_code("ABC")


# ---------- daily(monkeypatch) ----------

def test_query_index_daily_sina(monkeypatch, tmp_path):
    from local_datasource.providers import index
    fake = pd.DataFrame({
        "date": ["2026-08-26", "2026-08-27"],
        "open": [6000.0, 6010.0], "high": [6050.0, 6060.0],
        "low": [5980.0, 5990.0], "close": [6020.0, 6030.0], "volume": [1, 2],
    })
    monkeypatch.setattr(index.ak, "stock_zh_index_daily", lambda symbol: fake.copy())
    _, summary = query_index(symbol="000852", file_path=str(tmp_path / "i.csv"),
                             period="daily", start_date="2026-08-27", end_date="2026-08-27")
    assert "Rows: 1" in summary


def test_query_index_daily_csindex(monkeypatch, tmp_path):
    from local_datasource.providers import index
    fake = pd.DataFrame({"日期": ["2026-08-26"], "收盘": [1234.5]})
    monkeypatch.setattr(index.ak, "stock_zh_index_hist_csindex",
                        lambda symbol, start_date, end_date: fake.copy())
    _, summary = query_index(symbol="930050", file_path=str(tmp_path / "csi.csv"), period="daily")
    assert "Rows: 1" in summary


def test_query_index_daily_sina_one_sided_start(monkeypatch, tmp_path):
    """只给 start_date 也应生效,不得静默返回全历史。"""
    from local_datasource.providers import index
    fake = pd.DataFrame({
        "date": ["2026-08-26", "2026-08-27"],
        "open": [6000.0, 6010.0], "high": [6050.0, 6060.0],
        "low": [5980.0, 5990.0], "close": [6020.0, 6030.0], "volume": [1, 2],
    })
    monkeypatch.setattr(index.ak, "stock_zh_index_daily", lambda symbol: fake.copy())
    _, summary = query_index(symbol="000852", file_path=str(tmp_path / "i2.csv"),
                             period="daily", start_date="2026-08-27")
    assert "Rows: 1" in summary


def test_query_index_unsupported_period(tmp_path):
    with pytest.raises(ValueError, match="Unsupported period"):
        query_index(symbol="000852", file_path=str(tmp_path / "w.csv"), period="weekly")


def test_normalize_index_code_prefixed_unknown_series():
    from local_datasource.providers import index
    with pytest.raises(ValueError):
        index._normalize_index_code("sh980017")


# ---------- min ----------

def test_query_index_min_csindex_rejected(tmp_path):
    with pytest.raises(ValueError, match="中证系列官网源无分钟数据"):
        query_index(symbol="930050", file_path=str(tmp_path / "m.csv"),
                    period="min", start_date="2026-08-25", end_date="2026-08-27")


def test_query_index_min_guard(monkeypatch, tmp_path):
    from local_datasource.providers import common
    fake = pd.DataFrame({"day": ["2026-08-26 09:31:00"], "open": [1.0], "close": [1.0]})
    monkeypatch.setattr(common.ak, "stock_zh_a_minute", lambda symbol, period, adjust: fake.copy())
    with pytest.raises(ValueError, match="补数"):
        query_index(symbol="000852", file_path=str(tmp_path / "m.csv"),
                    period="min", start_date="2026-08-01", end_date="2026-08-27")


def test_query_index_min_happy(monkeypatch, tmp_path):
    from local_datasource.providers import common
    fake = pd.DataFrame({
        "day": ["2026-08-26 09:31:00", "2026-08-27 09:31:00"],
        "open": [1.0, 1.1], "close": [1.0, 1.1],
    })
    monkeypatch.setattr(common.ak, "stock_zh_a_minute", lambda symbol, period, adjust: fake.copy())
    _, summary = query_index(symbol="000852", file_path=str(tmp_path / "m.csv"),
                             period="min", start_date="2026-08-27", end_date="2026-08-27")
    assert "Rows: 1" in summary


# ---------- 集成 ----------

@pytest.mark.skipif(os.environ.get("SKIP_INTEGRATION"), reason="integration")
def test_query_index_daily_000852_integration():
    with tempfile.NamedTemporaryFile(suffix=".csv", delete=False) as f:
        path = f.name
    try:
        _, summary = query_index(symbol="000852", file_path=path, period="daily",
                                 start_date="2014-10-01", end_date="2014-12-31")
        assert "Rows:" in summary
    finally:
        os.unlink(path)


@pytest.mark.skipif(os.environ.get("SKIP_INTEGRATION"), reason="integration")
def test_query_index_daily_csindex_integration():
    with tempfile.NamedTemporaryFile(suffix=".csv", delete=False) as f:
        path = f.name
    try:
        _, summary = query_index(symbol="930050", file_path=path, period="daily",
                                 start_date="2024-01-01", end_date="2024-06-30")
        assert "Rows:" in summary
    finally:
        os.unlink(path)