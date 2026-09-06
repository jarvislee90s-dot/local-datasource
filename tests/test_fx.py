# tests/test_fx.py
"""query_fx 单测(全离线,monkeypatch)+ 集成冒烟(mid 连网,SKIP_INTEGRATION=1 跳过)。

契约要点:
- kind 非法报错;currency/symbol/pair 传错 kind 显式报错
- mid:值保持"100 外币"口径原样不换算;currency 过滤只输出指定小写列;
  summary 含"100 外币"字样;未映射币种列报漂移错误
- bochina:symbol(中文名)与起止日期必填,日期转 YYYYMMDD 透传;
  列映射 date/buy/cash_buy/sell/mid/boc_ref
- usdcnh/cross:Yahoo 日线输出 date/close;pair 归一大写无分隔(EUR/USD→EURUSD=X);
  yfinance end 排他 → 请求补一天;Yahoo 失败报错含"不可达"
"""
import os
import tempfile

import pandas as pd
import pytest

from local_datasource.providers import common as ds_common
from local_datasource.providers import fx
from local_datasource.providers.fx import query_fx


# ---------- 参数校验(纯逻辑,不连网) ----------

def test_invalid_kind_raises(tmp_path):
    with pytest.raises(ValueError, match="Unsupported"):
        query_fx(kind="gold", file_path=str(tmp_path / "x.csv"))


def test_param_wrong_kind_raises(tmp_path):
    with pytest.raises(ValueError, match="currency"):
        query_fx(kind="usdcnh", file_path=str(tmp_path / "x.csv"), currency="usd")
    with pytest.raises(ValueError, match="symbol"):
        query_fx(kind="mid", file_path=str(tmp_path / "x.csv"), symbol="美元")
    with pytest.raises(ValueError, match="pair"):
        query_fx(kind="mid", file_path=str(tmp_path / "x.csv"), pair="EUR/USD")


# ---------- mid(monkeypatch,不连网) ----------

def _fake_boc_safe():
    """currency_boc_safe 样例:26 列全字段(日期 + 25 币种,与真实表同构),值为"100 外币"口径。

    早期年份多数币种本就无牌价 → 以 None 表示,产出 CSV 为空单元格(不 dropna)。
    """
    cn = list(fx._BOC_SAFE_COLUMNS)  # 中文币种列,与 provider 映射同序
    data: dict = {
        "美元": [870.0, 870.0, 711.48],
        "欧元": [None, None, 833.05],
        "日元": [7.78, 7.78, 4.8204],
    }
    for name in cn:
        data.setdefault(name, [None, None, 1.0])
    return pd.DataFrame({"日期": ["1994-01-01", "1994-01-03", "2026-09-04"], **data})


def test_mid_keeps_per100_unit_and_filters_columns(monkeypatch, tmp_path):
    """currency=usd,eur → 输出仅 date,usd,eur;数值保持 100 外币口径原样(870 不换算成 8.7)。"""
    monkeypatch.setattr(fx.ak, "currency_boc_safe", _fake_boc_safe)
    file_path, summary = query_fx(
        kind="mid", file_path=str(tmp_path / "m.csv"), currency="usd,eur")
    assert "100 外币" in summary, "mid 的 summary 须注明 100 外币单位口径"
    out = pd.read_csv(file_path)
    assert list(out.columns) == ["date", "usd", "eur"]
    assert out["usd"].tolist() == [870.0, 870.0, 711.48], "数值不得换算(100 外币口径原样)"


def test_mid_no_currency_outputs_all_mapped_columns(monkeypatch, tmp_path):
    """缺省 currency → 输出日期 + 全部已映射币种列(映射表顺序),且按日期升序。"""
    monkeypatch.setattr(fx.ak, "currency_boc_safe", _fake_boc_safe)
    file_path, summary = query_fx(kind="mid", file_path=str(tmp_path / "m.csv"))
    assert "100 外币" in summary
    out = pd.read_csv(file_path)
    assert list(out.columns) == ["date"] + list(fx._BOC_SAFE_COLUMNS.values())
    assert out["date"].tolist() == ["1994-01-01", "1994-01-03", "2026-09-04"]


def test_mid_case_insensitive_and_unknown_code_raises(monkeypatch, tmp_path):
    monkeypatch.setattr(fx.ak, "currency_boc_safe", _fake_boc_safe)
    # 大小写不敏感 + 空白分隔
    file_path, _ = query_fx(kind="mid", file_path=str(tmp_path / "m.csv"), currency="USD jpy")
    assert list(pd.read_csv(file_path).columns) == ["date", "usd", "jpy"]
    # 未知代码 → 可读错误列出有效代码
    with pytest.raises(ValueError, match="未知币种代码") as excinfo:
        query_fx(kind="mid", file_path=str(tmp_path / "x.csv"), currency="usd,foo")
    assert "eur" in str(excinfo.value), "错误应列出有效代码"


def test_mid_unmapped_column_drift_raises(monkeypatch, tmp_path):
    """上游新增未映射币种列 → 报可读漂移错误而非静默丢弃。"""
    drifted = _fake_boc_safe()
    drifted["新币种"] = [1.0, 1.0, 1.0]
    monkeypatch.setattr(fx.ak, "currency_boc_safe", lambda: drifted)
    with pytest.raises(ValueError, match="未映射币种列"):
        query_fx(kind="mid", file_path=str(tmp_path / "x.csv"))


def test_mid_column_missing_drift_raises(monkeypatch, tmp_path):
    drifted = _fake_boc_safe().drop(columns=["美元"])
    monkeypatch.setattr(fx.ak, "currency_boc_safe", lambda: drifted)
    with pytest.raises(ValueError, match="列名不受支持"):
        query_fx(kind="mid", file_path=str(tmp_path / "x.csv"), currency="usd")


def test_mid_date_filter(monkeypatch, tmp_path):
    monkeypatch.setattr(fx.ak, "currency_boc_safe", _fake_boc_safe)
    file_path, _ = query_fx(
        kind="mid", file_path=str(tmp_path / "m.csv"),
        start_date="1994-01-03", end_date="1994-01-03")
    out = pd.read_csv(file_path)
    assert out["date"].tolist() == ["1994-01-03"]


# ---------- bochina(monkeypatch,不连网) ----------

def _fake_boc_sina(**kwargs):
    return pd.DataFrame({
        "日期": ["2022-12-06", "2022-12-07"],
        "中行汇买价": [7.0326, 7.0105],
        "中行钞买价": [6.9662, 6.9444],
        "中行钞卖价/汇卖价": [7.0624, 7.0405],
        "央行中间价": [7.0384, 7.0095],
        "中行折算价": [7.0384, 7.0095],
    })


def test_bochina_requires_symbol(tmp_path):
    with pytest.raises(ValueError, match="symbol"):
        query_fx(kind="bochina", file_path=str(tmp_path / "x.csv"),
                 start_date="2022-12-06", end_date="2022-12-07")


def test_bochina_requires_dates(tmp_path):
    with pytest.raises(ValueError, match="start_date"):
        query_fx(kind="bochina", file_path=str(tmp_path / "x.csv"), symbol="美元")


def test_bochina_passes_compact_dates_and_maps_columns(monkeypatch, tmp_path):
    """日期转 YYYYMMDD 透传;中文列映射 date/buy/cash_buy/sell/mid/boc_ref。"""
    called = {}

    def fake_sina(**kwargs):
        called.update(kwargs)
        return _fake_boc_sina(**kwargs)

    monkeypatch.setattr(fx.ak, "currency_boc_sina", fake_sina)
    file_path, _ = query_fx(
        kind="bochina", file_path=str(tmp_path / "b.csv"), symbol="美元",
        start_date="2022-12-06", end_date="2022-12-07")
    assert called == {"symbol": "美元", "start_date": "20221206", "end_date": "20221207"}
    out = pd.read_csv(file_path)
    assert list(out.columns) == ["date", "buy", "cash_buy", "sell", "mid", "boc_ref"]
    assert out["mid"].tolist() == [7.0384, 7.0095]
    assert out["date"].tolist() == ["2022-12-06", "2022-12-07"]


def test_bochina_column_drift_raises(monkeypatch, tmp_path):
    drifted = _fake_boc_sina().rename(columns={"央行中间价": "中间价"})
    monkeypatch.setattr(fx.ak, "currency_boc_sina", lambda **kwargs: drifted)
    with pytest.raises(ValueError, match="列名不受支持"):
        query_fx(kind="bochina", file_path=str(tmp_path / "x.csv"), symbol="美元",
                 start_date="2022-12-06", end_date="2022-12-07")


def test_bochina_empty_result_raises(monkeypatch, tmp_path):
    monkeypatch.setattr(fx.ak, "currency_boc_sina", lambda **kwargs: pd.DataFrame())
    with pytest.raises(ValueError, match="空数据"):
        query_fx(kind="bochina", file_path=str(tmp_path / "x.csv"), symbol="美元",
                 start_date="1990-01-01", end_date="1990-01-31")


def test_bochina_empty_after_date_filter_raises(monkeypatch, tmp_path):
    """上游返回的行全部落在请求区间之外 → 报"区间无数据"而非写出空表 CSV。"""
    monkeypatch.setattr(fx.ak, "currency_boc_sina", lambda **kwargs: _fake_boc_sina())
    with pytest.raises(ValueError, match="区间无数据"):
        query_fx(kind="bochina", file_path=str(tmp_path / "x.csv"), symbol="美元",
                 start_date="2023-01-01", end_date="2023-01-31")


# ---------- usdcnh / cross(monkeypatch yfinance,不连网) ----------

def _fake_yf_frame(ticker):
    """模拟 yfinance(>=0.2.54)单标的下载:MultiIndex 列 + Date 索引 + 一行 close 缺失。"""
    idx = pd.DatetimeIndex(pd.to_datetime(
        ["2026-01-05", "2026-01-06", "2026-01-07", "2026-01-08"]), name="Date")
    cols = pd.MultiIndex.from_product([["Open", "High", "Low", "Close", "Volume"], [ticker]])
    data = [
        [7.30, 7.31, 7.29, 7.305, 0],
        [7.30, 7.32, 7.28, 7.312, 0],
        [7.31, 7.33, 7.30, float("nan"), 0],
        [7.31, 7.34, 7.30, 7.325, 0],
    ]
    return pd.DataFrame(data, index=idx, columns=cols)


def test_usdcnh_outputs_date_close(monkeypatch, tmp_path):
    """MultiIndex 拍平后仅保留 date/close;close 缺失行丢弃;升序。"""
    captured = {}

    def fake_download(ticker, **kwargs):
        captured["ticker"] = ticker
        return _fake_yf_frame(ticker)

    monkeypatch.setattr(ds_common.yf, "download", fake_download)
    file_path, _ = query_fx(kind="usdcnh", file_path=str(tmp_path / "u.csv"))
    assert captured["ticker"] == "USDCNH=X"
    out = pd.read_csv(file_path)
    assert list(out.columns) == ["date", "close"]
    assert out["date"].tolist() == ["2026-01-05", "2026-01-06", "2026-01-08"]
    assert out["close"].tolist() == [7.305, 7.312, 7.325]


def test_usdcnh_yahoo_unreachable(monkeypatch, tmp_path):
    """本机被 Yahoo 拒时 yfinance 返回空表 → 报错须含"不可达";异常路径同样含。"""
    monkeypatch.setattr(ds_common.yf, "download", lambda ticker, **kwargs: pd.DataFrame())
    with pytest.raises(ValueError, match="不可达"):
        query_fx(kind="usdcnh", file_path=str(tmp_path / "x.csv"))

    def fail_download(ticker, **kwargs):
        raise ConnectionError("yahoo blocked")

    monkeypatch.setattr(ds_common.yf, "download", fail_download)
    with pytest.raises(ValueError, match="不可达") as excinfo:
        query_fx(kind="usdcnh", file_path=str(tmp_path / "x.csv"))
    assert excinfo.value.__cause__ is not None, "应保留原始网络异常链"


def test_yahoo_end_day_inclusive(monkeypatch, tmp_path):
    """yfinance 的 end 为排他区间 → 实现应补一天,输出仍含 end_date 当日(闭区间契约)。"""
    captured = {}

    def fake_download(ticker, **kwargs):
        captured.update(kwargs)
        # 模拟 yfinance 尊重排他 end:只返回 01-05..01-08(不含补的 01-09)
        return _fake_yf_frame(ticker).loc[:"2026-01-08"]

    monkeypatch.setattr(ds_common.yf, "download", fake_download)
    file_path, _ = query_fx(
        kind="usdcnh", file_path=str(tmp_path / "u.csv"),
        start_date="2026-01-05", end_date="2026-01-08")
    assert captured["start"] == "2026-01-05"
    assert captured["end"] == "2026-01-09", "yfinance end 排他,应补一天"
    out = pd.read_csv(file_path)
    assert out["date"].tolist()[-1] == "2026-01-08", "闭区间契约:end_date 当日不得缺失"


def test_cross_requires_pair(tmp_path):
    with pytest.raises(ValueError, match="pair"):
        query_fx(kind="cross", file_path=str(tmp_path / "x.csv"))


def test_cross_pair_normalization(monkeypatch, tmp_path):
    """eur/usd 归一为 EURUSD → 调用 EURUSD=X;输出 date/close。"""
    captured = {}

    def fake_download(ticker, **kwargs):
        captured["ticker"] = ticker
        return _fake_yf_frame(ticker)

    monkeypatch.setattr(ds_common.yf, "download", fake_download)
    file_path, _ = query_fx(
        kind="cross", file_path=str(tmp_path / "c.csv"), pair="eur/usd")
    assert captured["ticker"] == "EURUSD=X"
    out = pd.read_csv(file_path)
    assert list(out.columns) == ["date", "close"]
    assert out["date"].is_monotonic_increasing


def test_cross_invalid_pair_raises(monkeypatch, tmp_path):
    with pytest.raises(ValueError, match="Unrecognized pair"):
        query_fx(kind="cross", file_path=str(tmp_path / "x.csv"), pair="美元/日元")


# ---------- 集成冒烟(连网,SKIP_INTEGRATION=1 跳过) ----------

@pytest.mark.skipif(os.environ.get("SKIP_INTEGRATION"), reason="integration")
def test_smoke_mid_since_1994():
    """契约阈值(不得弱化):最早日期 ≤ 1994-01-04,行数 > 7000,summary 含 100 外币。"""
    with tempfile.NamedTemporaryFile(suffix=".csv", delete=False) as f:
        path = f.name
    try:
        file_path, summary = query_fx(kind="mid", file_path=path)
        assert "100 外币" in summary
        out = pd.read_csv(file_path)
        assert len(out) > 7000
        assert out["date"].min() <= "1994-01-04"
        assert "usd" in out.columns and "eur" in out.columns
        assert out["date"].is_monotonic_increasing
    finally:
        os.unlink(path)
