"""align provider:把本库产出的多份 CSV 按日期对齐合并为一张宽表(纯本地计算,不联网)。

- 日期列:各输入 CSV 的首列须为 ``date``/``datetime``/``日期``(不区分大小写,
  自动兼容 utf-8 BOM 与首尾空白);``datetime`` 含时间部分时截断为日期
- 值列:默认各取 ``close``;用 ``columns`` 逐文件指定(须与 file_paths 等长)
- 重采样(先重采样后合并):``week`` 按 W-FRI(周五为界)、``month`` 按自然月分箱,
  每期保留最后一行——输出日期为该期最后一个实际交易日(而非合成的期末标签),
  值取该行原值,保证回测日期真实可成交
- 合并:``outer`` 并集(缺失处 NaN)/``inner`` 交集(无交集报错并给出各序列日期范围);
  ``fill=ffill`` 对各序列列前向填充(序列开头的 NaN 无前值,保持 NaN)
- 同一文件内重复日期:升序排序后保留最后一次出现(后值覆盖前值,符合日线语义)
"""
from __future__ import annotations

from pathlib import Path
from typing import Literal

import pandas as pd

from local_datasource.formatters import format_csv_output


AlignHow = Literal["outer", "inner"]
FillHow = Literal["none", "ffill"]
ResampleHow = Literal["none", "week", "month"]

# 日期列的合法列名(对首列做 strip + 去 BOM + 小写后匹配)
_DATE_COLUMN_CANDIDATES = ("date", "datetime", "日期")

# resample 别名 → pandas period 别名(week 以周五为界,month 为自然月)
_RESAMPLE_RULES = {"week": "W-FRI", "month": "M"}


def _read_input_csv(path: Path) -> pd.DataFrame:
    """读取单份输入 CSV(utf-8-sig 兼容本库输出),空数据行时报可读错误。"""
    if not path.is_file():
        raise ValueError(f"输入文件不存在: {path}")
    df = pd.read_csv(path, encoding="utf-8-sig")
    if df.empty:
        raise ValueError(f"输入文件没有数据行: {path}")
    return df


def _normalize_dates(df: pd.DataFrame, source: str) -> pd.Series:
    """取首列并归一化为 YYYY-MM-DD 字符串(datetime 截断到日期);不合法时报可读错误。"""
    raw_name = str(df.columns[0]).strip().lstrip("\ufeff").lower()
    if raw_name not in _DATE_COLUMN_CANDIDATES:
        raise ValueError(
            f"{source} 缺少日期列(首列须为 date/datetime/日期,实际为 {df.columns[0]!r};"
            f"现有列: {list(df.columns)})"
        )
    name = df.columns[0]
    ts = pd.to_datetime(df[name], errors="coerce")
    bad = ts.isna()
    if bad.any():
        first_bad = df[name][bad].iloc[0]
        raise ValueError(f"{source} 日期列存在无法解析的值: {first_bad!r}")
    return ts.dt.strftime("%Y-%m-%d")


def _load_series(path: Path, column: str, name: str) -> pd.DataFrame:
    """读单份 CSV → (date, name) 两列;排序升序,重复日期保留最后一次出现。"""
    df = _read_input_csv(path)
    source = path.name
    dates = _normalize_dates(df, source)
    if column not in df.columns:
        raise ValueError(f"{source} 缺少列 {column!r}(现有列: {list(df.columns)})")
    series = pd.DataFrame({"date": dates, name: df[column].to_numpy()})
    series = series.sort_values("date", kind="stable").drop_duplicates("date", keep="last")
    return series.reset_index(drop=True)


def _resample_series(series: pd.DataFrame, rule: str) -> pd.DataFrame:
    """按期分箱保留最后一行:输出日期为该期最后一个实际交易日(非合成期末标签)。"""
    period_key = pd.to_datetime(series["date"]).dt.to_period(rule)
    resampled = series.assign(_period=period_key)
    # 已按日期升序,每期保留最后一行即该期最后一个交易日
    resampled = resampled.drop_duplicates("_period", keep="last")
    return resampled.drop(columns="_period").reset_index(drop=True)


def align_series(
    file_paths: list[str],
    file_path: str,
    columns: list[str] | None = None,
    names: list[str] | None = None,
    align: AlignHow = "outer",
    fill: FillHow = "none",
    resample: ResampleHow = "none",
) -> tuple[str, str]:
    """把本库产出的多份 CSV 按日期对齐合并成一张宽表,输出 ``date`` + 各序列列。

    纯本地计算,不联网。先逐文件重采样(可选),再按 ``date`` 做 outer/inner 合并,
    最后可选前向填充。

    参数:
        file_paths: 输入 CSV 路径,≥ 2 份(本库产出的 CSV,首列为日期列)
        file_path: 输出 CSV 路径
        columns: 各文件取的值列,与 file_paths 一一对应;默认各取 ``close``
        names: 输出列名,与 file_paths 一一对应;默认取文件名 stem
        align: ``outer`` 日期并集(缺失处 NaN)/ ``inner`` 日期交集
        fill: ``ffill`` 对各序列列前向填充(序列开头无前值处保持 NaN)
        resample: 逐序列重采样——``week`` 按 W-FRI、``month`` 按自然月;
            每期取最后一行(输出日期 = 该期最后一个实际交易日)

    返回:
        (file_path, 包含行数、列数和预览的文本摘要)
    """
    if len(file_paths) < 2:
        raise ValueError(f"align_series 至少需要 2 个输入文件,收到 {len(file_paths)} 个")
    if columns is not None and len(columns) != len(file_paths):
        raise ValueError(
            f"columns 长度({len(columns)})须与 file_paths 数量({len(file_paths)})一致"
        )
    if names is not None and len(names) != len(file_paths):
        raise ValueError(
            f"names 长度({len(names)})须与 file_paths 数量({len(file_paths)})一致"
        )
    if align not in ("outer", "inner"):
        raise ValueError(f"align 仅支持 outer/inner,收到 {align!r}")
    if fill not in ("none", "ffill"):
        raise ValueError(f"fill 仅支持 none/ffill,收到 {fill!r}")
    if resample not in ("none", "week", "month"):
        raise ValueError(f"resample 仅支持 none/week/month,收到 {resample!r}")

    value_columns = columns if columns is not None else ["close"] * len(file_paths)
    output_names = names if names is not None else [Path(p).stem for p in file_paths]
    if len(set(output_names)) != len(output_names):
        raise ValueError(f"输出列名存在重复(默认取文件名 stem,可用 names 显式指定): {output_names}")

    series_list = [
        _load_series(Path(p), column, name)
        for p, column, name in zip(file_paths, value_columns, output_names)
    ]
    if resample != "none":
        rule = _RESAMPLE_RULES[resample]
        series_list = [_resample_series(s, rule) for s in series_list]

    merged = series_list[0]
    for series in series_list[1:]:
        merged = merged.merge(series, on="date", how=align)

    if merged.empty:
        ranges = ";".join(
            f"{Path(p).name}[{s['date'].iloc[0]}~{s['date'].iloc[-1]}]"
            for p, s in zip(file_paths, series_list)
        )
        raise ValueError(
            f"对齐结果为空(align=inner 且各序列日期无交集)。各序列日期范围: {ranges};"
            f"若交易日历稀疏可改用 align='outer' + fill='ffill'"
        )

    merged = merged.sort_values("date").reset_index(drop=True)
    if fill == "ffill":
        value_cols = [c for c in merged.columns if c != "date"]
        merged[value_cols] = merged[value_cols].ffill()

    return format_csv_output(merged, file_path)
