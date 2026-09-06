# tests/test_align.py
"""align_series 单测(全离线,tmp_path 构造输入 CSV,零网络、零 mock)。

契约要点:
- outer 并集(NaN 位置可断言)/ inner 交集(无交集报错并含日期范围提示)
- fill=ffill 前向填充,序列开头无前值处保持 NaN
- resample week(W-FRI)/month:每期取最后一行,输出日期为该期最后一个
  实际交易日(而非合成的期末周五/月末)
- columns/names 定制;缺列/无日期首列/单文件/非法参数 → ValueError
- 重复日期保留最后一次出现
"""
from __future__ import annotations

import pandas as pd
import pytest

from local_datasource.providers.align import align_series


def _write_csv(path, dates: list[str], values: list[float], column: str = "close") -> str:
    pd.DataFrame({"date": dates, column: values}).to_csv(path, index=False)
    return str(path)


def _read_out(path: str) -> pd.DataFrame:
    return pd.read_csv(path, dtype={"date": str})


# ---------- outer / inner ----------

def test_align_outer_two_files(tmp_path):
    """不同交易日历的两份 close CSV:并集行数 + NaN 位置。"""
    a = _write_csv(tmp_path / "a.csv", ["2026-01-05", "2026-01-06", "2026-01-07"], [1.0, 2.0, 3.0])
    b = _write_csv(tmp_path / "b.csv", ["2026-01-06", "2026-01-07", "2026-01-08"], [10.0, 20.0, 30.0])
    out = str(tmp_path / "out.csv")

    _, summary = align_series(file_paths=[a, b], file_path=out)

    df = _read_out(out)
    assert list(df.columns) == ["date", "a", "b"]  # 默认 names = 文件名 stem
    assert len(df) == 4  # 并集 01-05..01-08
    assert df["date"].tolist() == ["2026-01-05", "2026-01-06", "2026-01-07", "2026-01-08"]
    assert df["a"].isna().tolist() == [False, False, False, True]   # A 缺 01-08
    assert df["b"].isna().tolist() == [True, False, False, False]   # B 缺 01-05
    assert df["a"].dropna().tolist() == [1.0, 2.0, 3.0]
    assert df["b"].dropna().tolist() == [10.0, 20.0, 30.0]
    assert "Rows: 4" in summary


def test_align_inner(tmp_path):
    a = _write_csv(tmp_path / "a.csv", ["2026-01-05", "2026-01-06", "2026-01-07"], [1.0, 2.0, 3.0])
    b = _write_csv(tmp_path / "b.csv", ["2026-01-06", "2026-01-07", "2026-01-08"], [10.0, 20.0, 30.0])
    out = str(tmp_path / "out.csv")

    align_series(file_paths=[a, b], file_path=out, align="inner")

    df = _read_out(out)
    assert len(df) == 2  # 交集 01-06/01-07
    assert df["date"].tolist() == ["2026-01-06", "2026-01-07"]
    assert df["a"].tolist() == [2.0, 3.0]
    assert df["b"].tolist() == [10.0, 20.0]
    assert not df.isna().any().any()


def test_inner_no_overlap_raises(tmp_path):
    a = _write_csv(tmp_path / "a.csv", ["2026-01-05", "2026-01-06"], [1.0, 2.0])
    b = _write_csv(tmp_path / "b.csv", ["2026-02-02", "2026-02-03"], [9.0, 8.0])
    with pytest.raises(ValueError, match="无交集"):
        align_series(file_paths=[a, b], file_path=str(tmp_path / "out.csv"), align="inner")


# ---------- ffill ----------

def test_fill_ffill(tmp_path):
    """前向填充生效;序列开头无前值处保持 NaN。"""
    a = _write_csv(tmp_path / "a.csv", ["2026-01-05", "2026-01-06", "2026-01-07"], [1.0, 2.0, 3.0])
    b = _write_csv(tmp_path / "b.csv", ["2026-01-06", "2026-01-07"], [20.0, 30.0])
    out = str(tmp_path / "out.csv")

    align_series(file_paths=[a, b], file_path=out, fill="ffill")

    df = _read_out(out)
    assert len(df) == 3
    assert df["b"].isna().tolist() == [True, False, False]  # 开头无前值,保持 NaN
    assert df["b"].dropna().tolist() == [20.0, 30.0]


# ---------- resample ----------

def test_resample_week_takes_period_end(tmp_path):
    """每周一行且取该周最后交易日的行;最后一周仅周二 → 日期是 01-20 而非合成周五 01-23。"""
    # 01-05(周一) 01-07(周三) 01-09(周五) | 01-13(周二) 01-16(周五) | 01-20(周二)
    a = _write_csv(
        tmp_path / "a.csv",
        ["2026-01-05", "2026-01-07", "2026-01-09", "2026-01-13", "2026-01-16", "2026-01-20"],
        [1.0, 2.0, 3.0, 4.0, 5.0, 6.0],
    )
    b = _write_csv(
        tmp_path / "b.csv",
        ["2026-01-07", "2026-01-09", "2026-01-16", "2026-01-20"],
        [10.0, 11.0, 12.0, 13.0],
    )
    out = str(tmp_path / "out.csv")

    align_series(file_paths=[a, b], file_path=out, resample="week")

    df = _read_out(out)
    assert len(df) == 3  # 三周各一行
    assert df["date"].tolist() == ["2026-01-09", "2026-01-16", "2026-01-20"]  # 实际交易日
    assert df["a"].tolist() == [3.0, 5.0, 6.0]  # 每期最后一行的值
    assert df["b"].isna().tolist() == [False, False, False]
    assert df["b"].tolist() == [11.0, 12.0, 13.0]


def test_resample_month(tmp_path):
    """每月一行取期末交易日;3 月只到 03-15 → 日期是 03-15 而非合成 03-31。"""
    a = _write_csv(
        tmp_path / "a.csv",
        ["2026-01-05", "2026-01-30", "2026-02-03", "2026-02-27", "2026-03-02", "2026-03-15"],
        [1.0, 2.0, 3.0, 4.0, 5.0, 6.0],
    )
    b = _write_csv(tmp_path / "b.csv", ["2026-01-30", "2026-02-27", "2026-03-15"], [20.0, 21.0, 22.0])
    out = str(tmp_path / "out.csv")

    align_series(file_paths=[a, b], file_path=out, resample="month")

    df = _read_out(out)
    assert len(df) == 3  # 三个月各一行
    assert df["date"].tolist() == ["2026-01-30", "2026-02-27", "2026-03-15"]
    assert df["a"].tolist() == [2.0, 4.0, 6.0]
    assert df["b"].tolist() == [20.0, 21.0, 22.0]


# ---------- columns / names ----------

def test_custom_columns_and_names(tmp_path):
    a = _write_csv(tmp_path / "a.csv", ["2026-01-05", "2026-01-06"], [1.0, 2.0], column="open")
    b = _write_csv(tmp_path / "b.csv", ["2026-01-05", "2026-01-06"], [10.0, 20.0], column="low")
    out = str(tmp_path / "out.csv")

    align_series(file_paths=[a, b], file_path=out, columns=["open", "low"], names=["x", "y"])

    df = _read_out(out)
    assert list(df.columns) == ["date", "x", "y"]
    assert df["x"].tolist() == [1.0, 2.0]
    assert df["y"].tolist() == [10.0, 20.0]


# ---------- 校验与报错 ----------

def test_missing_column_raises(tmp_path):
    a = _write_csv(tmp_path / "a.csv", ["2026-01-05"], [1.0])
    b = _write_csv(tmp_path / "b.csv", ["2026-01-05"], [2.0])
    with pytest.raises(ValueError, match=r"b\.csv.*nope"):
        align_series(file_paths=[a, b], file_path=str(tmp_path / "out.csv"), columns=["close", "nope"])
    # 默认各取 close:文件没有 close 列时报错且指明文件
    no_close = tmp_path / "c.csv"
    pd.DataFrame({"date": ["2026-01-05"], "price": [1.0]}).to_csv(no_close, index=False)
    with pytest.raises(ValueError, match=r"c\.csv.*close"):
        align_series(file_paths=[a, str(no_close)], file_path=str(tmp_path / "out.csv"))


def test_file_without_date_column_raises(tmp_path):
    bad1 = tmp_path / "bad1.csv"
    bad2 = tmp_path / "bad2.csv"
    pd.DataFrame({"timestamp": ["2026-01-05"], "close": [1.0]}).to_csv(bad1, index=False)
    pd.DataFrame({"timestamp": ["2026-01-05"], "close": [2.0]}).to_csv(bad2, index=False)
    with pytest.raises(ValueError, match="日期列"):
        align_series(
            file_paths=[str(bad1), str(bad2)],
            file_path=str(tmp_path / "out.csv"),
        )


def test_single_file_raises(tmp_path):
    a = _write_csv(tmp_path / "a.csv", ["2026-01-05"], [1.0])
    with pytest.raises(ValueError, match="至少需要 2 个输入文件"):
        align_series(file_paths=[a], file_path=str(tmp_path / "out.csv"))


def test_invalid_params_raise(tmp_path):
    a = _write_csv(tmp_path / "a.csv", ["2026-01-05"], [1.0])
    b = _write_csv(tmp_path / "b.csv", ["2026-01-05"], [2.0])
    with pytest.raises(ValueError, match="align"):
        align_series(file_paths=[a, b], file_path=str(tmp_path / "o.csv"), align="left")
    with pytest.raises(ValueError, match="fill"):
        align_series(file_paths=[a, b], file_path=str(tmp_path / "o.csv"), fill="bfill")
    with pytest.raises(ValueError, match="resample"):
        align_series(file_paths=[a, b], file_path=str(tmp_path / "o.csv"), resample="day")
    with pytest.raises(ValueError, match="columns"):
        align_series(file_paths=[a, b], file_path=str(tmp_path / "o.csv"), columns=["close"])
    with pytest.raises(ValueError, match="names"):
        align_series(file_paths=[a, b], file_path=str(tmp_path / "o.csv"), names=["only_one"])
    with pytest.raises(ValueError, match="重复"):
        align_series(file_paths=[a, b], file_path=str(tmp_path / "o.csv"), names=["dup", "dup"])
    with pytest.raises(ValueError, match="不存在"):
        align_series(file_paths=[a, tmp_path / "missing.csv"], file_path=str(tmp_path / "o.csv"))


def test_reserved_date_name_raises(tmp_path):
    """输出列名 'date' 与日期列冲突(直接合并会触发 pandas 的隐晦报错)→ 提前报可读错误。"""
    a = _write_csv(tmp_path / "a.csv", ["2026-01-05"], [1.0])
    b = _write_csv(tmp_path / "b.csv", ["2026-01-05"], [2.0])
    with pytest.raises(ValueError, match="保留为日期列"):
        align_series(file_paths=[a, b], file_path=str(tmp_path / "o.csv"), names=["date", "b"])


def test_duplicate_stem_names_raise(tmp_path):
    """默认 names = 文件名 stem:两个不同目录同名文件 → 输出列名冲突,报错提示用 names。"""
    d1 = tmp_path / "x"
    d2 = tmp_path / "y"
    d1.mkdir()
    d2.mkdir()
    a = _write_csv(d1 / "same.csv", ["2026-01-05"], [1.0])
    b = _write_csv(d2 / "same.csv", ["2026-01-05"], [2.0])
    with pytest.raises(ValueError, match="重复"):
        align_series(file_paths=[a, b], file_path=str(tmp_path / "out.csv"))


def test_duplicate_dates_keep_last(tmp_path):
    path = tmp_path / "dup.csv"
    pd.DataFrame({
        "date": ["2026-01-05", "2026-01-06", "2026-01-06"],
        "close": [1.0, 2.0, 99.0],
    }).to_csv(path, index=False)
    b = _write_csv(tmp_path / "b.csv", ["2026-01-05", "2026-01-06"], [10.0, 20.0])

    align_series(file_paths=[str(path), b], file_path=str(tmp_path / "out.csv"))

    df = _read_out(tmp_path / "out.csv")
    assert len(df) == 2
    assert df.iloc[1]["dup"] == 99.0  # 重复日期保留最后一次出现
