# tests/test_common.py
import pandas as pd
import pytest

from local_datasource.providers.common import (
    filter_by_date,
    filter_by_datetime,
    guard_minute_depth,
    require_columns,
    require_minute_range,
    to_compact_date,
    validate_period,
    fetch_tencent_minute,
)


def test_filter_by_date_none_bounds_return_all():
    """边界缺省表示该侧不设限,调用方不再需要拼哨兵日期。"""
    df = pd.DataFrame({"date": ["2026-01-02", "2026-01-05", "2026-01-06"]})
    assert len(filter_by_date(df)) == 3
    assert len(filter_by_date(df, end_date="2026-01-02")) == 1
    assert len(filter_by_date(df, start_date="2026-01-05")) == 2


def test_filter_by_datetime_none_bounds_return_all():
    df = pd.DataFrame({"datetime": ["2026-08-25 09:31:00", "2026-08-26 09:31:00"]})
    assert len(filter_by_datetime(df)) == 2
    assert len(filter_by_datetime(df, start_date="2026-08-26")) == 1


def test_require_minute_range():
    with pytest.raises(ValueError, match="period=min 需提供"):
        require_minute_range(None, "2026-08-27")
    with pytest.raises(ValueError, match="period=min 需提供"):
        require_minute_range("2026-08-25", "")
    require_minute_range("2026-08-25", "2026-08-27")  # 合法不抛


def test_validate_period():
    with pytest.raises(ValueError, match="Unsupported period"):
        validate_period("weekly")
    validate_period("daily")
    validate_period("min")


def test_require_columns():
    """上游列漂移守卫:缺列时报可读错误(缺失列 + 数据源 + 版本指引)。"""
    df = pd.DataFrame({"date": ["2026-01-05"], "close": [1.0]})
    require_columns(df, ["date", "close"], "测试源")  # 列齐不抛
    with pytest.raises(ValueError, match=r"测试源.*缺 \['high'\].*请检查 akshare 版本"):
        require_columns(df, ["date", "high"], "测试源")
    with pytest.raises(ValueError, match="请检查 yfinance 版本"):
        require_columns(df, ["high"], "yfinance 测试源", hint="请检查 yfinance 版本")


def test_filter_by_date_string_column():
    df = pd.DataFrame({"date": ["2026-01-02", "2026-01-05", "2026-01-06"]})
    out = filter_by_date(df, "2026-01-03", "2026-01-06")
    assert out["date"].tolist() == ["2026-01-05", "2026-01-06"]


def test_filter_by_date_chinese_column_and_datetime_input():
    """期货主连的"日期"列,输入可能是 datetime 对象,统一转字符串再过滤。"""
    df = pd.DataFrame({"日期": pd.to_datetime(["2026-01-02", "2026-01-05"])})
    out = filter_by_date(df, "2026-01-03", "2026-01-31", date_col="日期")
    assert out["日期"].tolist() == ["2026-01-05"]


def test_filter_by_datetime_takes_date_part():
    df = pd.DataFrame({"datetime": ["2026-08-25 09:31:00", "2026-08-26 09:31:00"]})
    out = filter_by_datetime(df, "2026-08-26", "2026-08-26")
    assert len(out) == 1


def test_filter_by_datetime_empty_no_columns():
    """源故障时可能返回无列空表 → 返回空表而不是 KeyError。"""
    out = filter_by_datetime(pd.DataFrame(), "2026-01-01", "2026-12-31")
    assert isinstance(out, pd.DataFrame)
    assert out.empty


def test_filter_by_date_empty_no_columns():
    """hk/us 日线源故障时可能返回无列空表 → 返回空表而不是 KeyError。"""
    out = filter_by_date(pd.DataFrame(), "2026-01-01", "2026-12-31")
    assert isinstance(out, pd.DataFrame)
    assert out.empty


def test_guard_minute_depth_ok_when_start_within_coverage():
    df = pd.DataFrame({"datetime": ["2026-08-25 09:31:00", "2026-08-27 15:00:00"]})
    guard_minute_depth(df, "2026-08-25", source="腾讯")  # 不抛即通过


def test_guard_minute_depth_raises_with_guidance_when_beyond():
    """请求起点早于数据实际覆盖 → 报错文案含覆盖区间与补数指引。"""
    df = pd.DataFrame({"datetime": ["2026-08-25 09:31:00", "2026-08-27 15:00:00"]})
    with pytest.raises(ValueError, match="分钟数据仅覆盖 2026-08-25 至 2026-08-27.*补数"):
        guard_minute_depth(df, "2026-08-01", source="新浪")


def test_coverage_error_is_precisely_catchable():
    """独立异常类型供消费方精确捕获(quant-chart 契约 §4),同时兼容 except ValueError。"""
    from local_datasource.providers.common import CoverageError
    assert issubclass(CoverageError, ValueError)
    df = pd.DataFrame({"datetime": ["2026-08-25 09:31:00"]})
    with pytest.raises(CoverageError, match=r"2026-08-25.*补数"):
        guard_minute_depth(df, "2026-08-01")


def test_guard_minute_depth_empty_df_noop():
    """空表不在这里报错,交给上层统一 No data。"""
    guard_minute_depth(pd.DataFrame(columns=["datetime"]), "2026-01-01")


def test_to_compact_date():
    assert to_compact_date("2026-08-28") == "20260828"
    assert len(to_compact_date(None)) == 8  # 默认今天 YYYYMMDD


def test_fetch_tencent_minute_renames_and_filters(monkeypatch, tmp_path):
    """腾讯分钟通用路径:day 列归一为 datetime,按区间过滤。"""
    from local_datasource.providers import common

    fake = pd.DataFrame({
        "day": ["2026-08-25 09:31:00", "2026-08-26 09:31:00"],
        "open": [1.0, 1.1], "close": [1.0, 1.1],
    })
    monkeypatch.setattr(common.ak, "stock_zh_a_minute", lambda symbol, period, adjust: fake.copy())
    out = fetch_tencent_minute("sh600519", freq="1", start_date="2026-08-26", end_date="2026-08-26")
    assert len(out) == 1
    assert "datetime" in out.columns


def test_fetch_tencent_minute_empty_after_filter_raises(monkeypatch):
    from local_datasource.providers import common

    fake = pd.DataFrame({
        "day": ["2026-08-25 09:31:00"],
        "open": [1.0], "close": [1.0],
    })
    monkeypatch.setattr(common.ak, "stock_zh_a_minute", lambda symbol, period, adjust: fake.copy())
    with pytest.raises(ValueError, match="No minute data"):
        fetch_tencent_minute("sh600519", freq="1", start_date="2026-08-26", end_date="2026-08-26")