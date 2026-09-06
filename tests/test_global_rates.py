# tests/test_global_rates.py
"""query_global_rates 单测(全离线,monkeypatch)+ 集成冒烟(skipif 无网)。

契约要点:
- kind 非法报错;tenure 仅 kind=us_treasury 有效
- us_treasury 全表输出列 date, us_2y, us_5y, us_10y, us_30y, us_10y_2y;短端单期限 date, us_<tenure>
- fed_rate 解析纽约联储 refRates(effectiveDate/percentRate),输出 date, effr 且日期升序;
  跨年分段请求合并(边界不重叠、跨段去重、升序)
- dxy 首选东财 index_global_hist_em(中文列映射 date/open/high/low/close),
  失败回退 yfinance DX-Y.NYB;两源均失败抛 ValueError 且文案含"不可达"
- vix 直连 CBOE VIX_History.csv(DATE,OPEN,HIGH,LOW,CLOSE → date/open/high/low/close,
  US 风格日期归一 YYYY-MM-DD 升序);请求失败重试一次,仍失败抛 ValueError 且文案含"不可达"
"""
import os
import tempfile
from urllib.parse import parse_qs, urlparse

import pandas as pd
import pytest

from local_datasource.providers import common as ds_common
from local_datasource.providers import global_rates as gr
from local_datasource.providers.global_rates import query_global_rates


# ---------- 参数校验(纯逻辑,不连网) ----------

def test_invalid_kind_raises(tmp_path):
    with pytest.raises(ValueError, match="Unsupported"):
        query_global_rates(kind="gold", file_path=str(tmp_path / "x.csv"))


def test_tenure_only_for_treasury(tmp_path):
    with pytest.raises(ValueError, match="tenure"):
        query_global_rates(kind="fed_rate", file_path=str(tmp_path / "x.csv"), tenure="10y")


# ---------- us_treasury(monkeypatch,不连网) ----------

def _fake_em_full():
    """bond_zh_us_rate 中文列样例(13 列全字段,2 行)。"""
    return pd.DataFrame({
        "日期": ["1990-12-19", "2026-09-04"],
        "中国国债收益率2年": [None, 1.2430],
        "中国国债收益率5年": [None, 1.4014],
        "中国国债收益率10年": [None, 1.6804],
        "中国国债收益率30年": [None, 2.1335],
        "中国国债收益率10年-2年": [None, 0.4374],
        "中国GDP年增率": [None, None],
        "美国国债收益率2年": [7.21, 4.37],
        "美国国债收益率5年": [7.64, 4.54],
        "美国国债收益率10年": [8.00, 4.78],
        "美国国债收益率30年": [8.19, 5.24],
        "美国国债收益率10年-2年": [0.79, 0.41],
        "美国GDP年增率": [None, None],
    })


def test_us_treasury_eastmoney_columns(monkeypatch, tmp_path):
    monkeypatch.setattr(gr.ak, "bond_zh_us_rate", lambda start_date: _fake_em_full())
    file_path, _ = query_global_rates(kind="us_treasury", file_path=str(tmp_path / "t.csv"))
    out = pd.read_csv(file_path)
    assert list(out.columns) == ["date", "us_2y", "us_5y", "us_10y", "us_30y", "us_10y_2y"]
    assert len(out) == 2

    # 单一长端期限 → date, us_<tenure>
    file_path2, _ = query_global_rates(
        kind="us_treasury", file_path=str(tmp_path / "t10.csv"), tenure="10y")
    out2 = pd.read_csv(file_path2)
    assert list(out2.columns) == ["date", "us_10y"]
    assert out2["us_10y"].tolist() == [8.00, 4.78]


def test_us_treasury_invalid_tenure_raises(tmp_path):
    with pytest.raises(ValueError, match="Unsupported tenure"):
        query_global_rates(kind="us_treasury", file_path=str(tmp_path / "x.csv"), tenure="3y")


def test_us_treasury_eastmoney_column_drift_raises(monkeypatch, tmp_path):
    """上游列漂移守卫:缺美国列时报可读错误而非裸 KeyError。"""
    drifted = _fake_em_full().drop(columns=["美国国债收益率10年"])
    monkeypatch.setattr(gr.ak, "bond_zh_us_rate", lambda start_date: drifted)
    with pytest.raises(ValueError, match="列名不受支持"):
        query_global_rates(kind="us_treasury", file_path=str(tmp_path / "x.csv"))


def test_us_treasury_sina_column_drift_raises(monkeypatch, tmp_path):
    drifted = pd.DataFrame({"day": ["2026-09-03"], "close": [3.84]})  # date 列缺失
    monkeypatch.setattr(gr.ak, "bond_gb_us_sina", lambda symbol: drifted)
    with pytest.raises(ValueError, match="列名不受支持"):
        query_global_rates(kind="us_treasury", file_path=str(tmp_path / "x.csv"), tenure="3m")


def test_us_treasury_short_tenure_routes_to_sina(monkeypatch, tmp_path):
    called = {}

    def fake_sina(symbol):
        called["symbol"] = symbol
        return pd.DataFrame({
            "date": ["2026-09-03", "2026-09-04"],
            "open": [3.8820, 3.8432], "high": [3.887, 3.873],
            "low": [3.838, 3.836], "close": [3.8432, 3.8571], "volume": [0, 0],
        })

    def must_not_call(start_date):
        raise AssertionError("短端期限不应调用东财全表接口")

    monkeypatch.setattr(gr.ak, "bond_gb_us_sina", fake_sina)
    monkeypatch.setattr(gr.ak, "bond_zh_us_rate", must_not_call)
    file_path, _ = query_global_rates(
        kind="us_treasury", file_path=str(tmp_path / "s.csv"), tenure="3m")
    assert called["symbol"] == "美国3月期国债"
    out = pd.read_csv(file_path)
    assert list(out.columns) == ["date", "us_3m"]
    assert out["us_3m"].tolist() == [3.8432, 3.8571]


# ---------- fed_rate(monkeypatch requests,不连网) ----------

class _FakeResponse:
    def __init__(self, payload):
        self._payload = payload

    def raise_for_status(self):
        return None

    def json(self):
        return self._payload


def test_fed_rate_parses_nyfed_response(monkeypatch, tmp_path):
    """真实 API 按日期降序返回 → 断言输出 date, effr 且升序。"""
    payload = {"refRates": [
        {"effectiveDate": "2026-09-03", "type": "EFFR", "percentRate": 3.63,
         "targetRateFrom": 3.5, "targetRateTo": 3.75},
        {"effectiveDate": "2026-09-02", "type": "EFFR", "percentRate": 3.63,
         "targetRateFrom": 3.5, "targetRateTo": 3.75},
        {"effectiveDate": "2026-09-01", "type": "EFFR", "percentRate": 3.65,
         "targetRateFrom": 3.5, "targetRateTo": 3.75},
    ]}
    urls = []

    def fake_get(url, timeout):
        urls.append(url)
        return _FakeResponse(payload)

    monkeypatch.setattr(gr.requests, "get", fake_get)
    file_path, _ = query_global_rates(
        kind="fed_rate", file_path=str(tmp_path / "f.csv"),
        start_date="2026-09-01", end_date="2026-09-03")
    out = pd.read_csv(file_path)
    assert list(out.columns) == ["date", "effr"]
    assert out["date"].tolist() == ["2026-09-01", "2026-09-02", "2026-09-03"]
    assert out["effr"].tolist() == [3.65, 3.63, 3.63]
    assert len(urls) == 1 and "effr" in urls[0]


def test_fed_rate_retries_once_then_raises(monkeypatch, tmp_path):
    calls = []

    def fail_get(url, timeout):
        calls.append(url)
        raise gr.requests.exceptions.ConnectionError("boom")

    monkeypatch.setattr(gr.requests, "get", fail_get)
    with pytest.raises(ValueError, match="纽约联储") as excinfo:
        query_global_rates(kind="fed_rate", file_path=str(tmp_path / "f.csv"),
                           start_date="2026-09-01", end_date="2026-09-03")
    assert len(calls) == 2, "失败后应恰好重试一次"
    assert excinfo.value.__cause__ is not None, "应保留原始网络异常链"


def test_fed_rate_multi_chunk_merge(monkeypatch, tmp_path):
    """2000~2026 跨 3 个 10 年分段:分段数正确、边界不重叠、跨段去重、合并升序。"""
    requested = []
    # 按 URL 中的 startDate 分段返回;2010 段故意混入 2009-12-31 验证跨段去重
    chunk_rows = {
        "2000-01-01": [("2009-12-31", 2.0), ("2009-12-30", 2.1)],
        "2010-01-01": [("2019-12-31", 1.5), ("2009-12-31", 2.0)],
        "2020-01-01": [("2026-09-03", 3.63), ("2026-09-02", 3.65)],
    }

    def fake_get(url, timeout):
        q = parse_qs(urlparse(url).query)
        start, end = q["startDate"][0], q["endDate"][0]
        requested.append((start, end))
        rows = chunk_rows[start]
        # 真实 API 按日期降序返回 → reverse 模拟
        return _FakeResponse({"refRates": [
            {"effectiveDate": d, "type": "EFFR", "percentRate": r}
            for d, r in reversed(rows)
        ]})

    monkeypatch.setattr(gr.requests, "get", fake_get)
    file_path, _ = query_global_rates(
        kind="fed_rate", file_path=str(tmp_path / "f.csv"),
        start_date="2000-01-01", end_date="2026-09-03")
    assert len(requested) == 3, f"应按 10 年拆 3 段, 实际 {requested}"
    for (_, prev_end), (next_start, _) in zip(requested, requested[1:]):
        assert next_start > prev_end, "相邻分段请求区间不得重叠"
    out = pd.read_csv(file_path)
    assert out["date"].tolist() == [
        "2009-12-30", "2009-12-31", "2019-12-31", "2026-09-02", "2026-09-03"]
    assert (out["date"] == "2009-12-31").sum() == 1, "跨段重复日期应去重"
    assert out["effr"].tolist() == [2.1, 2.0, 1.5, 3.65, 3.63]


# ---------- dxy(monkeypatch,不连网) ----------

def _fake_yf_frame():
    """模拟 yfinance(>=0.2.54)单标的下载:MultiIndex 列 + Date 索引 + 含 Volume。"""
    idx = pd.DatetimeIndex(pd.to_datetime(["2026-09-02", "2026-09-03", "2026-09-04"]), name="Date")
    cols = pd.MultiIndex.from_product(
        [["Open", "High", "Low", "Close", "Volume"], ["DX-Y.NYB"]])
    data = [
        [100.1, 101.2, 99.8, 100.9, 0],
        [100.9, 102.0, 100.5, 101.5, 0],
        [101.5, 102.3, 101.0, 102.1, 0],
    ]
    return pd.DataFrame(data, index=idx, columns=cols)


def _fake_em_dxy():
    """index_global_hist_em 中文列样例(降序,模拟真实返回)。"""
    return pd.DataFrame({
        "日期": ["2026-09-04", "2026-09-03"],
        "今开": [101.5, 100.9], "最新价": [102.1, 101.5],
        "最高": [102.3, 102.0], "最低": [101.0, 100.5],
        "振幅": [1.28, 1.49],
    })


def test_dxy_falls_back_to_yfinance(monkeypatch, tmp_path):
    """东财抛 RemoteDisconnected → 回退 yfinance,输出列与数值正确。"""
    called = {"em": 0, "ticker": None}

    def em_fail(symbol):
        called["em"] += 1
        raise gr.requests.exceptions.RemoteDisconnected("remote disconnected")

    def fake_download(ticker, **kwargs):
        called["ticker"] = ticker
        frame = _fake_yf_frame()
        # 追加一行 close 缺失的数据,验证输出不残留 NaN 行
        nan_row = pd.DataFrame(
            [[float("nan")] * 5], index=pd.DatetimeIndex(["2026-09-05"], name="Date"),
            columns=frame.columns)
        return pd.concat([frame, nan_row])

    monkeypatch.setattr(gr.ak, "index_global_hist_em", em_fail)
    monkeypatch.setattr(ds_common.yf, "download", fake_download)
    file_path, _ = query_global_rates(kind="dxy", file_path=str(tmp_path / "d.csv"))
    assert called["em"] == 1, "应先尝试东财源"
    assert called["ticker"] == "DX-Y.NYB"
    out = pd.read_csv(file_path)
    assert list(out.columns) == ["date", "open", "high", "low", "close"]
    assert out["date"].tolist() == ["2026-09-02", "2026-09-03", "2026-09-04"]
    assert out["close"].tolist() == [100.9, 101.5, 102.1]
    assert "volume" not in out.columns, "Volume 列应被丢弃"
    assert not out.isna().any().any(), "close 缺失的行应被丢弃"


def test_dxy_yahoo_end_day_inclusive(monkeypatch, tmp_path):
    """yfinance 的 end 为排他区间 → 实现应补一天,输出仍含 end_date 当日(闭区间契约)。"""
    captured = {}

    def em_fail(symbol):
        raise gr.requests.exceptions.RemoteDisconnected("remote disconnected")

    def fake_download(ticker, **kwargs):
        captured["ticker"] = ticker
        captured.update(kwargs)
        # 模拟 yfinance 尊重排他 end:返回 01-05..01-10(不含补的 01-11)
        idx = pd.DatetimeIndex(pd.to_datetime(
            ["2026-01-05", "2026-01-06", "2026-01-09", "2026-01-10"]), name="Date")
        cols = pd.MultiIndex.from_product(
            [["Open", "High", "Low", "Close", "Volume"], ["DX-Y.NYB"]])
        data = [[100.0, 101.0, 99.0, 100.5, 0]] * 4
        return pd.DataFrame(data, index=idx, columns=cols)

    monkeypatch.setattr(gr.ak, "index_global_hist_em", em_fail)
    monkeypatch.setattr(ds_common.yf, "download", fake_download)
    file_path, _ = query_global_rates(
        kind="dxy", file_path=str(tmp_path / "d.csv"),
        start_date="2026-01-05", end_date="2026-01-10")
    assert captured["start"] == "2026-01-05"
    assert captured["end"] == "2026-01-11", "yfinance end 排他,应补一天"
    out = pd.read_csv(file_path)
    assert out["date"].tolist()[-1] == "2026-01-10", "闭区间契约:end_date 当日不得缺失"


def test_dxy_eastmoney_primary(monkeypatch, tmp_path):
    """东财可用时不触发 yfinance;中文列正确映射且升序。"""
    def must_not_download(ticker, **kwargs):
        raise AssertionError("东财成功时不应回退 yfinance")

    monkeypatch.setattr(gr.ak, "index_global_hist_em", lambda symbol: _fake_em_dxy())
    monkeypatch.setattr(ds_common.yf, "download", must_not_download)
    file_path, _ = query_global_rates(kind="dxy", file_path=str(tmp_path / "d.csv"))
    out = pd.read_csv(file_path)
    assert list(out.columns) == ["date", "open", "high", "low", "close"]
    assert out["date"].tolist() == ["2026-09-03", "2026-09-04"]
    assert out["close"].tolist() == [101.5, 102.1]


def test_dxy_date_filter(monkeypatch, tmp_path):
    """start/end 区间过滤作用于回退归一后的结果。"""
    monkeypatch.setattr(gr.ak, "index_global_hist_em", lambda symbol: _fake_em_dxy())
    file_path, _ = query_global_rates(
        kind="dxy", file_path=str(tmp_path / "d.csv"),
        start_date="2026-09-04", end_date="2026-09-04")
    out = pd.read_csv(file_path)
    assert out["date"].tolist() == ["2026-09-04"]


def test_dxy_eastmoney_column_drift_raises(monkeypatch, tmp_path):
    drifted = _fake_em_dxy().rename(columns={"最新价": "收盘"})
    monkeypatch.setattr(gr.ak, "index_global_hist_em", lambda symbol: drifted)
    with pytest.raises(ValueError, match="列名不受支持"):
        query_global_rates(kind="dxy", file_path=str(tmp_path / "x.csv"))


def test_dxy_all_sources_unreachable(monkeypatch, tmp_path):
    """两源均失败 → ValueError 含"不可达" + 代理/网络指引 + 列出尝试过的源,保留异常链。"""

    def em_fail(symbol):
        raise gr.requests.exceptions.RemoteDisconnected("remote disconnected")

    def yf_fail(ticker, **kwargs):
        raise ConnectionError("yahoo blocked")

    monkeypatch.setattr(gr.ak, "index_global_hist_em", em_fail)
    monkeypatch.setattr(ds_common.yf, "download", yf_fail)
    with pytest.raises(ValueError) as excinfo:
        query_global_rates(kind="dxy", file_path=str(tmp_path / "x.csv"))
    msg = str(excinfo.value)
    assert "该源在当前网络不可达" in msg
    assert "代理" in msg or "网络" in msg
    assert "index_global_hist_em" in msg and "DX-Y.NYB" in msg, "应列出尝试过的数据源"
    assert excinfo.value.__cause__ is not None, "应保留原始异常链"


# ---------- vix(monkeypatch requests,不连网) ----------

# 样例故意乱序(3/15/2024 排在 12/31/2026 之后)并混入 NaN close 行(1/6/1990):
# 验证输出升序排序,且 close 缺失行被丢弃(与 dxy 对称)
_VIX_SAMPLE_CSV = """DATE,OPEN,HIGH,LOW,CLOSE
1/2/1990,17.24,17.24,17.24,17.24
1/3/1990,18.19,18.19,18.19,18.19
12/31/2026,15.50,16.20,15.10,16.02
3/15/2024,14.10,14.80,13.90,14.55
1/6/1990,18.50,18.60,18.40,
"""


class _FakeTextResponse:
    """模拟 requests.Response 的文本响应(CBOE 返回原始 CSV)。"""

    def __init__(self, text):
        self._text = text

    def raise_for_status(self):
        return None

    @property
    def text(self):
        return self._text


def test_vix_parses_cboe_csv(monkeypatch, tmp_path):
    """CBOE CSV 解析:US 风格日期归一 YYYY-MM-DD 且升序,列名映射正确,URL/超时符合契约。"""
    urls = []

    def fake_get(url, timeout):
        urls.append((url, timeout))
        return _FakeTextResponse(_VIX_SAMPLE_CSV)

    monkeypatch.setattr(gr.requests, "get", fake_get)
    file_path, _ = query_global_rates(kind="vix", file_path=str(tmp_path / "v.csv"))
    out = pd.read_csv(file_path)
    assert urls == [(
        "https://cdn.cboe.com/api/global/us_indices/daily_prices/VIX_History.csv", 30,
    )], "应直连 CBOE CSV 且 30 秒超时"
    assert list(out.columns) == ["date", "open", "high", "low", "close"]
    assert out["date"].tolist() == ["1990-01-02", "1990-01-03", "2024-03-15", "2026-12-31"]
    assert out["close"].tolist() == [17.24, 18.19, 14.55, 16.02]
    assert out["date"].is_monotonic_increasing, "乱序输入应输出升序"
    assert not out.isna().any().any(), "close 缺失的行应被丢弃"


def test_vix_retries_once_then_raises(monkeypatch, tmp_path):
    calls = []

    def timeout_get(url, timeout):
        calls.append(url)
        raise gr.requests.exceptions.Timeout("timed out")

    monkeypatch.setattr(gr.requests, "get", timeout_get)
    with pytest.raises(ValueError, match="不可达") as excinfo:
        query_global_rates(kind="vix", file_path=str(tmp_path / "v.csv"))
    assert len(calls) == 2, "失败后应恰好重试一次"
    assert excinfo.value.__cause__ is not None, "应保留原始网络异常链"


def test_vix_date_filter(monkeypatch, tmp_path):
    """start/end 闭区间过滤作用于日期归一后的结果。"""
    monkeypatch.setattr(
        gr.requests, "get", lambda url, timeout: _FakeTextResponse(_VIX_SAMPLE_CSV))
    file_path, _ = query_global_rates(
        kind="vix", file_path=str(tmp_path / "v.csv"),
        start_date="1990-01-03", end_date="1990-01-03")
    out = pd.read_csv(file_path)
    assert out["date"].tolist() == ["1990-01-03"]


def test_vix_cboe_column_drift_raises(monkeypatch, tmp_path):
    """上游列漂移守卫:表头变化时报可读错误而非裸 KeyError。"""
    drifted = _VIX_SAMPLE_CSV.replace("CLOSE", "CLOSE_PRICE")
    monkeypatch.setattr(
        gr.requests, "get", lambda url, timeout: _FakeTextResponse(drifted))
    with pytest.raises(ValueError, match="列名不受支持"):
        query_global_rates(kind="vix", file_path=str(tmp_path / "x.csv"))


# ---------- 集成冒烟(连网,SKIP_INTEGRATION=1 跳过) ----------

@pytest.mark.skipif(os.environ.get("SKIP_INTEGRATION"), reason="integration")
def test_smoke_us_treasury_full_history():
    with tempfile.NamedTemporaryFile(suffix=".csv", delete=False) as f:
        path = f.name
    try:
        file_path, summary = query_global_rates(kind="us_treasury", file_path=path)
        out = pd.read_csv(file_path)
        assert len(out) > 9000
        assert out["date"].min() <= "1991-01-01"
    finally:
        os.unlink(path)


@pytest.mark.skipif(os.environ.get("SKIP_INTEGRATION"), reason="integration")
def test_smoke_fed_rate_recent():
    with tempfile.NamedTemporaryFile(suffix=".csv", delete=False) as f:
        path = f.name
    try:
        file_path, summary = query_global_rates(kind="fed_rate", file_path=path)
        out = pd.read_csv(file_path)
        assert not out.empty
        assert out["date"].max() >= "2026-09-01"
    finally:
        os.unlink(path)


@pytest.mark.skipif(os.environ.get("SKIP_INTEGRATION"), reason="integration")
def test_smoke_dxy():
    """真实调用 dxy:先廉价探测东财与 Yahoo,均不可达则 skip(不算失败)。

    东财用 spot 快照接口探测(hist 接口无区间参数,全量历史拉取太重)。
    """
    em_ok = False
    em_reason = ""
    try:
        em_ok = not gr.ak.index_global_spot_em().empty
    except Exception as e:
        em_reason = f"东财: {type(e).__name__}"
    yahoo_ok = False
    yahoo_reason = ""
    try:
        resp = gr.requests.get(
            "https://query1.finance.yahoo.com/v8/finance/chart/DX-Y.NYB?range=5d&interval=1d",
            timeout=10,
        )
        yahoo_ok = resp.status_code == 200
        if not yahoo_ok:
            yahoo_reason = f"Yahoo: HTTP {resp.status_code}"
    except Exception as e:
        yahoo_reason = f"Yahoo: {type(e).__name__}"
    if not em_ok and not yahoo_ok:
        # 429 是限流非物理不可达,文案区分"被拒/限流",避免误导排查方向
        pytest.skip(f"两回退源本机均不可用({em_reason}; {yahoo_reason or 'Yahoo: 200'})")
    with tempfile.NamedTemporaryFile(suffix=".csv", delete=False) as f:
        path = f.name
    try:
        file_path, _ = query_global_rates(kind="dxy", file_path=path)
        out = pd.read_csv(file_path)
        assert not out.empty
        assert list(out.columns) == ["date", "open", "high", "low", "close"]
        assert out["date"].is_monotonic_increasing
    except ValueError as e:
        if "该源在当前网络不可达" in str(e):
            pytest.skip(f"探测通过但真实调用仍不可达(瞬时限流/网络抖动): {e}")
        raise
    finally:
        os.unlink(path)


@pytest.mark.skipif(os.environ.get("SKIP_INTEGRATION"), reason="integration")
def test_smoke_vix():
    """真实调用 vix:先流式探测 CBOE CDN,可达才跑;探测通过后仍瞬时失败(限流)则 skip。

    契约阈值(不得弱化):最早日期 ≤ 1990-06-01,行数 > 8000。
    """
    cboe_ok = False
    try:
        resp = gr.requests.get(
            "https://cdn.cboe.com/api/global/us_indices/daily_prices/VIX_History.csv",
            timeout=10,
            stream=True,  # 只看状态码,不重复拉 ~470KB 响应体
        )
        cboe_ok = resp.status_code == 200
        resp.close()
    except Exception:
        cboe_ok = False
    if not cboe_ok:
        pytest.skip("CBOE CDN 在本机网络不可达")
    with tempfile.NamedTemporaryFile(suffix=".csv", delete=False) as f:
        path = f.name
    try:
        file_path, _ = query_global_rates(kind="vix", file_path=path)
        out = pd.read_csv(file_path)
        assert out["date"].min() <= "1990-06-01"
        assert len(out) > 8000
        assert out["date"].is_monotonic_increasing
    except ValueError as e:
        if "该源在当前网络不可达" in str(e):
            pytest.skip(f"探测通过但真实调用仍不可达(瞬时限流/网络抖动): {e}")
        raise
    finally:
        os.unlink(path)
