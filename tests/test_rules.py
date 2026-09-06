# tests/test_rules.py
"""query_trading_rules 离线单测(Task 11):表内容即数据,无网络调用。

契约要点:
- 判定 effective_from <= as_of < effective_to(null=至今);as_of 缺省取今天(rules._today 可 monkeypatch)
- market 8 值枚举,非法值 ValueError;commodity_futures 返回引导行而非报错
- parameter 过滤为 parameter 列的不区分大小写子串
- 表内同时存在 official/media/to_verify/market_estimate 四档置信度(标注体系完整)
"""
from importlib import resources

import pandas as pd
import pytest
import yaml

from local_datasource.providers import rules
from local_datasource.providers.rules import query_trading_rules


def _query(tmp_path, **kwargs) -> tuple[pd.DataFrame, str]:
    """调用 provider 并读回 CSV(模拟真实消费路径),返回 (df, summary)。"""
    out = tmp_path / "rules.csv"
    _, summary = query_trading_rules(file_path=str(out), **kwargs)
    df = pd.read_csv(out, encoding="utf-8-sig")
    return df, summary


# ---------- 生效区间边界 ----------

def test_as_of_boundary(tmp_path):
    """印花税 2023-08-28 边界:生效日当天取新值(0.5‰),前一天取旧值(1‰)。"""
    df_new, _ = _query(tmp_path, market="a", parameter="印花税", as_of="2023-08-28")
    assert len(df_new) == 1
    assert float(df_new.loc[0, "value"]) == pytest.approx(0.0005)

    df_old, _ = _query(tmp_path, market="a", parameter="印花税", as_of="2023-08-27")
    assert len(df_old) == 1
    assert float(df_old.loc[0, "value"]) == pytest.approx(0.001)


def test_stamp_duty_2021_single_side_1bp(tmp_path):
    """2021-06-01 处于 2008-09-19 起"仅卖出方 1‰"档:值 0.001 且表明仅卖出方。"""
    df, _ = _query(tmp_path, market="a", parameter="印花税", as_of="2021-06-01")
    assert len(df) == 1
    assert float(df.loc[0, "value"]) == pytest.approx(0.001)
    assert "卖出" in str(df.loc[0, "basis"]), f"basis 应表明仅卖出方: {df.loc[0, 'basis']}"


def test_stamp_duty_2024_half(tmp_path):
    df, _ = _query(tmp_path, market="a", parameter="印花税", as_of="2024-01-01")
    assert len(df) == 1
    assert float(df.loc[0, "value"]) == pytest.approx(0.0005)


def test_st_limit_change_2026_07(tmp_path):
    """主板 ST 参数:2026-07-05 为 5%、2026-07-06 为 10%(附录 B2 近期变更)。"""
    df5, _ = _query(tmp_path, market="a", parameter="涨跌幅", as_of="2026-07-05")
    st5 = df5[df5["scope"].str.contains("ST", case=False, na=False)]
    assert len(st5) == 1
    assert float(st5.iloc[0]["value"]) == pytest.approx(0.05)

    df6, _ = _query(tmp_path, market="a", parameter="涨跌幅", as_of="2026-07-06")
    st6 = df6[df6["scope"].str.contains("ST", case=False, na=False)]
    assert len(st6) == 1
    assert float(st6.iloc[0]["value"]) == pytest.approx(0.10)


def test_margin_ratio_2026_01(tmp_path):
    """融资保证金:2026-01-18 为 80%、2026-01-19 回 100%(附录 B6 近期变更)。"""
    df18, _ = _query(tmp_path, market="margin", parameter="融资保证金", as_of="2026-01-18")
    assert len(df18) == 1
    assert float(df18.loc[0, "value"]) == pytest.approx(0.8)

    df19, _ = _query(tmp_path, market="margin", parameter="融资保证金", as_of="2026-01-19")
    assert len(df19) == 1
    assert float(df19.loc[0, "value"]) == pytest.approx(1.0)


# ---------- as_of 缺省与过滤 ----------

def test_default_as_of_is_today(tmp_path, monkeypatch):
    """缺省 as_of 取今天(monkeypatch rules._today 钉死日期),并断言取到现行新值。"""
    monkeypatch.setattr(rules, "_today", lambda: "2026-09-06")
    df, _ = _query(tmp_path, market="a", parameter="印花税")
    assert len(df) == 1
    assert float(df.loc[0, "value"]) == pytest.approx(0.0005), "现行印花税应为 2023-08-28 起 0.5‰ 新值"

    df_st, _ = _query(tmp_path, market="a", parameter="涨跌幅")
    st = df_st[df_st["scope"].str.contains("ST", case=False, na=False)]
    assert float(st.iloc[0]["value"]) == pytest.approx(0.10), "现行主板 ST 应为 2026-07-06 起 ±10% 新值"


def test_parameter_filter(tmp_path):
    """parameter 过滤:parameter 列子串命中,不混入其它参数。"""
    df, _ = _query(tmp_path, market="a", parameter="过户费", as_of="2024-06-01")
    assert not df.empty
    assert df["parameter"].str.contains("过户费", regex=False).all()
    assert not df["parameter"].str.contains("印花税", regex=False).any()
    # 大小写不敏感(拉丁字符场景,如 T+0/T+1)
    df_t, _ = _query(tmp_path, market="a", parameter="t+0", as_of="1993-06-01")
    assert df_t["parameter"].str.contains("T+0", regex=False).all()


# ---------- commodity_futures 引导行与参数校验 ----------

def test_commodity_futures_returns_guidance_not_error(tmp_path):
    """commodity_futures 返回引导行(单行、12 列、含"结算参数"指引),不报错。"""
    df, summary = _query(tmp_path, market="commodity_futures")
    assert len(df) == 1
    assert list(df.columns) == rules.RULE_COLUMNS
    note = str(df.loc[0, "note"])
    assert "结算参数" in note
    assert "结算参数" in summary


def test_market_enum_rejected(tmp_path):
    with pytest.raises(ValueError, match="market"):
        query_trading_rules(market="us", file_path=str(tmp_path / "x.csv"))
    # 合法市场 + 非法 as_of 格式同样报可读错误
    with pytest.raises(ValueError, match="as_of"):
        query_trading_rules(market="a", file_path=str(tmp_path / "x.csv"), as_of="20230828")
    with pytest.raises(ValueError, match="as_of"):
        query_trading_rules(market="a", file_path=str(tmp_path / "x.csv"), as_of="2023-8-28")


def test_empty_selection_readable_error(tmp_path):
    """as_of 早于所有生效记录时报可读错误(不静默返回空表)。"""
    with pytest.raises(ValueError, match="无生效的规则参数"):
        query_trading_rules(market="margin", file_path=str(tmp_path / "x.csv"), as_of="2009-01-01")


# ---------- 表质量(直接读 YAML,标注体系完整) ----------

def test_all_confidence_levels_present():
    """表内同时存在 official/media/to_verify/market_estimate 四档,且 12 字段齐全、区间合法。"""
    text = (
        resources.files("local_datasource")
        .joinpath("assets/trading_rules.yaml")
        .read_text(encoding="utf-8")
    )
    rows = yaml.safe_load(text)["rules"]
    levels = {r["confidence"] for r in rows}
    assert {"official", "media", "to_verify", "market_estimate"} <= levels, levels
    for i, r in enumerate(rows):
        assert set(r.keys()) == set(rules.RULE_COLUMNS), f"第 {i} 行字段不齐: {sorted(r.keys())}"
        assert r["effective_from"] < (r["effective_to"] or "9999-12-31"), f"第 {i} 行区间非法"
    # 8 个 market 枚举中 7 个入表(commodity_futures 由 provider 构造引导行,不入 YAML)
    assert {"a", "etf", "cffex", "treasury_futures", "margin", "option", "hk_connect"} == {
        r["market"] for r in rows
    }
