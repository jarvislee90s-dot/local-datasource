# tests/test_futures.py
import os
import tempfile

import pandas as pd
import pytest

from local_datasource.providers.futures import query_futures


# ---------- 归一化(纯函数,不连网) ----------

def test_normalize_futures_code():
    from local_datasource.providers import futures
    assert futures._normalize_futures_code("im2612") == "IM2612"
    assert futures._normalize_futures_code(" IM2612 ") == "IM2612"
    assert futures._normalize_futures_code("IM主连") == "IM0"
    assert futures._normalize_futures_code("im0") == "IM0"
    with pytest.raises(ValueError):
        futures._normalize_futures_code("不合法")


def test_exchange_of_variety():
    from local_datasource.providers import futures
    assert futures._exchange_of_variety("IM") == "CFFEX"
    assert futures._exchange_of_variety("rb") == "SHFE"
    # CZCE 活跃品种不得缺映射(实测 2026-08 挂牌表:AP 苹果/CJ 红枣/PK 花生/PL 瓶片/PR/SF 硅铁/SM 锰硅/ZC)
    for v in ["AP", "CJ", "PK", "PL", "PR", "SF", "SM", "ZC"]:
        assert futures._exchange_of_variety(v) == "CZCE", v
    with pytest.raises(ValueError, match="未识别品种"):
        futures._exchange_of_variety("XX")


def test_query_futures_invalid_kind(tmp_path):
    """非法 kind 直接报错,不得静默落入 hist 分支(与 period 校验一致的防静默降级)。"""
    with pytest.raises(ValueError, match="Unsupported futures kind"):
        query_futures(symbol="IM2612", file_path=str(tmp_path / "x.csv"), kind="contractz")


def test_normalize_futures_code_bare_variety_hints_contracts():
    """纯品种代码配 kind=hist 时,报错应提示改用 kind=contracts 查挂牌合约。"""
    from local_datasource.providers import futures
    with pytest.raises(ValueError, match="kind=contracts"):
        futures._normalize_futures_code("IM")


# ---------- hist daily(monkeypatch,不连网) ----------

def _fake_daily():
    return pd.DataFrame({
        "date": ["2026-04-20", "2026-04-21", "2026-04-22"],
        "open": [3900.0, 3910.0, 3920.0],
        "high": [3950.0, 3960.0, 3970.0],
        "low": [3880.0, 3890.0, 3900.0],
        "close": [3920.0, 3930.0, 3940.0],
        "volume": [1000, 1100, 1200],
        "hold": [5000, 5100, 5200],
        "settle": [3920.0, 3930.0, 3940.0],
    })


def test_query_futures_daily_single_contract(monkeypatch, tmp_path):
    from local_datasource.providers import futures
    monkeypatch.setattr(futures.ak, "futures_zh_daily_sina", lambda symbol: _fake_daily())
    file_path, summary = query_futures(
        symbol="im2612", file_path=str(tmp_path / "f.csv"),
        period="daily", start_date="2026-04-21", end_date="2026-04-22",
    )
    assert "Rows: 2" in summary


def test_query_futures_daily_main_uses_main_api(monkeypatch, tmp_path):
    from local_datasource.providers import futures
    called = {}

    def fake_main(symbol, start_date, end_date):
        called["symbol"] = symbol
        return pd.DataFrame({
            "日期": ["2026-08-26", "2026-08-27"],
            "开盘价": [3900.0, 3910.0], "最高价": [3950.0, 3960.0],
            "最低价": [3880.0, 3890.0], "收盘价": [3920.0, 3930.0],
            "成交量": [1000, 1100], "持仓量": [5000, 5100], "动态结算价": [3920.0, 3930.0],
        })

    monkeypatch.setattr(futures.ak, "futures_main_sina", fake_main)
    _, summary = query_futures(symbol="IM0", file_path=str(tmp_path / "main.csv"), period="daily")
    assert called["symbol"] == "IM0"
    assert "Rows: 2" in summary


def _fake_main_daily():
    return pd.DataFrame({
        "日期": ["2026-08-26", "2026-08-27", "2026-08-28"],
        "开盘价": [3900.0, 3910.0, 3920.0], "最高价": [3950.0, 3960.0, 3970.0],
        "最低价": [3880.0, 3890.0, 3900.0], "收盘价": [3920.0, 3930.0, 3940.0],
        "成交量": [1000, 1100, 1200], "持仓量": [5000, 5100, 5200],
        "动态结算价": [3921.0, 3931.0, 3941.0],
    })


def test_futures_main_continuation_columns_normalized(monkeypatch, tmp_path):
    """主连日线输出列名归一:中文上游列 → 与单合约一致的 8 个英文列(契约),值原样保留。"""
    from local_datasource.providers import futures
    monkeypatch.setattr(
        futures.ak, "futures_main_sina",
        lambda symbol, start_date, end_date: _fake_main_daily(),
    )
    file_path = str(tmp_path / "main.csv")
    _, summary = query_futures(symbol="IM0", file_path=file_path, period="daily")
    assert "Rows: 3" in summary
    df = pd.read_csv(file_path, encoding="utf-8-sig")
    assert list(df.columns) == ["date", "open", "high", "low", "close", "volume", "hold", "settle"]
    assert df.loc[0, "date"] == "2026-08-26"
    assert df.loc[0, "settle"] == 3921.0
    assert df.loc[2, "volume"] == 1200
    assert df.loc[1, "close"] == 3930.0


def test_futures_single_contract_columns_unchanged(monkeypatch, tmp_path):
    """单合约日线输出列名与契约文档一致(回归保护,不被主连归一改动波及)。"""
    from local_datasource.providers import futures
    monkeypatch.setattr(futures.ak, "futures_zh_daily_sina", lambda symbol: _fake_daily())
    file_path = str(tmp_path / "single.csv")
    _, summary = query_futures(symbol="IM2612", file_path=file_path, period="daily")
    assert "Rows: 3" in summary
    df = pd.read_csv(file_path, encoding="utf-8-sig")
    assert list(df.columns) == ["date", "open", "high", "low", "close", "volume", "hold", "settle"]


# ---------- hist min(守卫) ----------

def test_query_futures_min_guard_raises(monkeypatch, tmp_path):
    from local_datasource.providers import futures
    fake = pd.DataFrame({
        "datetime": ["2026-08-26 09:31:00", "2026-08-27 15:00:00"],
        "open": [1.0, 1.1], "close": [1.0, 1.1], "volume": [10, 11], "hold": [5, 6],
    })
    monkeypatch.setattr(futures.ak, "futures_zh_minute_sina", lambda symbol, period: fake.copy())
    with pytest.raises(ValueError, match="补数"):
        query_futures(symbol="IM2612", file_path=str(tmp_path / "m.csv"),
                      period="min", start_date="2026-08-01", end_date="2026-08-27")


def test_query_futures_min_requires_dates(tmp_path):
    with pytest.raises(ValueError, match="period=min 需提供"):
        query_futures(symbol="IM2612", file_path=str(tmp_path / "m.csv"), period="min")


# ---------- contracts ----------

def test_query_futures_contracts(monkeypatch, tmp_path):
    from local_datasource.providers import futures
    fake = pd.DataFrame({
        "合约代码": ["IM2609", "IM2612", "IF2609", "IO2706-P-5600"],
        "合约月份": ["2609", "2612", "2609", "2706"],
        "挂盘基准价": [1.0, 1.0, 1.0, 1.0],
        "上市日": ["2026-01-01"] * 4,
        "最后交易日": ["2026-09-18", "2026-12-18", "2026-09-18", "2027-06-18"],
    })
    monkeypatch.setattr(futures.ak, "futures_contract_info_cffex", lambda date: fake.copy())
    _, summary = query_futures(symbol="IM", kind="contracts", file_path=str(tmp_path / "c.csv"))
    assert "Rows: 2" in summary


def test_query_futures_contracts_no_prefix_collision(monkeypatch, tmp_path):
    """品种前缀过滤不能混入更长前缀的品种(实测 DCE: J 会撞 JD/JM)。"""
    from local_datasource.providers import futures
    fake = pd.DataFrame({"合约代码": ["J2609", "JD2609", "JM2609"]})
    monkeypatch.setattr(futures.ak, "futures_contract_info_dce", lambda: fake.copy())
    _, summary = query_futures(symbol="J", kind="contracts", file_path=str(tmp_path / "j.csv"))
    assert "Rows: 1" in summary


def test_query_futures_daily_single_contract_one_sided_start(monkeypatch, tmp_path):
    """只给 start_date 时也应生效,不得静默返回全历史。"""
    from local_datasource.providers import futures
    monkeypatch.setattr(futures.ak, "futures_zh_daily_sina", lambda symbol: _fake_daily())
    _, summary = query_futures(symbol="IM2612", file_path=str(tmp_path / "o.csv"),
                               period="daily", start_date="2026-04-21")
    assert "Rows: 2" in summary


# ---------- 集成(连网,SKIP_INTEGRATION=1 跳过) ----------

@pytest.mark.skipif(os.environ.get("SKIP_INTEGRATION"), reason="integration")
def test_query_futures_daily_im2612_integration():
    with tempfile.NamedTemporaryFile(suffix=".csv", delete=False) as f:
        path = f.name
    try:
        _, summary = query_futures(symbol="IM2612", file_path=path, period="daily",
                                   start_date="2026-04-01", end_date="2026-08-28")
        assert "Rows:" in summary
    finally:
        os.unlink(path)


@pytest.mark.skipif(os.environ.get("SKIP_INTEGRATION"), reason="integration")
def test_query_futures_contracts_im_integration():
    with tempfile.NamedTemporaryFile(suffix=".csv", delete=False) as f:
        path = f.name
    try:
        _, summary = query_futures(symbol="IM", kind="contracts", file_path=path, trade_date="2026-08-27")
        assert "Rows:" in summary
    finally:
        os.unlink(path)