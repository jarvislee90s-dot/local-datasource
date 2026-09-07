# tests/test_stdio_probe.py
"""stdio 真实路径探针：subprocess 起服务 → initialize → tools/list → tools/call → 错误指引。

- fe9ed77 教训回归门：业务报错必须以 "Error calling <name>: ..." 文本到达客户端，
  而非 mcp 2.x 默认吞成的裸 "Error executing tool <name>"。
- 全离线：tools/call 用纯本地工具（query_trading_rules）与确定性业务错误
  （align_series 输入文件不存在）。
"""
import json
import subprocess
import sys

import pytest

from local_datasource import server
from local_datasource.providers.common import CoverageError


class _StdioProbe:
    def __init__(self) -> None:
        self.proc = subprocess.Popen(
            [sys.executable, "-m", "local_datasource.server"],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            text=True, encoding="utf-8",
        )

    def request(self, payload: dict) -> dict:
        assert self.proc.stdin is not None and self.proc.stdout is not None
        self.proc.stdin.write(json.dumps(payload, ensure_ascii=False) + "\n")
        self.proc.stdin.flush()
        line = self.proc.stdout.readline()
        assert line.strip(), "服务端关闭了 stdout（看 stderr: " + (self.proc.stderr.read() if self.proc.stderr else "") + "）"
        return json.loads(line)

    def notify(self, payload: dict) -> None:
        """发送 notification(协议约定不产生应答),只写不等 readline,否则永久阻塞。"""
        assert self.proc.stdin is not None
        self.proc.stdin.write(json.dumps(payload, ensure_ascii=False) + "\n")
        self.proc.stdin.flush()

    def close(self) -> None:
        self.proc.terminate()
        self.proc.wait(timeout=10)


@pytest.fixture()
def probe():
    p = _StdioProbe()
    yield p
    p.close()


def _handshake(probe: _StdioProbe) -> None:
    probe.request({"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {
        "protocolVersion": "2024-11-05", "capabilities": {},
        "clientInfo": {"name": "probe", "version": "0"},
    }})
    probe.notify({"jsonrpc": "2.0", "method": "notifications/initialized"})


def test_initialize_returns_server_info(probe):
    resp = probe.request({"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {
        "protocolVersion": "2024-11-05", "capabilities": {},
        "clientInfo": {"name": "probe", "version": "0"},
    }})
    assert resp["result"]["serverInfo"]["name"] == "local-datasource"


def test_tools_list_has_16(probe):
    _handshake(probe)
    resp = probe.request({"jsonrpc": "2.0", "id": 2, "method": "tools/list"})
    assert len({t["name"] for t in resp["result"]["tools"]}) == 16


def test_tools_call_returns_csv_preview(probe, tmp_path):
    _handshake(probe)
    out = str(tmp_path / "rules.csv")
    resp = probe.request({"jsonrpc": "2.0", "id": 3, "method": "tools/call", "params": {
        "name": "query_trading_rules", "arguments": {"market": "a", "file_path": out},
    }})
    text = resp["result"]["content"][0]["text"]
    assert not text.startswith("Error calling")
    assert out in text


def test_business_error_text_reaches_client(probe, tmp_path):
    _handshake(probe)
    resp = probe.request({"jsonrpc": "2.0", "id": 4, "method": "tools/call", "params": {
        "name": "align_series",
        "arguments": {
            "file_paths": ["Z:/__no_such_1.csv", "Z:/__no_such_2.csv"],
            "file_path": str(tmp_path / "out.csv"),
        },
    }})
    text = resp["result"]["content"][0]["text"]
    assert text.startswith("Error calling align_series")
    assert "输入文件不存在" in text
    assert "Error executing tool" not in text


def test_tools_call_align_series_end_to_end(probe, tmp_path):
    _handshake(probe)
    a = tmp_path / "a.csv"
    b = tmp_path / "b.csv"
    a.write_text("date,close\n2026-09-01,100\n2026-09-02,101\n", encoding="utf-8")
    b.write_text("date,close\n2026-09-01,50\n2026-09-02,49\n", encoding="utf-8")
    out = str(tmp_path / "aligned.csv")
    resp = probe.request({"jsonrpc": "2.0", "id": 5, "method": "tools/call", "params": {
        "name": "align_series",
        "arguments": {"file_paths": [str(a), str(b)], "file_path": out},
    }})
    text = resp["result"]["content"][0]["text"]
    assert not text.startswith("Error calling")
    assert out in text


def test_coverage_error_wrapped_in_process(monkeypatch):
    """spec §5.2 指名 CoverageError：进程内经 _safe_summary 验证指引文本完整。

    注：provider 在 server 模块内以 ``_`` 前缀别名导入（避免被同名薄工具函数遮蔽），
    故 monkeypatch 目标是 ``server._query_futures``。
    """
    def _boom(**kwargs):
        raise CoverageError("分钟深度覆盖不足 2026-08-01~2026-08-27，补数：收窄区间或改日线")

    monkeypatch.setattr(server, "_query_futures", _boom)
    text = server._safe_summary("query_futures", {"symbol": "IM0", "file_path": "x.csv"})
    assert text.startswith("Error calling query_futures")
    assert "补数" in text
    assert "Error executing tool" not in text
