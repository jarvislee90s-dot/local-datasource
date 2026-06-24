"""统一输出格式化模块。

将各个 provider 返回的 DataFrame 写入 CSV 文件，并生成可读的前 N 行预览摘要。
"""
from pathlib import Path

import pandas as pd


def format_csv_output(df: pd.DataFrame, file_path: str, preview_rows: int = 5) -> tuple[str, str]:
    """把 DataFrame 输出为 CSV，并返回文件路径与预览文本。

    参数:
        df: 待写入的数据
        file_path: 目标 CSV 路径
        preview_rows: 预览行数，默认 5 行

    返回:
        (file_path, 包含行数、列数和预览的文本摘要)
    """
    path = Path(file_path)
    # 自动创建目标目录，避免目录不存在导致写入失败
    path.parent.mkdir(parents=True, exist_ok=True)
    # 使用 utf-8-sig 以兼容 Excel 打开中文
    df.to_csv(path, index=False, encoding="utf-8-sig")

    preview_df = df.head(preview_rows)
    preview = preview_df.to_csv(index=False, encoding="utf-8-sig").strip()

    summary = f"CSV written to {file_path}\nRows: {len(df)}, Columns: {len(df.columns)}\nPreview:\n{preview}"
    return file_path, summary
