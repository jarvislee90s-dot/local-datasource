# tests/test_stock.py
import os
import tempfile

import pandas as pd
import pytest

from local_datasource.providers.stock import query_stock


@pytest.mark.skipif(os.environ.get("SKIP_INTEGRATION"), reason="integration")
def test_query_stock_a_share():
    with tempfile.NamedTemporaryFile(suffix=".csv", delete=False) as f:
        path = f.name
    try:
        file_path, preview = query_stock("600519", market="a", start_date="2025-06-01", end_date="2026-06-24", file_path=path)
        assert os.path.exists(file_path)
        assert "Rows:" in preview
    finally:
        os.unlink(path)


def test_query_stock_normalizes_code():
    from local_datasource.providers import stock
    assert stock._normalize_a_code("600519") == "sh600519"
    assert stock._normalize_hk_code("00700") == "00700"
    assert stock._normalize_us_code("AAPL") == "AAPL"


@pytest.mark.skipif(os.environ.get("SKIP_INTEGRATION"), reason="integration")
def test_resolve_stock_code_by_abbreviation():
    """简称反查:茅台 → 候选含 600519。"""
    from local_datasource.providers.stock import resolve_stock_code
    import pandas as pd
    with tempfile.NamedTemporaryFile(suffix=".csv", delete=False) as f:
        path = f.name
    try:
        file_path, summary = resolve_stock_code(keyword="茅台", file_path=path)
        df = pd.read_csv(file_path)
        assert len(df) >= 1
        assert "600519" in df["代码"].astype(str).values
    finally:
        os.unlink(path)


@pytest.mark.skipif(os.environ.get("SKIP_INTEGRATION"), reason="integration")
def test_resolve_stock_code_by_full_name():
    """全称反查:贵州茅台酒股份有限公司 → 命中 600519(从新浪关联字段提取)。"""
    from local_datasource.providers.stock import resolve_stock_code
    import pandas as pd
    with tempfile.NamedTemporaryFile(suffix=".csv", delete=False) as f:
        path = f.name
    try:
        file_path, summary = resolve_stock_code(keyword="贵州茅台酒股份有限公司", file_path=path)
        df = pd.read_csv(file_path)
        # 新浪全称搜索从关联字段提取 sh600519
        assert "600519" in df["代码"].astype(str).values
    finally:
        os.unlink(path)


@pytest.mark.skipif(os.environ.get("SKIP_INTEGRATION"), reason="integration")
def test_resolve_stock_code_non_listed_returns_empty():
    """城投/非上市发行人名称 → 候选为空(非报错)。"""
    from local_datasource.providers.stock import resolve_stock_code
    import pandas as pd
    with tempfile.NamedTemporaryFile(suffix=".csv", delete=False) as f:
        path = f.name
    try:
        file_path, summary = resolve_stock_code(keyword="成都东方广益投资有限公司", file_path=path)
        df = pd.read_csv(file_path)
        # 城投平台未上市,新浪搜不到 → 候选为空(不报错)
        assert len(df) == 0
    finally:
        os.unlink(path)


def test_resolve_stock_code_requires_keyword():
    """缺 keyword 应报错(纯函数)。"""
    from local_datasource.providers import stock
    with pytest.raises(ValueError, match="resolve_stock_code requires keyword"):
        stock.resolve_stock_code(keyword="", file_path="/tmp/x.csv")


def test_query_stock_min_only_supports_a_market():
    """period=min 仅支持 A 股,在发起任何网络请求前就应报错。"""
    from local_datasource.providers.stock import query_stock
    with pytest.raises(ValueError, match="period=min 仅支持 A 股"):
        query_stock("AAPL", market="us", start_date="2026-08-25", end_date="2026-08-27",
                    file_path="/tmp/x.csv", period="min")


def test_query_stock_min_requires_dates():
    from local_datasource.providers.stock import query_stock
    with pytest.raises(ValueError, match="period=min 需提供"):
        query_stock("600519", market="a", start_date="", end_date="",
                    file_path="/tmp/x.csv", period="min")


def test_query_stock_min_happy(monkeypatch, tmp_path):
    from local_datasource.providers import common
    from local_datasource.providers.stock import query_stock

    fake = pd.DataFrame({
        "day": ["2026-08-26 09:31:00", "2026-08-27 09:31:00"],
        "open": [1500.0, 1510.0], "close": [1505.0, 1515.0],
    })
    monkeypatch.setattr(common.ak, "stock_zh_a_minute", lambda symbol, period, adjust: fake.copy())
    file_path, summary = query_stock("600519", market="a",
                                     start_date="2026-08-27", end_date="2026-08-27",
                                     file_path=str(tmp_path / "min.csv"), period="min")
    assert "Rows: 1" in summary


def test_query_stock_min_guard_raises(monkeypatch, tmp_path):
    from local_datasource.providers import common
    from local_datasource.providers.stock import query_stock

    fake = pd.DataFrame({"day": ["2026-08-26 09:31:00"], "open": [1.0], "close": [1.0]})
    monkeypatch.setattr(common.ak, "stock_zh_a_minute", lambda symbol, period, adjust: fake.copy())
    with pytest.raises(ValueError, match="补数"):
        query_stock("600519", market="a", start_date="2026-08-01", end_date="2026-08-27",
                    file_path=str(tmp_path / "min.csv"), period="min")


def test_query_stock_unsupported_period():
    from local_datasource.providers.stock import query_stock
    with pytest.raises(ValueError, match="Unsupported period"):
        query_stock("600519", market="a", start_date="2026-08-25", end_date="2026-08-27",
                    file_path="/tmp/x.csv", period="weekly")


@pytest.mark.skipif(os.environ.get("SKIP_INTEGRATION"), reason="integration")
def test_query_stock_min_integration():
    import tempfile
    with tempfile.NamedTemporaryFile(suffix=".csv", delete=False) as f:
        path = f.name
    try:
        from local_datasource.providers.stock import query_stock
        _, summary = query_stock("600519", market="a",
                                 start_date="2026-08-25", end_date="2026-08-27",
                                 file_path=path, period="min")
        assert "Rows:" in summary
    finally:
        os.unlink(path)
