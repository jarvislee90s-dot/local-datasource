# tests/test_spot.py
"""query_spot 单测(全离线,monkeypatch)+ 集成冒烟(连网,SKIP_INTEGRATION=1 跳过)。

契约要点:
- kind 非法报错;symbol/symbols 传错 kind 显式报错
- sge:symbol 必填且须在品种表内(未知品种报错列出有效品种);
  源列 date/open/close/low/high 重排为 date,open,high,low,close
- sy:symbols 与起止日期必填;区间 > 1 年(366 天)报错文案含"缩小范围",
  365 天放行且确实发出 akshare 调用;13 列源精选 7 列
  date/symbol/spot_price/dominant_contract/dominant_contract_price/dom_basis/dom_basis_rate
"""
import datetime
import os
import tempfile

import pandas as pd
import pytest

from local_datasource.providers import spot
from local_datasource.providers.spot import query_spot


# ---------- 参数校验(纯逻辑,不连网) ----------

def test_invalid_kind_raises(tmp_path):
    with pytest.raises(ValueError, match="Unsupported"):
        query_spot(kind="gold", file_path=str(tmp_path / "x.csv"))


def test_param_wrong_kind_raises(tmp_path):
    with pytest.raises(ValueError, match="symbol"):
        query_spot(kind="sy", file_path=str(tmp_path / "x.csv"), symbol="Au99.99")
    with pytest.raises(ValueError, match="symbols"):
        query_spot(kind="sge", file_path=str(tmp_path / "x.csv"), symbols=["CU"])


# ---------- sge(monkeypatch,不连网) ----------

_FAKE_SGE_TABLE = pd.DataFrame({"品种": ["Au99.99", "Ag99.99", "Au(T+D)"]})


def _fake_sge_hist(symbol):
    """spot_hist_sge 样例:源列顺序 date/open/close/low/high(close 在 low/high 前),
    date 为 datetime.date(与真实源一致),故意乱序。"""
    return pd.DataFrame({
        "date": [datetime.date(2026, 1, 5), datetime.date(2016, 12, 19)],
        "open": [510.0, 260.0],
        "close": [512.0, 262.0],
        "low": [508.0, 258.0],
        "high": [513.0, 264.0],
    })


def test_sge_reorders_columns(monkeypatch, tmp_path):
    """源列 date/open/close/low/high → 输出 date,open,high,low,close;日期升序。"""
    monkeypatch.setattr(spot.ak, "spot_symbol_table_sge", lambda: _FAKE_SGE_TABLE)
    monkeypatch.setattr(spot.ak, "spot_hist_sge", _fake_sge_hist)
    file_path, _ = query_spot(kind="sge", symbol="Au99.99", file_path=str(tmp_path / "s.csv"))
    out = pd.read_csv(file_path)
    assert list(out.columns) == ["date", "open", "high", "low", "close"]
    assert out["date"].tolist() == ["2016-12-19", "2026-01-05"], "输出应按日期升序"
    assert out.loc[0, "high"] == 264.0 and out.loc[0, "low"] == 258.0


def test_sge_requires_symbol(tmp_path):
    with pytest.raises(ValueError, match="symbol"):
        query_spot(kind="sge", file_path=str(tmp_path / "x.csv"))


def test_sge_unknown_symbol_raises_listing_valid(monkeypatch, tmp_path):
    monkeypatch.setattr(spot.ak, "spot_symbol_table_sge", lambda: _FAKE_SGE_TABLE)
    with pytest.raises(ValueError, match="未知上金所品种") as excinfo:
        query_spot(kind="sge", symbol="Xu99.99", file_path=str(tmp_path / "x.csv"))
    assert "Au99.99" in str(excinfo.value), "错误应列出有效品种"


def test_sge_column_drift_raises(monkeypatch, tmp_path):
    drifted = _fake_sge_hist("Au99.99").drop(columns=["high"])
    monkeypatch.setattr(spot.ak, "spot_symbol_table_sge", lambda: _FAKE_SGE_TABLE)
    monkeypatch.setattr(spot.ak, "spot_hist_sge", lambda symbol: drifted)
    with pytest.raises(ValueError, match="列名不受支持"):
        query_spot(kind="sge", symbol="Au99.99", file_path=str(tmp_path / "x.csv"))


def test_sge_date_filter(monkeypatch, tmp_path):
    monkeypatch.setattr(spot.ak, "spot_symbol_table_sge", lambda: _FAKE_SGE_TABLE)
    monkeypatch.setattr(spot.ak, "spot_hist_sge", _fake_sge_hist)
    file_path, _ = query_spot(
        kind="sge", symbol="Au99.99", file_path=str(tmp_path / "s.csv"),
        start_date="2026-01-01", end_date="2026-01-31")
    out = pd.read_csv(file_path)
    assert out["date"].tolist() == ["2026-01-05"]


# ---------- sy(monkeypatch,不连网) ----------

def _fake_sy_df(**kwargs):
    """futures_spot_price_daily 样例:完整 13 列源表,date 为 YYYYMMDD 字符串(与真实源一致)。"""
    return pd.DataFrame({
        "date": ["20260102", "20260105"],
        "symbol": ["CU", "CU"],
        "spot_price": [68520.0, 69010.0],
        "near_contract": ["cu2601", "cu2601"],
        "near_contract_price": [68490.0, 68950.0],
        "dominant_contract": ["cu2602", "cu2602"],
        "dominant_contract_price": [68610.0, 69080.0],
        "near_month": ["2601", "2601"],
        "dominant_month": ["2602", "2602"],
        "near_basis": [30.0, 60.0],
        "dom_basis": [-90.0, -70.0],
        "near_basis_rate": [0.000438, 0.000870],
        "dom_basis_rate": [-0.001314, -0.001014],
    })


def test_sy_rejects_range_over_one_year(monkeypatch, tmp_path):
    """366 天(> 1 年)→ 报错文案含"缩小范围",且不得发出 akshare 调用。"""
    calls = []

    def recorder(**kwargs):
        calls.append(kwargs)
        return _fake_sy_df(**kwargs)

    monkeypatch.setattr(spot.ak, "futures_spot_price_daily", recorder)
    with pytest.raises(ValueError, match="缩小范围") as excinfo:
        query_spot(
            kind="sy", symbols=["CU"], file_path=str(tmp_path / "x.csv"),
            start_date="2026-01-01", end_date="2027-01-02")  # 366 天
    assert "1 年" in str(excinfo.value), "错误文案须注明 1 年上限"
    assert calls == [], "超限时不得发出 akshare 调用"


def test_sy_allows_365_days_and_calls_akshare(monkeypatch, tmp_path):
    """365 天恰好在限内 → 放行且确实发出 akshare 调用(参数原样透传)。"""
    calls = []

    def recorder(**kwargs):
        calls.append(kwargs)
        return _fake_sy_df(**kwargs)

    monkeypatch.setattr(spot.ak, "futures_spot_price_daily", recorder)
    file_path, _ = query_spot(
        kind="sy", symbols=["CU"], file_path=str(tmp_path / "s.csv"),
        start_date="2026-01-01", end_date="2027-01-01")  # 365 天,放行
    assert len(calls) == 1, "365 天应放行并发起调用"
    assert calls[0] == {"start_day": "2026-01-01", "end_day": "2027-01-01", "vars_list": ["CU"]}
    out = pd.read_csv(file_path)
    assert "dom_basis" in out.columns


def test_sy_requires_dates(tmp_path):
    with pytest.raises(ValueError, match="start_date"):
        query_spot(kind="sy", symbols=["CU"], file_path=str(tmp_path / "x.csv"))


def test_sy_requires_symbols(tmp_path):
    with pytest.raises(ValueError, match="symbols"):
        query_spot(
            kind="sy", file_path=str(tmp_path / "x.csv"),
            start_date="2026-01-01", end_date="2026-06-30")


def test_sy_rejects_non_iso_date_format(tmp_path):
    """pd.Timestamp 宽松解析("20260101"/"2026/01/01")后,字符串比较会静默过滤掉
    全部行并误报"区间无数据" → 区间检查前须严格校验 YYYY-MM-DD。"""
    with pytest.raises(ValueError, match="日期格式需为 YYYY-MM-DD"):
        query_spot(
            kind="sy", symbols=["CU"], file_path=str(tmp_path / "x.csv"),
            start_date="20260101", end_date="2026-06-30")
    with pytest.raises(ValueError, match="日期格式需为 YYYY-MM-DD"):
        query_spot(
            kind="sy", symbols=["CU"], file_path=str(tmp_path / "x.csv"),
            start_date="2026-01-01", end_date="2026/06/30")


def test_sy_output_column_selection(monkeypatch, tmp_path):
    """13 列源 df → 只输出 7 个精选列;date 归一 YYYY-MM-DD 且升序。"""
    monkeypatch.setattr(spot.ak, "futures_spot_price_daily", lambda **kwargs: _fake_sy_df())
    file_path, _ = query_spot(
        kind="sy", symbols=["CU"], file_path=str(tmp_path / "s.csv"),
        start_date="2026-01-01", end_date="2026-06-30")
    out = pd.read_csv(file_path)
    assert list(out.columns) == [
        "date", "symbol", "spot_price",
        "dominant_contract", "dominant_contract_price",
        "dom_basis", "dom_basis_rate",
    ]
    assert len(out) == 2
    assert out["date"].tolist() == ["2026-01-02", "2026-01-05"], "YYYYMMDD 源应归一并升序"
    assert out["dom_basis"].tolist() == [-90.0, -70.0]


def test_sy_symbols_normalized(monkeypatch, tmp_path):
    """symbols 容错:字符串当单元素列表;strip+大写+去重。"""
    calls = []
    for raw in ["cu", [" cu ", "RB"], ["CU", "cu", " RB "]]:

        def recorder(**kwargs):
            calls.append(kwargs["vars_list"])
            return _fake_sy_df(**kwargs)

        monkeypatch.setattr(spot.ak, "futures_spot_price_daily", recorder)
        file_path, _ = query_spot(
            kind="sy", symbols=raw, file_path=str(tmp_path / "s.csv"),
            start_date="2026-01-01", end_date="2026-06-30")
    assert calls == [["CU"], ["CU", "RB"], ["CU", "RB"]]


def test_sy_empty_result_raises(monkeypatch, tmp_path):
    monkeypatch.setattr(spot.ak, "futures_spot_price_daily", lambda **kwargs: pd.DataFrame())
    with pytest.raises(ValueError, match="空数据"):
        query_spot(
            kind="sy", symbols=["CU"], file_path=str(tmp_path / "x.csv"),
            start_date="2026-01-01", end_date="2026-06-30")


def test_sy_empty_after_date_filter_raises(monkeypatch, tmp_path):
    """源返回行全部落在请求区间之外 → 报"区间无数据"而非写出空表 CSV。"""
    monkeypatch.setattr(spot.ak, "futures_spot_price_daily", lambda **kwargs: _fake_sy_df())
    with pytest.raises(ValueError, match="区间无数据"):
        query_spot(
            kind="sy", symbols=["CU"], file_path=str(tmp_path / "x.csv"),
            start_date="2026-07-01", end_date="2026-12-31")


# ---------- 集成冒烟(连网,SKIP_INTEGRATION=1 跳过) ----------

@pytest.mark.skipif(os.environ.get("SKIP_INTEGRATION"), reason="integration")
def test_smoke_sge_au9999():
    """契约阈值(不得弱化):行数 ≥ 2000,输出列重排为 date,open,high,low,close。"""
    with tempfile.NamedTemporaryFile(suffix=".csv", delete=False) as f:
        path = f.name
    try:
        file_path, _ = query_spot(kind="sge", symbol="Au99.99", file_path=path)
        out = pd.read_csv(file_path)
        assert len(out) >= 2000
        assert list(out.columns) == ["date", "open", "high", "low", "close"]
        assert out["date"].min() <= "2017-01-01"
        assert out["date"].is_monotonic_increasing
    finally:
        os.unlink(path)


@pytest.mark.skipif(os.environ.get("SKIP_INTEGRATION"), reason="integration")
def test_smoke_sy_cu_half_year():
    """2026 年内半年区间 CU:非空且含 dom_basis 列(生意社逐日抓取,约需 1 分钟)。"""
    with tempfile.NamedTemporaryFile(suffix=".csv", delete=False) as f:
        path = f.name
    try:
        file_path, _ = query_spot(
            kind="sy", symbols=["CU"], file_path=path,
            start_date="2026-01-01", end_date="2026-06-30")
        out = pd.read_csv(file_path)
        assert not out.empty
        assert "dom_basis" in out.columns
        assert "dom_basis_rate" in out.columns
        assert out["date"].is_monotonic_increasing
    finally:
        os.unlink(path)
