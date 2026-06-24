"""世界银行宏观经济数据 provider。

通过 wbgapi 按指标代码、国家代码和年份范围查询数据。
"""
from __future__ import annotations

import wbgapi as wb

from local_datasource.formatters import format_csv_output


def query_worldbank(
    indicator: str,
    country: str,
    start_year: int,
    end_year: int,
    file_path: str,
) -> tuple[str, str]:
    """查询世界银行指标并输出 CSV。

    参数:
        indicator: 指标代码，例如 ``NY.GDP.MKTP.CD``
        country: 国家代码，支持逗号分隔或 ``all``
        start_year: 起始年份
        end_year: 结束年份
        file_path: 输出 CSV 路径
    """
    if end_year < start_year:
        raise ValueError("end_year must be >= start_year")

    country_list = [c.strip().upper() for c in country.split(",")]
    if country_list == ["ALL"]:
        country_list = "all"

    df = wb.data.DataFrame(indicator, country_list, time=range(start_year, end_year + 1))
    df = df.reset_index()

    if df.empty:
        raise ValueError(f"No World Bank data for indicator {indicator}")

    return format_csv_output(df, file_path)
