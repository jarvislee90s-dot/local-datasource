# tests/test_etf.py
import os
import tempfile

import pandas as pd
import pytest

from local_datasource.providers.etf import query_etf


def test_normalize_etf_code():
    from local_datasource.providers import etf
    assert etf._normalize_etf_code("510300") == "sh510300"
    assert etf._normalize_etf_code("sh510300") == "sh510300"
    assert etf._normalize_etf_code("159915") == "sz159915"
    assert etf._normalize_etf_code("510300.SH") == "sh510300"
    with pytest.raises(ValueError):
        etf._normalize_etf_code("300300")  # 创业板股票代码不是 ETF
    with pytest.raises(ValueError):
        etf._normalize_etf_code("abc")


def test_query_etf_daily(monkeypatch, tmp_path):
    from local_datasource.providers import etf
    fake = pd.DataFrame({
        "date": ["2026-08-26", "2026-08-27"],
        "open": [4.0, 4.1], "high": [4.2, 4.3], "low": [3.9, 4.0],
        "close": [4.1, 4.2], "volume": [100, 110],
        "amount": [410.0, 462.0], "postVol": [0, 0], "postAmt": [0.0, 0.0],
    })
    monkeypatch.setattr(etf.ak, "fund_etf_hist_sina", lambda symbol: fake.copy())
    _, summary = query_etf(symbol="510300", file_path=str(tmp_path / "e.csv"),
                           period="daily", start_date="2026-08-27", end_date="2026-08-27")
    assert "Rows: 1" in summary


def test_query_etf_min_guard(monkeypatch, tmp_path):
    from local_datasource.providers import common
    fake = pd.DataFrame({"day": ["2026-08-26 09:31:00"], "open": [1.0], "close": [1.0]})
    monkeypatch.setattr(common.ak, "stock_zh_a_minute", lambda symbol, period, adjust: fake.copy())
    with pytest.raises(ValueError, match="补数"):
        query_etf(symbol="510300", file_path=str(tmp_path / "m.csv"),
                  period="min", start_date="2026-08-01", end_date="2026-08-27")


def test_query_etf_min_requires_dates(tmp_path):
    with pytest.raises(ValueError, match="period=min 需提供"):
        query_etf(symbol="510300", file_path=str(tmp_path / "m.csv"), period="min")


def test_query_etf_daily_one_sided_end(monkeypatch, tmp_path):
    """只给 end_date 也应生效,不得返回区间后的数据。"""
    from local_datasource.providers import etf
    fake = pd.DataFrame({
        "date": ["2026-08-26", "2026-08-27"],
        "open": [4.0, 4.1], "high": [4.2, 4.3], "low": [3.9, 4.0],
        "close": [4.1, 4.2], "volume": [100, 110],
    })
    monkeypatch.setattr(etf.ak, "fund_etf_hist_sina", lambda symbol: fake.copy())
    _, summary = query_etf(symbol="510300", file_path=str(tmp_path / "e2.csv"),
                           period="daily", end_date="2026-08-26")
    assert "Rows: 1" in summary


def test_query_etf_unsupported_period(tmp_path):
    with pytest.raises(ValueError, match="Unsupported period"):
        query_etf(symbol="510300", file_path=str(tmp_path / "w.csv"), period="weekly")


def test_normalize_etf_rejects_convertible_bond_codes():
    """110xxx/128xxx 等转债代码不是 ETF,应给明确报错而非 No daily data。"""
    from local_datasource.providers import etf
    with pytest.raises(ValueError, match="Not an ETF code"):
        etf._normalize_etf_code("110038")


def test_normalize_etf_code_prefixed_input_same_digit_rules():
    """带前缀输入与纯数字走同一套数字段校验:股票/转债立即拒绝;前缀写错以数字段为准自动纠正。"""
    from local_datasource.providers import etf
    with pytest.raises(ValueError, match="Not an ETF code"):
        etf._normalize_etf_code("sh600519")  # 股票
    with pytest.raises(ValueError, match="Not an ETF code"):
        etf._normalize_etf_code("sz110038")  # 转债
    assert etf._normalize_etf_code("sz510300") == "sh510300"  # 前缀冲突:数字段为准


@pytest.mark.skipif(os.environ.get("SKIP_INTEGRATION"), reason="integration")
def test_query_etf_daily_510300_integration():
    with tempfile.NamedTemporaryFile(suffix=".csv", delete=False) as f:
        path = f.name
    try:
        _, summary = query_etf(symbol="510300", file_path=path, period="daily",
                               start_date="2012-05-01", end_date="2012-12-31")
        assert "Rows:" in summary
    finally:
        os.unlink(path)
