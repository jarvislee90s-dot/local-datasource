# tests/test_options.py
import os
import tempfile

import pandas as pd
import pytest

from local_datasource.providers.options import query_options


# ---------- 归一化 ----------

def test_normalize_option_code():
    from local_datasource.providers import options
    assert options._normalize_option_code("10003889") == ("10003889", "sse")
    assert options._normalize_option_code("IO2706-P-5600") == ("io2706p5600", "cffex")
    assert options._normalize_option_code("io2609C4200") == ("io2609c4200", "cffex")
    assert options._normalize_option_code("HO 2706 C 5600") == ("ho2706c5600", "cffex")
    with pytest.raises(ValueError):
        options._normalize_option_code("XX2706C5600")  # 非 IO/HO/MO 前缀
    with pytest.raises(ValueError):
        options._normalize_option_code("abc")


# ---------- months ----------

def _fake_sse_day_table():
    """上交所官方当日全表样例:两个标的 × 两个月,标的名按 6 位代码锚定过滤。"""
    return pd.DataFrame({
        "合约编码": ["10011255", "10011256", "10011301", "10011302"],
        "标的券名称及代码": ["50ETF(510050)", "50ETF(510050)", "500ETF(510500)", "500ETF(510500)"],
        "类型": ["认购", "认沽", "认购", "认沽"],
        "行权价": [2.9, 2.9, 6.0, 6.0],
        "到期日": ["2026-09-23", "2026-09-23", "2026-09-23", "2026-12-23"],
    })


def test_query_options_months_sse(monkeypatch, tmp_path):
    """SSE months 从官方当日表统一推导,不再依赖新浪关键字接口(其文档仅覆盖 50ETF/300ETF)。"""
    from local_datasource.providers import options
    monkeypatch.setattr(options.ak, "option_current_day_sse", _fake_sse_day_table)
    _, summary = query_options(kind="months", underlying="50ETF",
                               file_path=str(tmp_path / "m.csv"))
    assert "Rows: 1" in summary and "202609" in summary


def test_query_options_months_sse_500etf_uniform(monkeypatch, tmp_path):
    """四个 SSE 标的共用同一路径:500ETF 也能从官方表锚定出月份。"""
    from local_datasource.providers import options
    monkeypatch.setattr(options.ak, "option_current_day_sse", _fake_sse_day_table)
    _, summary = query_options(kind="months", underlying="500ETF",
                               file_path=str(tmp_path / "m.csv"))
    assert "Rows: 2" in summary and "202609" in summary and "202612" in summary


def test_query_options_months_cffex(monkeypatch, tmp_path):
    from local_datasource.providers import options
    fake = {"沪深300指数": ["io2609", "io2612", "io2703"]}
    monkeypatch.setattr(options.ak, "option_cffex_hs300_list_sina", lambda: fake)
    _, summary = query_options(kind="months", underlying="IO",
                               file_path=str(tmp_path / "m.csv"))
    assert "202609" in summary and "Rows: 3" in summary


# ---------- contracts ----------

def test_query_options_contracts_cffex(monkeypatch, tmp_path):
    from local_datasource.providers import options
    fake = pd.DataFrame({
        "合约代码": ["IO2706-P-5600", "IO2706-C-5600", "IM2612"],
        "上市日": ["2026-06-01"] * 3,
        "最后交易日": ["2027-06-18"] * 3,
    })
    monkeypatch.setattr(options.ak, "futures_contract_info_cffex", lambda date: fake.copy())
    _, summary = query_options(kind="contracts", underlying="IO",
                               file_path=str(tmp_path / "c.csv"), trade_date="2026-08-27")
    assert "Rows: 2" in summary


def test_query_options_contracts_sse_current_day(monkeypatch, tmp_path):
    from local_datasource.providers import options
    fake = pd.DataFrame({
        "合约编码": ["10011255", "10011256"],
        "合约交易代码": ["50ETF购9月2900", "50ETF沽9月2900"],
        "标的券名称及代码": ["50ETF(510050)", "50ETF(510050)"],
        "类型": ["认购", "认沽"],
        "行权价": [2.9, 2.9],
        "到期日": ["2026-09-23", "2026-09-23"],
    })
    monkeypatch.setattr(options.ak, "option_current_day_sse", lambda: fake.copy())
    _, summary = query_options(kind="contracts", underlying="50ETF",
                               file_path=str(tmp_path / "c.csv"))
    assert "Rows: 2" in summary


def test_query_options_contracts_sse_nearest_month_only(monkeypatch, tmp_path):
    """SSE 合约清单只保留最近到期月的行。"""
    from local_datasource.providers import options
    fake = pd.DataFrame({
        "合约编码": ["10011255", "10011300"],
        "合约交易代码": ["50ETF购9月2900", "50ETF购12月2900"],
        "标的券名称及代码": ["50ETF(510050)", "50ETF(510050)"],
        "类型": ["认购", "认购"],
        "行权价": [2.9, 2.9],
        "到期日": ["2026-09-23", "2026-12-23"],
    })
    monkeypatch.setattr(options.ak, "option_current_day_sse", lambda: fake.copy())
    _, summary = query_options(kind="contracts", underlying="50ETF",
                               file_path=str(tmp_path / "c2.csv"))
    assert "Rows: 1" in summary


def test_query_options_contracts_sse_ke220(monkeypatch, tmp_path):
    """科创50ETF 的官方标签是 科创50(588000)/科创板50(588080),按代码锚定必须能命中。"""
    from local_datasource.providers import options
    fake = pd.DataFrame({
        "合约编码": ["10004501", "10011255"],
        "合约交易代码": ["科创50购9月1000", "50ETF购9月2900"],
        "标的券名称及代码": ["科创50(588000)", "50ETF(510050)"],
        "类型": ["认购", "认购"],
        "行权价": [1.0, 2.9],
        "到期日": ["2026-09-23", "2026-09-23"],
    })
    monkeypatch.setattr(options.ak, "option_current_day_sse", lambda: fake.copy())
    _, summary = query_options(kind="contracts", underlying="科创50ETF",
                               file_path=str(tmp_path / "kc.csv"))
    assert "Rows: 1" in summary


def test_query_options_hist_one_sided_start(monkeypatch, tmp_path):
    """hist 只给 start_date 也应生效。"""
    from local_datasource.providers import options
    fake = pd.DataFrame({
        "日期": ["2026-01-05", "2026-01-06"],
        "开盘": [0.1, 0.11], "最高": [0.12, 0.13], "最低": [0.09, 0.1],
        "收盘": [0.11, 0.12], "成交量": [100, 110],
    })
    monkeypatch.setattr(options.ak, "option_sse_daily_sina", lambda symbol: fake.copy())
    _, summary = query_options(kind="hist", symbol="10003889",
                               file_path=str(tmp_path / "h2.csv"),
                               start_date="2026-01-06")
    assert "Rows: 1" in summary


# ---------- hist ----------

def test_query_options_hist_sse(monkeypatch, tmp_path):
    from local_datasource.providers import options
    fake = pd.DataFrame({
        "日期": ["2026-01-05", "2026-01-06"],
        "开盘": [0.1, 0.11], "最高": [0.12, 0.13], "最低": [0.09, 0.1],
        "收盘": [0.11, 0.12], "成交量": [100, 110],
    })
    monkeypatch.setattr(options.ak, "option_sse_daily_sina", lambda symbol: fake.copy())
    _, summary = query_options(kind="hist", symbol="10003889",
                               file_path=str(tmp_path / "h.csv"),
                               start_date="2026-01-06", end_date="2026-01-06")
    assert "Rows: 1" in summary


def test_query_options_hist_cffex(monkeypatch, tmp_path):
    from local_datasource.providers import options
    fake = pd.DataFrame({
        "date": ["2026-01-05", "2026-01-06"],
        "open": [100.0, 101.0], "close": [100.5, 101.5],
    })
    monkeypatch.setattr(options.ak, "option_cffex_hs300_daily_sina", lambda symbol: fake.copy())
    _, summary = query_options(kind="hist", symbol="IO2706-P-5600",
                               file_path=str(tmp_path / "h.csv"))
    assert "Rows: 2" in summary


# ---------- 参数校验 ----------

def test_query_options_requires_underlying_for_months(tmp_path):
    with pytest.raises(ValueError, match="underlying"):
        query_options(kind="months", file_path=str(tmp_path / "x.csv"))


def test_query_options_unsupported_underlying(tmp_path):
    with pytest.raises(ValueError, match="Unrecognized underlying"):
        query_options(kind="months", underlying="XX", file_path=str(tmp_path / "x.csv"))


# ---------- 集成 ----------

@pytest.mark.skipif(os.environ.get("SKIP_INTEGRATION"), reason="integration")
def test_query_options_months_io_integration():
    with tempfile.NamedTemporaryFile(suffix=".csv", delete=False) as f:
        path = f.name
    try:
        _, summary = query_options(kind="months", underlying="IO", file_path=path)
        assert "Rows:" in summary
    finally:
        os.unlink(path)


@pytest.mark.skipif(os.environ.get("SKIP_INTEGRATION"), reason="integration")
def test_query_options_hist_sse_integration():
    """10003889 为已退市旧合约,历史数据稳定,适合做回归样本。"""
    with tempfile.NamedTemporaryFile(suffix=".csv", delete=False) as f:
        path = f.name
    try:
        _, summary = query_options(kind="hist", symbol="10003889", file_path=path)
        assert "Rows:" in summary
    finally:
        os.unlink(path)
