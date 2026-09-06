# tests/test_cli.py
"""download CLI 单测(全离线,mock provider + tmp_path 清单)+ 集成冒烟。

契约:
- ``run_download``: ``--config`` 必填、``--data-dir``/``--force`` 可选;
- 每条目输出 SKIP/FETCH/FAIL;单条失败不中断整批,任一失败退出码 1;
- 白名单外 tool / 缺 args / 不支持工具 → 启动期一次性报错,不执行任何下载;
- server.main() 无 download 参数时行为不变(照常启动 MCP stdio server)。

mock 方式:monkeypatch ``cli.TOOL_FUNCS`` 条目(provider 为模块级 dict,可整体替换)。
"""
import asyncio
import json
import os
import sys
from pathlib import Path
from types import SimpleNamespace

import pandas as pd
import pytest
import yaml

import local_datasource.cli as cli
from local_datasource.cache import cache_paths, make_key
from local_datasource.server import main as server_main


# ---------- 测试脚手架 ----------

def make_fake_provider(rows=2, error=None):
    """造一个离线假 provider:记录调用、按契约落盘 CSV(或抛错)。

    返回的函数带 ``calls`` 列表,供断言调用次数与参数。
    """
    calls = []

    def provider(**kwargs):
        calls.append(dict(kwargs))
        if error is not None:
            raise error
        df = pd.DataFrame({
            "date": [f"2024-01-{i + 1:02d}" for i in range(rows)],
            "close": [float(i + 1) for i in range(rows)],
        })
        # 真实 provider 经 format_csv_output 会自动建父目录,这里保持一致
        path = Path(kwargs["file_path"])
        path.parent.mkdir(parents=True, exist_ok=True)
        df.to_csv(path, index=False, encoding="utf-8-sig")
        return str(path), "summary"

    provider.calls = calls
    return provider


def test_file_path_in_args_rejected(tmp_path, monkeypatch, capsys):
    """args 里误写 file_path:启动报错(download 自动落缓存,该值不生效),不执行任何下载。"""
    guard = make_fake_provider()
    for name in cli.TOOL_FUNCS:
        monkeypatch.setitem(cli.TOOL_FUNCS, name, guard)
    manifest = write_manifest_file(tmp_path, {
        "data_dir": str(tmp_path / "cache"),
        "assets": [{"tool": "query_stock",
                    "args": {"ticker": "600519", "market": "a",
                             "start_date": "2026-01-01", "end_date": "2026-01-31",
                             "file_path": "/tmp/should_be_ignored.csv"}}],
    })

    rc = cli.run_download(["--config", str(manifest)])

    assert rc == 2
    captured = capsys.readouterr()
    assert "file_path" in captured.err
    assert "缓存目录" in captured.err
    assert len(guard.calls) == 0


def write_manifest_file(tmp_path: Path, content: dict) -> Path:
    manifest = tmp_path / "manifest.yaml"
    manifest.write_text(
        yaml.safe_dump(content, allow_unicode=True), encoding="utf-8"
    )
    return manifest


# ---------- 契约测试 ----------

def test_download_writes_cache_and_manifest(tmp_path, monkeypatch, capsys):
    """正常下载:provider 收到注入 file_path + 合并日期;CSV/manifest 落盘;打印 FETCH。"""
    fake = make_fake_provider()
    monkeypatch.setitem(cli.TOOL_FUNCS, "query_stock", fake)
    data_dir = tmp_path / "cache"
    manifest = write_manifest_file(tmp_path, {
        "data_dir": str(data_dir),
        "assets": [{
            "tool": "query_stock",
            # args 内的 start_date 应被条目级 start_date 覆盖(条目级优先)
            "args": {"ticker": "600519", "market": "a", "adjust": "qfq",
                     "start_date": "2023-01-01"},
            "start_date": "2024-01-01",
            "end_date": "2024-06-30",
        }],
    })

    rc = cli.run_download(["--config", str(manifest)])

    assert rc == 0
    effective = {"ticker": "600519", "market": "a", "adjust": "qfq",
                 "start_date": "2024-01-01", "end_date": "2024-06-30"}
    key = make_key("query_stock", effective)
    csv_path, manifest_path = cache_paths(str(data_dir), "query_stock", key)
    assert csv_path.is_file()
    assert manifest_path.is_file()
    loaded = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert loaded["args"] == effective
    assert loaded["rows"] == 2
    assert loaded["last_fetched"]
    # provider 调用参数:file_path 注入 + 条目级日期合并进 args(条目级优先)
    assert len(fake.calls) == 1
    assert fake.calls[0]["file_path"] == str(csv_path)
    assert fake.calls[0]["start_date"] == "2024-01-01"
    assert fake.calls[0]["ticker"] == "600519"
    out = capsys.readouterr().out
    assert f"FETCH query_stock/{key} 2 rows" in out


def test_second_run_same_day_skips(tmp_path, monkeypatch, capsys):
    """同一天连跑两次:第二次 provider 不被调用,输出 SKIP。"""
    fake = make_fake_provider()
    monkeypatch.setitem(cli.TOOL_FUNCS, "query_global_rates", fake)
    manifest = write_manifest_file(tmp_path, {
        "data_dir": str(tmp_path / "cache"),
        "assets": [{"tool": "query_global_rates",
                    "args": {"kind": "us_treasury", "tenure": "all"}}],
    })
    argv = ["--config", str(manifest)]

    assert cli.run_download(argv) == 0
    assert len(fake.calls) == 1
    first_out = capsys.readouterr().out
    assert "FETCH query_global_rates/" in first_out

    assert cli.run_download(argv) == 0
    assert len(fake.calls) == 1  # 第二次为 0 次新增调用
    second_out = capsys.readouterr().out
    assert "SKIP query_global_rates/" in second_out
    assert "FETCH" not in second_out


def test_force_refetches(tmp_path, monkeypatch, capsys):
    """--force 忽略当天缓存:第二次仍调用 provider,共 2 次。"""
    fake = make_fake_provider()
    monkeypatch.setitem(cli.TOOL_FUNCS, "query_fx", fake)
    manifest = write_manifest_file(tmp_path, {
        "data_dir": str(tmp_path / "cache"),
        "assets": [{"tool": "query_fx", "args": {"kind": "mid", "currency": "usd"}}],
    })

    assert cli.run_download(["--config", str(manifest)]) == 0
    assert cli.run_download(["--config", str(manifest), "--force"]) == 0

    assert len(fake.calls) == 2
    out = capsys.readouterr().out
    assert "FETCH query_fx/" in out
    assert "SKIP" not in out


def test_unsupported_tool_rejected(tmp_path, monkeypatch, capsys):
    """清单含 align_series → 启动报错,文案含「不支持」,不执行任何下载。"""
    guard = make_fake_provider()
    for name in cli.TOOL_FUNCS:
        monkeypatch.setitem(cli.TOOL_FUNCS, name, guard)
    manifest = write_manifest_file(tmp_path, {
        "data_dir": str(tmp_path / "cache"),
        "assets": [{"tool": "align_series",
                    "args": {"file_paths": ["a.csv", "b.csv"]}}],
    })

    rc = cli.run_download(["--config", str(manifest)])

    assert rc == 2
    captured = capsys.readouterr()
    assert "不支持" in captured.err
    assert "align_series" in captured.err
    assert len(guard.calls) == 0  # 校验失败时绝不发起下载


def test_one_failure_does_not_abort_batch(tmp_path, monkeypatch, capsys):
    """第一条抛错:打印 FAIL,第二条仍执行,退出码 1。"""
    bad = make_fake_provider(error=RuntimeError("boom: upstream down"))
    good = make_fake_provider()
    monkeypatch.setitem(cli.TOOL_FUNCS, "query_stock", bad)
    monkeypatch.setitem(cli.TOOL_FUNCS, "query_fx", good)
    manifest = write_manifest_file(tmp_path, {
        "data_dir": str(tmp_path / "cache"),
        "assets": [
            {"tool": "query_stock",
             "args": {"ticker": "600519", "market": "a",
                      "start_date": "2024-01-01", "end_date": "2024-06-30"}},
            {"tool": "query_fx", "args": {"kind": "mid"}},
        ],
    })

    rc = cli.run_download(["--config", str(manifest)])

    assert rc == 1
    assert len(bad.calls) == 1
    assert len(good.calls) == 1  # 失败后第二条仍被拉取
    out = capsys.readouterr().out
    assert "FAIL query_stock/" in out
    assert "boom" in out
    assert "FETCH query_fx/" in out
    # 失败条目不写 manifest:同 key 下次仍会尝试
    effective = {"ticker": "600519", "market": "a",
                 "start_date": "2024-01-01", "end_date": "2024-06-30"}
    _, manifest_path = cache_paths(str(tmp_path / "cache"), "query_stock",
                                   make_key("query_stock", effective))
    assert not manifest_path.exists()


def test_no_subcommand_still_starts_server(monkeypatch):
    """main() 无 download 参数 → 照常 asyncio.run(_main());有 download → 转交 CLI。"""
    started = []
    download_calls = []

    def fake_asyncio_run(coro, *args, **kwargs):
        started.append(coro)
        coro.close()  # 关掉协程,不真正启动 stdio server

    def fake_run_download(argv):
        download_calls.append(list(argv))
        return 0

    monkeypatch.setattr(cli, "run_download", fake_run_download)
    monkeypatch.setattr(asyncio, "run", fake_asyncio_run)

    # 无参:启动 server(asyncio.run 被调用)
    monkeypatch.setattr(sys, "argv", ["local-datasource"])
    server_main()
    assert len(started) == 1
    assert len(download_calls) == 0

    # download 子命令:转交 CLI,不再启动 server(经 SystemExit 传递退出码)
    monkeypatch.setattr(sys, "argv",
                        ["local-datasource", "download", "--config", "x.yaml"])
    with pytest.raises(SystemExit) as excinfo:
        server_main()
    assert excinfo.value.code == 0
    assert len(started) == 1  # asyncio.run 未被再次调用
    assert download_calls == [["--config", "x.yaml"]]


# ---------- 启动期校验(未知 tool / 缺 args / 用法) ----------

def test_unknown_tool_lists_valid_names(tmp_path, monkeypatch, capsys):
    """未知 tool:报错列出合法 tool 名。"""
    guard = make_fake_provider()
    for name in cli.TOOL_FUNCS:
        monkeypatch.setitem(cli.TOOL_FUNCS, name, guard)
    manifest = write_manifest_file(tmp_path, {
        "data_dir": str(tmp_path / "cache"),
        "assets": [{"tool": "query_nothere", "args": {}}],
    })

    rc = cli.run_download(["--config", str(manifest)])

    assert rc == 2
    captured = capsys.readouterr()
    assert "query_nothere" in captured.err
    assert "query_global_rates" in captured.err  # 合法名单至少含一个示例
    assert len(guard.calls) == 0


def test_missing_args_rejected(tmp_path, monkeypatch, capsys):
    """缺 args:启动报错指出缺 args,不执行任何下载。"""
    guard = make_fake_provider()
    for name in cli.TOOL_FUNCS:
        monkeypatch.setitem(cli.TOOL_FUNCS, name, guard)
    manifest = write_manifest_file(tmp_path, {
        "data_dir": str(tmp_path / "cache"),
        "assets": [{"tool": "query_stock"}],
    })

    rc = cli.run_download(["--config", str(manifest)])

    assert rc == 2
    captured = capsys.readouterr()
    assert "args" in captured.err
    assert len(guard.calls) == 0


def test_multiple_problems_reported_together(tmp_path, monkeypatch, capsys):
    """多条问题一次性报出(校验先于任何下载)。"""
    guard = make_fake_provider()
    for name in cli.TOOL_FUNCS:
        monkeypatch.setitem(cli.TOOL_FUNCS, name, guard)
    manifest = write_manifest_file(tmp_path, {
        "data_dir": str(tmp_path / "cache"),
        "assets": [
            {"tool": "query_nothere", "args": {}},
            {"tool": "resolve_stock_code", "args": {"keyword": "茅台"}},
        ],
    })

    rc = cli.run_download(["--config", str(manifest)])

    assert rc == 2
    captured = capsys.readouterr()
    assert "query_nothere" in captured.err
    assert "不支持" in captured.err
    assert "2 处问题" in captured.err
    assert len(guard.calls) == 0


def test_missing_config_is_usage_error(capsys):
    """缺 --config → argparse 可读 usage 错误,退出码 2。"""
    with pytest.raises(SystemExit) as excinfo:
        cli.run_download([])
    assert excinfo.value.code == 2
    assert "--config" in capsys.readouterr().err


def test_manifest_file_missing(tmp_path, capsys):
    """清单文件不存在 → 可读错误,退出码 2。"""
    rc = cli.run_download(["--config", str(tmp_path / "nope.yaml")])
    assert rc == 2
    assert "无法读取" in capsys.readouterr().err


# ---------- data_dir 优先级与 query_yfinance 注入 ----------

def test_data_dir_precedence_cli_over_manifest(tmp_path, monkeypatch, capsys):
    """--data-dir > 清单顶层 data_dir;各自目录独立判定新鲜度。"""
    fake = make_fake_provider()
    monkeypatch.setitem(cli.TOOL_FUNCS, "query_fx", fake)
    dir_from_manifest = tmp_path / "from-manifest"
    dir_from_cli = tmp_path / "from-cli"
    manifest = write_manifest_file(tmp_path, {
        "data_dir": str(dir_from_manifest),
        "assets": [{"tool": "query_fx", "args": {"kind": "mid"}}],
    })

    assert cli.run_download(["--config", str(manifest), "--data-dir", str(dir_from_cli)]) == 0
    assert any(dir_from_cli.rglob("*.csv"))
    assert not dir_from_manifest.exists()

    assert cli.run_download(["--config", str(manifest)]) == 0  # 落到清单 data_dir
    assert any(dir_from_manifest.rglob("*.csv"))
    assert len(fake.calls) == 2


def test_data_dir_falls_back_to_config(tmp_path, monkeypatch):
    """CLI 与清单都没给 data_dir → 用 config.yaml 的 cache.data_dir。"""
    fake = make_fake_provider()
    monkeypatch.setitem(cli.TOOL_FUNCS, "query_fx", fake)
    cfg_dir = tmp_path / "cfg-cache"
    cfg = SimpleNamespace(
        providers=SimpleNamespace(yahoo=SimpleNamespace(use_yfinance=False)),
        cache=SimpleNamespace(data_dir=str(cfg_dir)),
    )
    monkeypatch.setattr(cli, "load_config", lambda path=None: cfg)
    manifest = write_manifest_file(tmp_path, {
        "assets": [{"tool": "query_fx", "args": {"kind": "mid"}}],
    })

    assert cli.run_download(["--config", str(manifest)]) == 0
    assert any(cfg_dir.rglob("*.csv"))


def test_yfinance_injects_config_use_yfinance(tmp_path, monkeypatch, capsys):
    """query_yfinance:清单未显式给 use_yfinance 时注入 config 默认值;
    显式提供时不查 config。注入值不进入缓存 key/manifest args。"""
    cfg = SimpleNamespace(
        providers=SimpleNamespace(yahoo=SimpleNamespace(use_yfinance=True)),
        cache=SimpleNamespace(data_dir=str(tmp_path / "cache")),
    )
    monkeypatch.setattr(cli, "load_config", lambda path=None: cfg)
    fake = make_fake_provider()
    monkeypatch.setitem(cli.TOOL_FUNCS, "query_yfinance", fake)
    manifest = write_manifest_file(tmp_path, {
        "assets": [{"tool": "query_yfinance", "args": {"ticker": "AAPL"}}],
    })

    assert cli.run_download(["--config", str(manifest)]) == 0
    assert fake.calls[0]["use_yfinance"] is True
    key = make_key("query_yfinance", {"ticker": "AAPL"})
    loaded = json.loads(
        cache_paths(str(tmp_path / "cache"), "query_yfinance", key)[1]
        .read_text(encoding="utf-8")
    )
    assert loaded["args"] == {"ticker": "AAPL"}  # 注入值不落 manifest

    # 显式 use_yfinance: false 时以清单为准;data_dir 由清单提供,
    # 因此若代码仍去读 config 注入开关,_boom 会立刻暴露
    def _boom(path=None):
        raise AssertionError("显式 use_yfinance 时不应读取 config")

    monkeypatch.setattr(cli, "load_config", _boom)
    fake2 = make_fake_provider()
    monkeypatch.setitem(cli.TOOL_FUNCS, "query_yfinance", fake2)
    manifest2 = write_manifest_file(tmp_path, {
        "data_dir": str(tmp_path / "cache"),
        "assets": [{"tool": "query_yfinance",
                    "args": {"ticker": "SPY", "use_yfinance": False}}],
    })
    assert cli.run_download(["--config", str(manifest2), "--force"]) == 0
    assert fake2.calls[0]["use_yfinance"] is False
    assert "SKIP" not in capsys.readouterr().out


# ---------- 集成冒烟(连网,SKIP_INTEGRATION=1 跳过) ----------

@pytest.mark.skipif(os.environ.get("SKIP_INTEGRATION"), reason="integration")
def test_live_download_global_rates_twice(tmp_path, capsys):
    """真实清单拉 query_global_rates(kind=us_treasury) 连跑两次,第二次 SKIP。"""
    data_dir = tmp_path / "live-cache"
    manifest = write_manifest_file(tmp_path, {
        "data_dir": str(data_dir),
        "assets": [{"tool": "query_global_rates",
                    "args": {"kind": "us_treasury", "tenure": "all"}}],
    })

    assert cli.run_download(["--config", str(manifest)]) == 0
    first = capsys.readouterr()
    assert "FETCH query_global_rates/" in first.out
    assert any(data_dir.rglob("query_global_rates/*.csv"))

    assert cli.run_download(["--config", str(manifest)]) == 0
    second = capsys.readouterr()
    assert "SKIP query_global_rates/" in second.out
    assert "FETCH" not in second.out
