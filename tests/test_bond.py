# tests/test_bond.py
import os
import tempfile

import pytest

from local_datasource.providers.bond import query_bond


def test_normalize_bond_code_strips_ib_suffix():
    from local_datasource.providers import bond
    assert bond._normalize_bond_code("2180495.IB") == "2180495"


def test_normalize_bond_code_strips_exchange_suffix():
    from local_datasource.providers import bond
    assert bond._normalize_bond_code("sh019623") == "sh019623"
    assert bond._normalize_bond_code("019623.SH") == "019623"


def test_normalize_bond_code_plain_digits():
    from local_datasource.providers import bond
    assert bond._normalize_bond_code("2180495") == "2180495"


def test_normalize_bond_code_invalid():
    from local_datasource.providers import bond
    with pytest.raises(ValueError):
        bond._normalize_bond_code("abc!@#")


@pytest.mark.skipif(os.environ.get("SKIP_INTEGRATION"), reason="integration")
def test_query_bond_yield_curve():
    with tempfile.NamedTemporaryFile(suffix=".csv", delete=False) as f:
        path = f.name
    try:
        file_path, summary = query_bond(
            kind="yield_curve", start_date="2025-01-01", end_date="2025-06-30", file_path=path)
        assert os.path.exists(file_path)
        assert "Rows:" in summary
        assert "Columns:" in summary
    finally:
        os.unlink(path)


def _skip_on_cm_rate_limit() -> None:
    """实网前置:货币网处于连接数限流(HTTP 421)惩罚窗口时诚实 skip。

    本机当天探测/压测会触发惩罚,此时跳过而非 fail;窗口恢复(数小时)后
    测试自动转绿。单次廉价探测(1 个请求,走共享 keep-alive 连接)。
    """
    from local_datasource.providers import bond
    try:
        probe = bond._cm_post(
            bond._CM_LIST_URL, {"pageNo": "1", "pageSize": "1", "bondType": "100004"})
    except Exception:  # 断网等异常留给查询路径真实报错
        return
    if probe.status_code == 421:
        pytest.skip("货币网连接数限流惩罚窗口内(421),实网验证顺延;离线用例已覆盖逻辑")


@pytest.mark.skipif(os.environ.get("SKIP_INTEGRATION"), reason="integration")
def test_query_bond_issue_info_exact_match():
    """回归 case:2180495.IB 只应返回 1 条「21徐州新盛03」,排除子串误命中的 112180495。"""
    _skip_on_cm_rate_limit()
    with tempfile.NamedTemporaryFile(suffix=".csv", delete=False) as f:
        path = f.name
    try:
        file_path, summary = query_bond(kind="issue_info", bond_code="2180495.IB", file_path=path)
        assert os.path.exists(file_path)
        import pandas as pd
        df = pd.read_csv(file_path)
        assert len(df) == 1, f"expected exactly 1 row, got {len(df)}:\n{df}"
        assert "徐州新盛03" in str(df.iloc[0].values) or "2180495" in str(df.iloc[0].values)
    finally:
        os.unlink(path)


def test_query_bond_issue_info_requires_bond_code():
    from local_datasource.providers import bond
    with pytest.raises(ValueError, match="issue_info requires bond_code"):
        bond.query_bond(kind="issue_info", file_path="/tmp/x.csv")


@pytest.mark.skipif(os.environ.get("SKIP_INTEGRATION"), reason="integration")
def test_query_bond_credit_daily():
    with tempfile.NamedTemporaryFile(suffix=".csv", delete=False) as f:
        path = f.name
    try:
        file_path, summary = query_bond(
            kind="credit_daily", symbol="sh019547",
            start_date="2025-01-01", end_date="2025-06-30", file_path=path)
        assert os.path.exists(file_path)
        assert "Rows:" in summary
    finally:
        os.unlink(path)


@pytest.mark.skipif(os.environ.get("SKIP_INTEGRATION"), reason="integration")
def test_query_bond_issue_info_by_issuer():
    """按发行人查:成都东方广益 → 返回最新一只债(1 行,含代码)。"""
    _skip_on_cm_rate_limit()
    import pandas as pd
    with tempfile.NamedTemporaryFile(suffix=".csv", delete=False) as f:
        path = f.name
    try:
        file_path, summary = query_bond(
            kind="issue_info", bond_issue="成都东方广益", file_path=path)
        df = pd.read_csv(file_path)
        # 按发行日期降序取最新一只,应只有 1 行
        assert len(df) == 1, f"expected 1 row (latest), got {len(df)}"
        assert "成都东方广益" in str(df.iloc[0].values)
    finally:
        os.unlink(path)


def test_query_bond_issue_info_bond_code_and_issue_mutually_exclusive():
    """bond_code 与 bond_issue 同时给应报错(纯函数)。"""
    from local_datasource.providers import bond
    with pytest.raises(ValueError, match="互斥"):
        bond.query_bond(kind="issue_info", bond_code="2180495",
                        bond_issue="成都东方广益", file_path="/tmp/x.csv")


def test_query_bond_issue_info_requires_bond_code_or_issue():
    """issue_info 缺 bond_code 且 bond_issue 应报错(纯函数)。"""
    from local_datasource.providers import bond
    with pytest.raises(ValueError, match="issue_info requires"):
        bond.query_bond(kind="issue_info", file_path="/tmp/x.csv")


# ---------- _bond_info_cm_direct 离线测试(monkeypatch,不连网) ----------
# 背景:货币网改版后 BondMarketInfoList2 强制 bondType(30 类型逐一遍历),
# akshare ≤1.18.94 未适配(实测 1.18.94 同断),故 provider 直连接口。


def _fake_row(code="2180495", name="21东方广益03", date="2021-12-06", btype="企业债",
             defined="ffcdbhj505", enty="成都东方广益投资有限公司"):
    return {"bondDefinedCode": defined, "bondName": name, "bondCode": code,
            "issueStartDate": date, "bondType": btype, "entyFullName": enty,
            "debtRtng": "---"}


def _patch_types(monkeypatch, codes):
    from local_datasource.providers import bond
    monkeypatch.setattr(bond, "_cm_bond_type_codes", lambda: tuple(codes))


def test_direct_merges_types_and_keeps_columns(monkeypatch):
    from local_datasource.providers import bond
    _patch_types(monkeypatch, ["100001", "100004"])

    def fake_fetch(bond_type, page_no, bond_code, bond_issue):
        assert page_no == 1 and bond_issue == "成都东方广益"
        if bond_type == "100001":
            return {"resultList": [], "pageTotal": 1}
        return {"resultList": [_fake_row(), _fake_row(code="---", name="20东方广益01", date="---")],
                "pageTotal": 1}

    monkeypatch.setattr(bond, "_cm_fetch", fake_fetch)
    df = bond._bond_info_cm_direct(bond_issue="成都东方广益")
    assert list(df.columns) == bond._CM_OUTPUT_COLUMNS, "输出列须与原 akshare bond_info_cm 一致"
    assert len(df) == 2


def test_direct_dedupes_cross_type(monkeypatch):
    """同一只债出现在多个类型结果中时去重。"""
    from local_datasource.providers import bond
    _patch_types(monkeypatch, ["100010", "100073"])

    def fake_fetch(bond_type, page_no, bond_code, bond_issue):
        return {"resultList": [_fake_row()], "pageTotal": 1}

    monkeypatch.setattr(bond, "_cm_fetch", fake_fetch)
    df = bond._bond_info_cm_direct(bond_issue="成都东方广益")
    assert len(df) == 1


def test_direct_follows_pagination(monkeypatch):
    from local_datasource.providers import bond
    _patch_types(monkeypatch, ["100004"])
    pages_seen = []

    def fake_fetch(bond_type, page_no, bond_code, bond_issue):
        pages_seen.append(page_no)
        if page_no == 1:
            return {"resultList": [_fake_row()], "pageTotal": 2}
        return {"resultList": [_fake_row(code="2380205", name="23东方广益01", date="2023-07-05")],
                "pageTotal": 2}

    monkeypatch.setattr(bond, "_cm_fetch", fake_fetch)
    df = bond._bond_info_cm_direct(bond_issue="成都东方广益")
    assert pages_seen == [1, 2]
    assert len(df) == 2


def test_direct_partial_failure_raises_with_types(monkeypatch):
    """任一类型失败必须整体报错并列出类型(绝不静默返回缺类型的残缺结果)。"""
    from local_datasource.providers import bond
    _patch_types(monkeypatch, ["100001", "100004"])

    def fake_fetch(bond_type, page_no, bond_code, bond_issue):
        if bond_type == "100004":
            raise ValueError("boom")
        return {"resultList": [_fake_row()], "pageTotal": 1}

    monkeypatch.setattr(bond, "_cm_fetch", fake_fetch)
    with pytest.raises(ValueError, match="1/2 个债券类型失败") as excinfo:
        bond._bond_info_cm_direct(bond_issue="成都东方广益")
    assert "100004" in str(excinfo.value)


def test_direct_all_fail_raises_network_hint(monkeypatch):
    from local_datasource.providers import bond
    _patch_types(monkeypatch, ["100001"])
    monkeypatch.setattr(bond, "_cm_fetch",
                        lambda *a, **k: (_ for _ in ()).throw(ConnectionError("refused")))
    with pytest.raises(ValueError, match="该源在当前网络不可达"):
        bond._bond_info_cm_direct(bond_issue="成都东方广益")


def test_direct_rate_limited_aborts_remaining(monkeypatch):
    """HTTP 421 限流:立即中止剩余类型请求,报错文案含 421 与稍候指引。"""
    from local_datasource.providers import bond
    codes = [f"1{i:05d}" for i in range(10)]
    _patch_types(monkeypatch, codes)
    attempted = []

    def fake_fetch(bond_type, page_no, bond_code, bond_issue):
        attempted.append(bond_type)
        raise bond._CmRateLimited("货币网连接数限流(HTTP 421)")

    monkeypatch.setattr(bond, "_cm_fetch", fake_fetch)
    with pytest.raises(ValueError, match="421"):
        bond._bond_info_cm_direct(bond_issue="成都东方广益")
    # cancel_futures 中止排队任务;在途的至多再有一个,远小于全部 10 个
    assert len(attempted) <= 4, f"421 后应中止剩余请求,实际尝试了 {len(attempted)}/10"


def test_by_issuer_picks_latest_and_skips_undated(monkeypatch, tmp_path):
    """'---'(无代码/无日期)记录在降序排序中沉底,最新有码债券入选。"""
    from local_datasource.providers import bond
    _patch_types(monkeypatch, ["100004"])

    def fake_fetch(bond_type, page_no, bond_code, bond_issue):
        return {"resultList": [
            _fake_row(code="---", name="20东方广益01", date="---"),
            _fake_row(code="2380205", name="23东方广益01", date="2023-07-05"),
            _fake_row(code="2180495", name="21东方广益03", date="2021-12-06"),
        ], "pageTotal": 1}

    monkeypatch.setattr(bond, "_cm_fetch", fake_fetch)
    out = tmp_path / "issuer.csv"
    file_path, _ = bond.query_bond(kind="issue_info", bond_issue="成都东方广益", file_path=str(out))
    import pandas as pd
    df = pd.read_csv(file_path)
    assert len(df) == 1
    assert str(df.iloc[0]["债券代码"]) == "2380205"


def test_cm_type_codes_cached_and_raises_on_failure(monkeypatch):
    """字典请求失败报网络指引;成功结果进程内缓存(不再二次请求)。"""
    from local_datasource.providers import bond
    calls = []

    class FakeResp:
        @staticmethod
        def json():
            return {"data": {"bondType": [{"bondTypeCode": "100004", "bondDisplayType": "企业债"}]}}

    def fake_post(url, data=None):
        calls.append(url)
        return FakeResp()

    monkeypatch.setattr(bond, "_cm_post", fake_post)
    bond._cm_bond_type_codes.cache_clear()
    assert bond._cm_bond_type_codes() == ("100004",)
    bond._cm_bond_type_codes()  # 第二次命中缓存
    assert len(calls) == 1
    bond._cm_bond_type_codes.cache_clear()

    def boom(url, data=None):
        raise ConnectionError("refused")

    monkeypatch.setattr(bond, "_cm_post", boom)
    with pytest.raises(ValueError, match="该源在当前网络不可达"):
        bond._cm_bond_type_codes()
    bond._cm_bond_type_codes.cache_clear()
