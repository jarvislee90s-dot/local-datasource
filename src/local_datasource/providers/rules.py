"""rules provider:交易规则参数静态表查询(纯本地,不联网)。

数据源为包内资产 ``assets/trading_rules.yaml``(随 wheel 分发,经
``importlib.resources`` 读取,不依赖工作目录)。每行为一条带生效区间的规则参数,
12 字段:market/parameter/scope/value/unit/basis/effective_from/effective_to/
source/last_verified/confidence/note。

- 判定口径:``effective_from <= as_of < effective_to``(``effective_to`` 为
  null 表示至今);``as_of`` 缺省取今天(经模块级 ``_today`` 便于测试)。
- ``parameter`` 过滤:对 parameter 列做不区分大小写的子串匹配(不匹配 scope 列)。
- ``market=commodity_futures``:商品期货合约级参数按"品种×合约×时段"频繁变动,
  不入静态表;返回一行引导(建议查交易所当日结算参数),不是报错。
- 无命中时报可读错误(不静默返回空表)。
"""
from __future__ import annotations

import re
from datetime import datetime
from importlib import resources
from typing import Literal

import pandas as pd
import yaml

from local_datasource.formatters import format_csv_output


MarketKind = Literal[
    "a", "etf", "cffex", "treasury_futures", "margin", "option", "hk_connect",
    "commodity_futures",
]

VALID_MARKETS: tuple[str, ...] = (
    "a", "etf", "cffex", "treasury_futures", "margin", "option", "hk_connect",
    "commodity_futures",
)

VALID_CONFIDENCE: tuple[str, ...] = ("official", "media", "to_verify", "market_estimate")

# 表内 12 字段(顺序即输出列顺序)
RULE_COLUMNS: list[str] = [
    "market", "parameter", "scope", "value", "unit", "basis",
    "effective_from", "effective_to", "source", "last_verified", "confidence",
    "note",
]

_DATE_RE = re.compile(r"\d{4}-\d{2}-\d{2}")
_INFINITE_END = "9999-12-31"


def _today() -> str:
    """当前日期(YYYY-MM-DD)。独立模块级函数,便于测试 monkeypatch。"""
    return datetime.now().strftime("%Y-%m-%d")


def _load_rules() -> list[dict]:
    """读取包内 YAML(importlib.resources,不依赖工作目录),并做行级结构守卫。"""
    text = (
        resources.files("local_datasource")
        .joinpath("assets/trading_rules.yaml")
        .read_text(encoding="utf-8")
    )
    data = yaml.safe_load(text)
    rules = data.get("rules") if isinstance(data, dict) else None
    if not isinstance(rules, list) or not rules:
        raise ValueError("包内资产 assets/trading_rules.yaml 缺少 rules 列表(资产损坏)")
    for i, row in enumerate(rules):
        missing = [c for c in RULE_COLUMNS if c not in row]
        if missing:
            raise ValueError(f"trading_rules.yaml 第 {i} 行缺字段 {missing}(资产损坏)")
        if row["market"] not in VALID_MARKETS:
            raise ValueError(f"trading_rules.yaml 第 {i} 行 market 非法: {row['market']!r}")
        if row["confidence"] not in VALID_CONFIDENCE:
            raise ValueError(f"trading_rules.yaml 第 {i} 行 confidence 非法: {row['confidence']!r}")
        if not isinstance(row["effective_from"], str) or not _DATE_RE.fullmatch(row["effective_from"]):
            raise ValueError(f"trading_rules.yaml 第 {i} 行 effective_from 须为 YYYY-MM-DD: {row['effective_from']!r}")
        if row["effective_to"] is not None and (
            not isinstance(row["effective_to"], str) or not _DATE_RE.fullmatch(row["effective_to"])
        ):
            raise ValueError(f"trading_rules.yaml 第 {i} 行 effective_to 须为 YYYY-MM-DD 或 null: {row['effective_to']!r}")
    return rules


def _validate_as_of(as_of: str) -> str:
    """严格校验 as_of 为 YYYY-MM-DD(拒绝 2023/8/28 等非零填充写法)。"""
    if not isinstance(as_of, str) or not _DATE_RE.fullmatch(as_of):
        raise ValueError(f"as_of 须为 YYYY-MM-DD 格式字符串,收到 {as_of!r}")
    try:
        datetime.strptime(as_of, "%Y-%m-%d")
    except ValueError as e:
        raise ValueError(f"as_of 不是有效日期: {as_of!r}({e})") from e
    return as_of


def _guidance_row(as_of: str) -> dict:
    """commodity_futures 引导行:品种×合约×时段三维频繁变动,不入静态表。"""
    return {
        "market": "commodity_futures",
        "parameter": "合约级手续费/保证金(不入静态表)",
        "scope": "上期所/大商所/郑商所/广期所/上期能源",
        "value": "请查交易所当日结算参数",
        "unit": "引导",
        "basis": "品种×合约月份×时段三维频繁变动",
        "effective_from": as_of,
        "effective_to": None,
        "source": "各交易所每日结算参数页(附录B B4 结论)",
        "last_verified": as_of,
        "confidence": "official",
        "note": (
            "商品期货手续费/保证金/平今费/涨跌停按品种×合约×时段不定期调整,同一品种一年可调多次"
            "(例:螺纹钢2016-03-15恢复平今费、2024-05-29起RB非1/5/10月合约差异化费率),静态历史表必然过时"
            "——故不入表;请查上期所/大商所/郑商所/广期所/能源中心当日结算参数,或仅对重点品种人工整理关键区间"
        ),
    }


def query_trading_rules(
    market: MarketKind,
    file_path: str,
    as_of: str | None = None,
    parameter: str | None = None,
) -> tuple[str, str]:
    """查询 ``as_of`` 当日生效的交易规则参数(税费/涨跌幅/T+1/保证金等),输出 12 字段 CSV。

    纯本地计算,不联网;数据为包内静态表,随版本更新。

    参数:
        market: 市场枚举(a/etf/cffex/treasury_futures/margin/option/hk_connect/
            commodity_futures);commodity_futures 返回引导行(不入静态表)
        file_path: 输出 CSV 路径
        as_of: 判定日期 YYYY-MM-DD,命中 ``effective_from <= as_of < effective_to``;
            缺省取今天("按现行规则"不传,"按历史真实规则"传历史日期)
        parameter: 可选过滤,对 parameter 列做不区分大小写的子串匹配
            (仅匹配 parameter 列,不匹配 scope;如 印花税/涨跌幅/融资保证金)

    返回:
        (file_path, 包含行数、列数和预览的文本摘要)
    """
    if market not in VALID_MARKETS:
        raise ValueError(f"market 须为 {', '.join(VALID_MARKETS)} 之一,收到 {market!r}")
    as_of = _validate_as_of(as_of) if as_of is not None else _today()

    if market == "commodity_futures":
        # 引导行不参与 parameter 过滤,保证无论过滤词如何都给出指引
        df = pd.DataFrame([_guidance_row(as_of)], columns=RULE_COLUMNS)
        return format_csv_output(df, file_path)

    df = pd.DataFrame(_load_rules(), columns=RULE_COLUMNS)
    df = df[df["market"] == market]

    # 生效区间判定:effective_from <= as_of < effective_to(null = 至今)
    end = df["effective_to"].fillna(_INFINITE_END)
    df = df[(df["effective_from"] <= as_of) & (as_of < end)]

    if parameter:
        needle = str(parameter).lower()
        df = df[df["parameter"].str.lower().str.contains(needle, regex=False, na=False)]

    if df.empty:
        hint = f"parameter 过滤({parameter!r})无命中" if parameter else "该日期无生效记录"
        earliest = min(
            (r["effective_from"] for r in _load_rules() if r["market"] == market),
            default=None,
        )
        earliest_text = f"该市场表内最早生效日为 {earliest}" if earliest else "该市场表内无记录"
        raise ValueError(
            f"market={market} 在 as_of={as_of} 无生效的规则参数({hint});"
            f"{earliest_text},可去掉 parameter 过滤或调整 as_of"
        )

    df = df.sort_values(["parameter", "effective_from"], kind="stable").reset_index(drop=True)
    return format_csv_output(df, file_path)
