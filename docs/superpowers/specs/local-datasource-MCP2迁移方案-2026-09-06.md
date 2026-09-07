# local-datasource MCP 2.x 迁移方案

> **日期** 2026-09-06 ｜ **状态** 待评审/待执行 ｜ **文档角色** 迁移设计（由 Quant-Research 项目产出，供 local-datasource 仓库的执行者使用）
> **背景**：local-datasource 当前钉死 `mcp>=1.6,<2`，与需要 mcp 2.x 的环境（如 Quant-Research）无法在同一 Python 环境共存。本文档给出迁移到 mcp 2.x 的完整方案。**执行本文档时请遵守 local-datasource 仓库自身的规范；本方案不动 providers 层任何代码。**

---

## 1. 问题陈述

- mcp 2.x 移除了 1.x 的 `Server` 装饰器注册 API（`@server.list_tools()` / `@server.call_tool()`），旧代码在 mcp 2.1.1 下初始化即抛 `AttributeError`；
- 当前处置（commit `6455c77` 钉 `mcp>=1.6,<2`）是**止血**：防止误装 2.x 后服务挂掉，但代价是与其他需要 2.x 的 MCP 服务不能共享环境；
- 目标：入口层迁到 mcp 2.x 官方高层 API，依赖改为 `mcp>=2.0.0,<3`，一劳永逸。

## 2. 现状诊断（只涉及入口层）

`src/local_datasource/server.py` 中与 mcp 版本耦合的只有四处：

| 位置 | 现状 | 说明 |
|---|---|---|
| import 区 | `from mcp.server import Server`、`from mcp.server.stdio import stdio_server`、`from mcp.types import TextContent, Tool` | v1 风格 |
| `_main()` | `server = Server(APP_NAME)` | 实例化 v1 Server |
| 注册 | `@server.list_tools()`（返回 `list[Tool]`）+ `@server.call_tool()`（转发到 `handle_call_tool`） | **2.x 已移除此装饰器对** |
| 业务分发 | `handle_call_tool(name, arguments) -> list[TextContent]`（386 行起，16 个 tool 的 if/elif 分发） | 与 mcp 版本无关，**可整体保留** |

**关键结论**：providers/ 下 16 个数据适配器与 mcp 零耦合，本次迁移**只改 server.py 入口层 + pyproject**，业务代码零改动。

## 3. 迁移蓝本（已生产验证，可直接对照）

Quant-Research 仓库 `E:\LLMproject\Github\Quant-Research\src\quantresearch\mcp_server.py`（174 行，4 工具，mcp 2.1.1 实测运行，含回归测试）就是按 local-datasource 同构结构写的 2.x 版本。核心模式：

```python
from mcp.server.mcpserver import MCPServer

mcp = MCPServer(APP_NAME)

@mcp.tool()
def query_xxx(...) -> str:
    """工具描述（成为客户端可见的 tool schema）"""
    return _safe_summary("query_xxx", {...args...})

def _safe_summary(name: str, arguments: dict) -> str:
    try:
        path, summary = <业务函数>(**arguments)
        return summary            # 摘要文本回传（路径+前5行预览，维持现有格式）
    except Exception as exc:
        return f"❌ {name} 执行失败：{exc}\n补数指引：…"   # 见 §4 第2条

if __name__ == "__main__":
    mcp.run()                     # 缺省 stdio 传输
```

## 4. 两条实战教训（来自 Quant-Research 迁移，务必重视）

1. **工具数量多时用集中注册**：Quant-Research 只有 4 个工具用装饰器即可；local-datasource 有 16 个，建议保留现有 `build_tools()` 的 InputSchema 构造逻辑，把 `list[Tool]` 换成 2.x 的注册调用（或在每个业务函数上包一层薄装饰器生成器），避免 16 段重复样板。选型由执行者定，验收只看行为。
2. **错误必须显式包装（本仓库文化红线）**：mcp 2.x 高层 API 会把业务异常吞成裸 `Error executing tool <name>`——这意味着 `CoverageError` 的"明确报错+补数指引"根本到不了客户端。**必须**像蓝本那样统一 `_safe_summary` 包装，保证任何失败都以带指引的文本返回。Quant-Research 为此修过一次 BLOCKING 缺陷（fe9ed77），勿重蹈。
3. **stdio 探针测试**：蓝本配套了 subprocess 起服务 → JSON-RPC 三步探针（`initialize` 应答 serverInfo → `tools/list` 校验工具清单 → `tools/call` 真实调用）的测试，建议一并移植，作为长期回归门。

## 5. 迁移步骤（建议顺序，构造细节自由）

1. `pyproject.toml`：`mcp>=1.6.0,<2` → `mcp>=2.0.0,<3`；
2. 重写 `server.py` 入口层（注册方式见 §4.1，`handle_call_tool` 的 16 分支业务分发逻辑原样搬入各工具函数或保留集中分发均可）；
3. 接入 `_safe_summary` 统一错误包装（§4.2）；
4. 测试：现有 `tests/` 全量回归 + 新增 stdio 探针测试（§4.3），其中必须包含一条"构造 CoverageError 样例 → 客户端收到完整错误文本与补数指引"的断言；
5. 文档同步：`README.md` / `SKILL.md` 中 MCP 配置说明、依赖表述（如有"mcp 1.x"字样）一并更新。

## 6. 验收标准

- [ ] 依赖声明为 `mcp>=2.0.0,<3`，干净环境安装后 `local-datasource` 可启动；
- [ ] `initialize` 探针应答含 `serverInfo.name`；
- [ ] `tools/list` 列出全部 16 个工具，名称与现有清单一致；
- [ ] 任选 3 个工具 `tools/call` 真实调用：返回 CSV 落盘路径 + 前 5 行预览（与现有输出格式一致）；
- [ ] 构造覆盖不足样例：错误文本（含补数指引）完整到达客户端，不是裸 `Error executing tool`；
- [ ] 现有 `tests/` 全量通过；README/SKILL 同步无残留 1.x 表述。

## 7. 风险与回滚

| 风险 | 评估 |
|---|---|
| MCP 客户端兼容性 | stdio 传输 + 协议版本协商是 MCP 基本面，主流客户端（Claude Code/Codex/Cursor 等）均支持 2.x 服务端；如遇老客户端只认 1.x，可临时回退钉版分支 |
| 回滚 | 单 PR 变更（server.py + pyproject + 测试 + 文档），`git revert` 即整体回滚 |
| 并存期 | 迁移合入前，1.x 钉版现状继续可用（当前无实际故障场景） |

## 8. 与 Quant-Research 的关系

迁移完成后，两个 MCP 服务可共存于同一 Python 环境（本项目 `mcp_server.py` 已是 2.x）。Quant-Research 侧**库直调**路径与本次迁移无关（providers 不动），不存在联动风险。
