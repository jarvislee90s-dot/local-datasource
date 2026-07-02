# tests/test_convertible_bond.py
import os
import tempfile

import pytest

from local_datasource.providers.convertible_bond import query_convertible_bond


def test_normalize_cb_code_native():
    from local_datasource.providers import convertible_bond as cb
    assert cb._normalize_cb_code("sz128039") == "sz128039"


def test_normalize_cb_code_plain_digits_sz():
    from local_datasource.providers import convertible_bond as cb
    assert cb._normalize_cb_code("128039") == "sz128039"


def test_normalize_cb_code_plain_digits_sh():
    from local_datasource.providers import convertible_bond as cb
    assert cb._normalize_cb_code("113682") == "sh113682"


def test_normalize_cb_code_suffix():
    from local_datasource.providers import convertible_bond as cb
    assert cb._normalize_cb_code("113682.SH") == "sh113682"


def test_normalize_cb_code_invalid():
    from local_datasource.providers import convertible_bond as cb
    with pytest.raises(ValueError):
        cb._normalize_cb_code("abc!@#")


@pytest.mark.skipif(os.environ.get("SKIP_INTEGRATION"), reason="integration")
def test_query_cb_overview():
    """可转债一览:返回全市场转债,含转股溢价率等字段,行数>0。"""
    with tempfile.NamedTemporaryFile(suffix=".csv", delete=False) as f:
        path = f.name
    try:
        file_path, summary = query_convertible_bond(kind="overview", file_path=path)
        assert os.path.exists(file_path)
        assert "Rows:" in summary
    finally:
        os.unlink(path)


@pytest.mark.skipif(os.environ.get("SKIP_INTEGRATION"), reason="integration")
def test_query_cb_overview_keyword_regex_meta_not_error():
    """含正则元字符的关键字应走字面匹配(ValueError 可,但不抛 re.error)。"""
    import re as _re
    with tempfile.NamedTemporaryFile(suffix=".csv", delete=False) as f:
        path = f.name
    try:
        try:
            query_convertible_bond(kind="overview", keyword="银行+", file_path=path)
            keyword_ok = True
        except ValueError:
            # 无匹配是合法结果,只要不是 re.error 即可
            keyword_ok = True
        except _re.error:
            keyword_ok = False
        assert keyword_ok, "含正则元字符的关键字不应触发 re.error"
    finally:
        os.unlink(path)


@pytest.mark.skipif(os.environ.get("SKIP_INTEGRATION"), reason="integration")
def test_query_cb_terms():
    """可转债条款:集思录强赎+剩余期限/到期税前收益,行数>0。"""
    with tempfile.NamedTemporaryFile(suffix=".csv", delete=False) as f:
        path = f.name
    try:
        file_path, summary = query_convertible_bond(kind="terms", file_path=path)
        assert os.path.exists(file_path)
        assert "Rows:" in summary
        assert "Rows: 0" not in summary
    finally:
        os.unlink(path)


@pytest.mark.skipif(os.environ.get("SKIP_INTEGRATION"), reason="integration")
def test_query_cb_history_daily():
    """可转债历史日K:sz128039 返回开高低收量。"""
    with tempfile.NamedTemporaryFile(suffix=".csv", delete=False) as f:
        path = f.name
    try:
        file_path, summary = query_convertible_bond(
            kind="history", symbol="sz128039",
            start_date="2024-01-01", end_date="2024-06-30",
            period="daily", file_path=path)
        assert os.path.exists(file_path)
        assert "Rows:" in summary
        assert "Rows: 0" not in summary
    finally:
        os.unlink(path)


def test_query_cb_history_requires_symbol():
    from local_datasource.providers import convertible_bond as cb
    with pytest.raises(ValueError, match="history requires"):
        cb.query_convertible_bond(kind="history", start_date="2024-01-01", end_date="2024-06-30", file_path="/tmp/x.csv")


@pytest.mark.skipif(os.environ.get("SKIP_INTEGRATION"), reason="integration")
def test_query_cb_issuer_finance_via_stock_code():
    """通过正股代码取发行人财务:603938(益丰药房)返回三大报表。"""
    with tempfile.NamedTemporaryFile(suffix=".csv", delete=False) as f:
        path = f.name
    try:
        file_path, summary = query_convertible_bond(
            kind="issuer_finance", stock_code="sh603938",
            report_type="资产负债表", file_path=path)
        assert os.path.exists(file_path)
        assert "Rows:" in summary
    finally:
        os.unlink(path)


def test_query_cb_issuer_finance_requires_code():
    from local_datasource.providers import convertible_bond as cb
    with pytest.raises(ValueError, match="issuer_finance requires"):
        cb.query_convertible_bond(kind="issuer_finance", file_path="/tmp/x.csv")


def test_query_cb_issuer_finance_nonlisted_returns_hint():
    """非上市发行人(城投)解析正股失败时返回引导性提示 CSV,不报错。

    纯函数测试:直接测 _build_nonlisted_hint 输出格式。
    """
    from local_datasource.providers import convertible_bond as cb
    hint_df = cb._build_nonlisted_hint("某城投平台")
    assert len(hint_df) == 1
    assert "非上市" in str(hint_df.iloc[0].values) or "Wind" in str(hint_df.iloc[0].values)


def test_query_cb_issuer_finance_non_cb_bond_code_returns_hint():
    """企业债/银行间债 code(非转债)走 issuer_finance 不应崩溃,返回非上市提示。

    回归 case:2180495.IB 是企业债(城投),不是转债,_normalize_cb_code 会抛
    ValueError;_resolve_stock_code_from_cb 应兜住,返回非上市提示而非上抛异常。
    """
    from local_datasource.providers import convertible_bond as cb
    import pandas as pd
    path = _tmp_csv()
    try:
        file_path, summary = cb.query_convertible_bond(
            kind="issuer_finance", bond_code="2180495.IB",
            report_type="资产负债表", file_path=path)
        df = pd.read_csv(file_path)
        assert len(df) == 1
        assert "非上市" in str(df.iloc[0].values) or "Wind" in str(df.iloc[0].values)
    finally:
        os.unlink(path)


def _tmp_csv():
    import tempfile
    f = tempfile.NamedTemporaryFile(suffix=".csv", delete=False)
    f.close()
    return f.name
